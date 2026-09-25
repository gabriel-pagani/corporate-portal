import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


User = get_user_model()


@pytest.mark.django_db
def test_admin_can_deactivate_selected_users(client):
    admin_user = User.objects.create_superuser(username='admin', password='senha')
    first = User.objects.create_user(username='primeiro', password='senha')
    second = User.objects.create_user(username='segundo', password='senha')
    already_inactive = User.objects.create_user(username='inativo', password='senha', is_active=False)
    client.force_login(admin_user)

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
