"""
O que cada card de acesso rápido da home mostra do seu serviço.

Só é montado o preview dos serviços que o usuário pode abrir: quem não vê o
card não paga as consultas dele. Os serviços sem preview dinâmico (chamados,
que é um sistema de fora, e o cadastro de clientes e fornecedores, que é um
formulário) ficam com o desenho estático do template.
"""
from django.db.models import F

from app.models import Contact, ServiceAccess, Toner
from app.utils.dashboards.access import get_user_dashboards
from app.utils.notifications.delivery import serialize_notification, visible_notifications
from app.utils.services import arranged_services


LATEST_NOTIFICATIONS = 3

FAVORITE_DASHBOARDS = 4

LOW_TONERS = 4


def contacts_preview(user):
    # A busca do card roda no navegador, como a da lista de contatos
    return {
        'contacts': [
            {
                'name': contact.get_display_name(),
                'number': contact.number or '',
                'sector': contact.sector.name if contact.sector else '',
            }
            for contact in Contact.objects.select_related('sector', 'user')
        ],
    }


def notifications_preview(user):
    notifications = visible_notifications(user)
    return {
        'unread_count': notifications.filter(is_read=False).count(),
        'latest': [
            serialize_notification(notification)
            for notification in notifications.order_by('-start_at')[:LATEST_NOTIFICATIONS]
        ],
    }


def dashboards_preview(user):
    dashboards = get_user_dashboards(user)
    return {
        'total': dashboards.count(),
        'favorites': [
            {'title': dashboard.title, 'url': dashboard.get_absolute_url()}
            for dashboard in dashboards.filter(fav_by=user).order_by('title')[:FAVORITE_DASHBOARDS]
        ],
    }


def toners_preview(user):
    low = Toner.objects.select_related('location').filter(quantity__lte=F('minimum_quantity'))
    return {
        'low_count': low.count(),
        'low': [
            {
                'name': toner.name,
                'location': toner.location.name if toner.location else '',
                'quantity': toner.quantity,
                'minimum_quantity': toner.minimum_quantity,
                'requested_quantity': toner.requested_quantity,
            }
            for toner in low.order_by('quantity', 'name')[:LOW_TONERS]
        ],
    }


def journey_audit_preview(user):
    # Importado aqui: a auditoria já depende do app, e não o contrário
    from journey_audit.audit import competencies_queryset, current_period

    start, end = current_period()
    competency = competencies_queryset().filter(start_date=start, end_date=end).first()
    return {
        'start_date': start,
        'end_date': end,
        'competency': competency and {
            'occurrence_count': competency.occurrence_count,
            'pending_count': competency.pending_count,
            'finished_at': competency.finished_at,
        },
    }


PREVIEWS = {
    ServiceAccess.CONTACTS: contacts_preview,
    ServiceAccess.NOTIFICATIONS: notifications_preview,
    ServiceAccess.DASHBOARDS: dashboards_preview,
    ServiceAccess.TONERS: toners_preview,
    ServiceAccess.JOURNEY_AUDIT: journey_audit_preview,
}


def quick_access_cards(user):
    # Os ocultos também vão para a página: é no modo de personalizar que o
    # usuário volta a exibi-los, e o card já chega pronto
    cards = []
    for service, hidden in arranged_services(user):
        build = PREVIEWS.get(service.key)
        cards.append({
            'service': service,
            'hidden': hidden,
            'preview': build(user) if build else None,
        })
    return cards
