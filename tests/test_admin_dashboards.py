import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from app.models import Dashboard, GroupDashboards
from tests.conftest import sign_in


User = get_user_model()


@pytest.mark.django_db
def test_dashboard_admin_lists_users_with_access_and_origin():
    dashboard = Dashboard.objects.create(title='Folha de Pagamento')
    other = Dashboard.objects.create(title='Faturamento')

    direct = User.objects.create_user(username='direto', password='senha')
    direct.dashboards.add(dashboard)

    group = Group.objects.create(name='RH')
    GroupDashboards.objects.create(group=group).dashboards.add(dashboard)
    by_group = User.objects.create_user(username='porgrupo', password='senha')
    by_group.groups.add(group)

    view_all = User.objects.create_user(username='vetodos', password='senha')
    view_all.user_permissions.add(Permission.objects.get(codename='view_all_dashboards'))

    superuser = User.objects.create_superuser(username='admin', password='senha')

    without_access = User.objects.create_user(username='semacesso', password='senha')
    without_access.dashboards.add(other)

    inactive = User.objects.create_user(username='inativo', password='senha', is_active=False)
    inactive.dashboards.add(dashboard)

    result = site._registry[Dashboard].get_users_with_access(dashboard)

    assert '<td>direto</td><td>Direto</td>' in result
    assert '<td>porgrupo</td><td>Grupo RH</td>' in result
    assert '<td>vetodos</td><td>Ver todos os dashboards</td>' in result
    assert '<td>admin</td><td>Superusuário</td>' in result
    assert '&lt;' not in result
    assert 'semacesso' not in result
    assert 'inativo' not in result


@pytest.mark.django_db
def test_dashboard_admin_change_page_shows_users_with_access(client):
    superuser = User.objects.create_superuser(username='admin', password='senha')
    dashboard = Dashboard.objects.create(title='Folha de Pagamento')
    sign_in(client, superuser)

    response = client.get(reverse('admin:app_dashboard_change', args=[dashboard.pk]))

    assert response.status_code == 200
    assert 'Usuários com acesso' in response.content.decode()


@pytest.mark.django_db
def test_home_hides_dashboards_menu_without_accessible_dashboard(client):
    Dashboard.objects.create(title='Faturamento')
    user = User.objects.create_user(username='semacesso', password='senha')
    sign_in(client, user)

    content = client.get(reverse('app:home')).content.decode()

    assert reverse('app:dashboards') not in content


@pytest.mark.django_db
def test_home_shows_dashboards_menu_with_direct_access(client):
    dashboard = Dashboard.objects.create(title='Faturamento')
    user = User.objects.create_user(username='direto', password='senha')
    user.dashboards.add(dashboard)
    sign_in(client, user)

    content = client.get(reverse('app:home')).content.decode()

    assert reverse('app:dashboards') in content


@pytest.mark.django_db
def test_home_shows_dashboards_menu_with_group_access(client):
    dashboard = Dashboard.objects.create(title='Faturamento')
    group = Group.objects.create(name='Financeiro')
    GroupDashboards.objects.create(group=group).dashboards.add(dashboard)
    user = User.objects.create_user(username='porgrupo', password='senha')
    user.groups.add(group)
    sign_in(client, user)

    content = client.get(reverse('app:home')).content.decode()

    assert reverse('app:dashboards') in content
