from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from app.models import Dashboard


def describe_permission(permission):
    content_type = permission.content_type
    model = content_type.model_class()
    return {
        'app': apps.get_app_config(content_type.app_label).verbose_name,
        'model': model._meta.verbose_name if model else content_type.model,
        'name': permission.name,
        'codename': f'{content_type.app_label}.{permission.codename}',
    }


def user_permissions_report(users):
    """O que cada usuário pode fazer no portal, e de onde vem cada acesso."""
    users = users.prefetch_related(
        'user_permissions__content_type',
        'groups__permissions__content_type',
        'groups__perfil__dashboards',
        'dashboards',
    ).order_by('username')
    all_dashboards = list(Dashboard.objects.select_related('sector'))

    report = []
    for user in users:
        groups = list(user.groups.all())

        # A mesma permissão pode chegar direto e por mais de um grupo: todas as
        # origens aparecem, para se saber o que tirar para revogar o acesso
        permissions = {}
        for permission in user.user_permissions.all():
            permissions.setdefault(permission, []).append('Direta')
        for group in groups:
            for permission in group.permissions.all():
                permissions.setdefault(permission, []).append(f'Grupo {group.name}')

        rows = sorted(
            ({**describe_permission(permission), 'sources': sources} for permission, sources in permissions.items()),
            key=lambda row: (row['app'], str(row['model']), row['name']),
        )

        # As mesmas regras do get_user_dashboards, mas guardando a origem de cada acesso
        sees_all = user.is_superuser or any(row['codename'] == 'app.view_all_dashboards' for row in rows)
        dashboards = {}
        for dashboard in user.dashboards.all():
            dashboards.setdefault(dashboard, []).append('Direto')
        for group in groups:
            try:
                profile_dashboards = group.perfil.dashboards.all()
            except ObjectDoesNotExist:
                continue
            for dashboard in profile_dashboards:
                dashboards.setdefault(dashboard, []).append(f'Grupo {group.name}')
        if sees_all:
            origin = 'Superusuário' if user.is_superuser else 'Ver todos os dashboards'
            for dashboard in all_dashboards:
                dashboards.setdefault(dashboard, []).append(origin)

        report.append({
            'user': user,
            'groups': [group.name for group in groups],
            'permissions': rows,
            'dashboards': sorted(
                ({'title': dashboard.title, 'sources': sources} for dashboard, sources in dashboards.items()),
                key=lambda row: row['title'],
            ),
        })
    return report
