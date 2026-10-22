import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from app.models import Dashboard, GroupDashboards


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

    assert '(direto) — Direto' in result
    assert '(porgrupo) — Grupo RH' in result
    assert '(vetodos) — Ver todos os dashboards' in result
    assert '(admin) — Superusuário' in result
    assert 'semacesso' not in result
    assert 'inativo' not in result


@pytest.mark.django_db
def test_dashboard_admin_change_page_shows_users_with_access(client):
    superuser = User.objects.create_superuser(username='admin', password='senha')
    dashboard = Dashboard.objects.create(title='Folha de Pagamento')
    client.force_login(superuser)

    response = client.get(reverse('admin:app_dashboard_change', args=[dashboard.pk]))

    assert response.status_code == 200
    assert 'Usuários com acesso' in response.content.decode()
