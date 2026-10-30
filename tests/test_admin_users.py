import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from app.models import Dashboard, GroupDashboards
from app.utils.permissions_report import permissions_report_pdf, user_permissions_report
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


@pytest.fixture
def report_users():
    group = Group.objects.create(name='Almoxarifado')
    view_toner = Permission.objects.get(content_type__app_label='app', codename='view_toner')
    change_toner = Permission.objects.get(content_type__app_label='app', codename='change_toner')
    group.permissions.add(view_toner, change_toner)
    GroupDashboards.objects.create(group=group).dashboards.add(Dashboard.objects.create(title='Estoque'))

    operator = User.objects.create_user(username='operador', password='senha', first_name='Ana & <Cia>', is_active=False)
    operator.groups.add(group)
    operator.user_permissions.add(view_toner)
    operator.dashboards.add(Dashboard.objects.create(title='Frota'))
    User.objects.create_user(username='sem-acesso', password='senha')
    User.objects.create_superuser(username='admin', password='senha')
    return User.objects.all()


@pytest.mark.django_db
def test_permissions_report_shows_where_each_access_comes_from(report_users):
    report = {item['user'].username: item for item in user_permissions_report(report_users)}
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


@pytest.mark.django_db
def test_permissions_report_action_downloads_a_pdf(client, report_users):
    admin_user = User.objects.get(username='admin')
    sign_in(client, admin_user)

    response = client.post(reverse('admin:app_user_changelist'), {
        'action': 'permissions_report',
        '_selected_action': [user.pk for user in report_users],
        'index': '0',
    })

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'
    assert response['Content-Disposition'].startswith('attachment; filename="relatorio-permissoes-')
    # O nome com & e < chega escapado à ReportLab: sem isso, o PDF nem seria gerado
    assert response.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_permissions_report_starts_the_user_on_the_first_page():
    user = User.objects.create_user(username='operador', password='senha')
    user.user_permissions.add(*Permission.objects.order_by('pk')[:30])

    pdf = permissions_report_pdf(user_permissions_report(User.objects.all()), 'admin')

    # Uma tabela que não cabe no resto da página começa nela e continua na seguinte:
    # empurrada inteira para a página 2, a primeira ficava só com o título do relatório
    assert re.search(rb'/Count (\d+)', pdf).group(1) == b'2'
