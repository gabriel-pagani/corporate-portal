import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from app.models import Dashboard, GroupDashboards
from tests.conftest import sign_in


User = get_user_model()


@pytest.mark.django_db
def test_admin_can_deactivate_selected_users(client):
    admin_user = User.objects.create_superuser(username='admin', password='senha')
    first = User.objects.create_user(username='primeiro', password='senha')
    second = User.objects.create_user(username='segundo', password='senha')
    already_inactive = User.objects.create_user(username='inativo', password='senha', is_active=False)
    sign_in(client, admin_user)

    response = client.post(reverse('admin:app_user_changelist'), {
        'action': 'deactivate_users',
        '_selected_action': [first.pk, second.pk, already_inactive.pk],
        'index': '0',
    }, follow=True)

    assert response.status_code == 200
    first.refresh_from_db()
    second.refresh_from_db()
    already_inactive.refresh_from_db()
    assert not first.is_active
    assert not second.is_active
    assert not already_inactive.is_active
    assert b'2 usu\xc3\xa1rio(s) desativado(s) com sucesso.' in response.content


@pytest.mark.django_db
def test_permissions_report_shows_where_each_access_comes_from(client):
    from django.contrib.auth.models import Group, Permission
    from app.models import Dashboard, GroupDashboards

    admin_user = User.objects.create_superuser(username='admin', password='senha')
    group = Group.objects.create(name='Almoxarifado')
    view_toner = Permission.objects.get(content_type__app_label='app', codename='view_toner')
    change_toner = Permission.objects.get(content_type__app_label='app', codename='change_toner')
    group.permissions.add(view_toner, change_toner)
    group_dashboard = Dashboard.objects.create(title='Estoque')
    GroupDashboards.objects.create(group=group).dashboards.add(group_dashboard)
    own_dashboard = Dashboard.objects.create(title='Frota')

    operator = User.objects.create_user(username='operador', password='senha', first_name='Ana', is_active=False)
    operator.groups.add(group)
    operator.user_permissions.add(view_toner)
    operator.dashboards.add(own_dashboard)
    plain = User.objects.create_user(username='sem-acesso', password='senha')
    sign_in(client, admin_user)

    response = client.post(reverse('admin:app_user_changelist'), {
        'action': 'permissions_report',
        '_selected_action': [operator.pk, plain.pk, admin_user.pk],
        'index': '0',
    })

    assert response.status_code == 200
    report = {item['user'].username: item for item in response.context['report']}
    assert list(report) == ['admin', 'operador', 'sem-acesso']

    permissions = {row['codename']: row['sources'] for row in report['operador']['permissions']}
    assert permissions == {
        'app.change_toner': ['Grupo Almoxarifado'],
        'app.view_toner': ['Direta', 'Grupo Almoxarifado'],
    }
    assert report['operador']['groups'] == ['Almoxarifado']
    assert [(row['title'], row['sources']) for row in report['operador']['dashboards']] == [
        ('Estoque', ['Grupo Almoxarifado']), ('Frota', ['Direto']),
    ]
    assert report['sem-acesso']['permissions'] == [] and report['sem-acesso']['dashboards'] == []
    assert [row['sources'] for row in report['admin']['dashboards']] == [['Superusuário'], ['Superusuário']]

    content = response.content.decode()
    assert 'Usuário inativo' in content
    assert 'Superusuário: tem todas as permissões do sistema' in content
    assert 'Direta, Grupo Almoxarifado' in content
