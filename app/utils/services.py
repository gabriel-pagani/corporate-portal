"""
Os serviços do portal, na ordem da barra lateral da home.

A home monta os cards de acesso rápido daqui, então a regra de quem vê cada
serviço é a mesma da barra lateral: o card só aparece para quem também vê o
link no menu.
"""
from dataclasses import dataclass
from functools import wraps
from typing import Callable

from django.db import IntegrityError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from app.models import HomeLayout, ServiceAccess
from app.utils.dashboards.access import get_user_dashboards


TICKETS_URL = 'http://servicos.gruposmi.com.br/front/ticket.php'

# A altura dos cards enquanto o usuário não escolhe outra, e os limites da que
# ele dá a um card ao redimensioná-lo, em pixels
CARD_DEFAULT_HEIGHT = 380

CARD_MIN_HEIGHT = 180

CARD_MAX_HEIGHT = 900


@dataclass(frozen=True)
class Service:
    key: str
    title: str
    icon: str
    url_name: str
    description: str
    is_available: Callable

    @property
    def url(self):
        return reverse(self.url_name)


def everyone(user):
    return True


def has_perm(perm):
    return lambda user: user.has_perm(perm)


SERVICES = [
    Service(
        ServiceAccess.CONTACTS, 'Lista de Contatos', 'fa-phone', 'app:contacts',
        'Ramais e setores de todos os colaboradores.', everyone,
    ),
    Service(
        ServiceAccess.NOTIFICATIONS, 'Mural de Notificações', 'fa-bullhorn', 'app:notifications',
        'Os avisos enviados para você.', everyone,
    ),
    Service(
        ServiceAccess.TICKETS, 'Central de Chamados', 'fa-headphones', 'app:tickets',
        'Abra e acompanhe chamados de suporte.', everyone,
    ),
    Service(
        ServiceAccess.DASHBOARDS, 'Central de Dashboards', 'fa-chart-pie', 'app:dashboards',
        'Os indicadores liberados para você.', lambda user: get_user_dashboards(user).exists(),
    ),
    Service(
        ServiceAccess.TONERS, 'Controle de Toners', 'fa-print', 'app:toners',
        'Estoque, movimentações e solicitações de toner.', has_perm('app.view_toner'),
    ),
    Service(
        ServiceAccess.CUSTOMERS_VENDORS, 'Clientes e Fornecedores', 'fa-address-card', 'app:customers-vendors',
        'Cadastro de clientes e fornecedores no RM pelo CNPJ.', has_perm('app.register_customers_suppliers'),
    ),
    Service(
        ServiceAccess.JOURNEY_AUDIT, 'Auditoria de Jornada', 'fa-user-clock', 'journey_audit:audit',
        'Conferência das ocorrências de ponto da competência.', has_perm('journey_audit.view_competency'),
    ),
]


def available_services(user):
    return [service for service in SERVICES if service.is_available(user)]


def ranked_services(user):
    """
    Os serviços que o usuário pode abrir, do mais acessado ao menos acessado.

    No empate vale o acesso mais recente, e o que nunca foi aberto fica na
    ordem da barra lateral.
    """
    accesses = {
        access.service: access
        for access in ServiceAccess.objects.filter(user=user)
    }
    services = available_services(user)
    position = {service.key: index for index, service in enumerate(services)}

    def rank(service):
        access = accesses.get(service.key)
        if access is None:
            return (0, 0, position[service.key])
        return (-access.count, -access.last_accessed_at.timestamp(), position[service.key])

    return sorted(services, key=rank)


def arranged_services(user):
    """
    Os serviços na ordem dos cards da home, cada um com a marca de oculto e a
    altura do card.

    Quem arrumou os cards vê do jeito que arrumou; os serviços que não estão
    no layout salvo entram no fim, na ordem dos acessos, com a altura padrão.
    """
    services = ranked_services(user)
    layout = HomeLayout.objects.filter(user=user).first()
    if layout is None:
        return [(service, False, CARD_DEFAULT_HEIGHT) for service in services]

    position = {key: index for index, key in enumerate(layout.order)}
    hidden = set(layout.hidden)
    # A ordenação é estável: os que ficam fora do layout mantêm a ordem dos acessos
    services = sorted(services, key=lambda service: position.get(service.key, len(position)))
    return [
        (service, service.key in hidden, layout.sizes.get(service.key, CARD_DEFAULT_HEIGHT))
        for service in services
    ]


def save_layout(user, order, hidden, sizes):
    """Guarda o layout; levanta ValueError se vier serviço que não existe ou altura fora dos limites."""
    known = {key for key, _ in ServiceAccess.SERVICES}
    for keys in (order, hidden):
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise ValueError('Envie a ordem e os ocultos como listas de serviços.')
        if set(keys) - known:
            raise ValueError('Serviço desconhecido.')
        if len(set(keys)) != len(keys):
            raise ValueError('Serviço repetido.')

    if not isinstance(sizes, dict):
        raise ValueError('Envie as alturas como um objeto de serviço e altura.')
    if set(sizes) - known:
        raise ValueError('Serviço desconhecido.')
    for height in sizes.values():
        # O bool é int no Python, e True viraria um card de 1 pixel
        if isinstance(height, bool) or not isinstance(height, int):
            raise ValueError('A altura do card deve ser um número inteiro.')
        if not CARD_MIN_HEIGHT <= height <= CARD_MAX_HEIGHT:
            raise ValueError(f'A altura do card deve ficar entre {CARD_MIN_HEIGHT} e {CARD_MAX_HEIGHT}.')

    HomeLayout.objects.update_or_create(
        user=user, defaults={'order': order, 'hidden': hidden, 'sizes': sizes},
    )


def register_access(user, service):
    now = timezone.now()
    accesses = ServiceAccess.objects.filter(user=user, service=service)
    # O incremento vai no banco: duas abas abrindo juntas não perdem acesso
    if accesses.update(count=F('count') + 1, last_accessed_at=now):
        return
    try:
        with transaction.atomic():
            ServiceAccess.objects.create(user=user, service=service, count=1, last_accessed_at=now)
    except IntegrityError:
        # Outra requisição criou a linha entre a atualização e a criação
        accesses.update(count=F('count') + 1, last_accessed_at=now)


def track_access(service):
    """
    Conta a abertura da página do serviço, para a ordem dos cards da home.

    Fica abaixo do login_required e do permission_required: só conta quem
    chegou a ver a página, e só a abertura (GET), não o envio de formulários.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            response = view(request, *args, **kwargs)
            if request.method == 'GET' and request.user.is_authenticated and response.status_code < 400:
                register_access(request.user, service)
            return response
        return wrapper
    return decorator
