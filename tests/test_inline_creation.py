import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from app.models import Contact, Notification, User


def user_with_permission(client, codename):
    user = User.objects.create_user(username='editor', password='senha')
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label='app', codename=codename)
    )
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_contact_can_be_created_from_contacts_page(client):
    user_with_permission(client, 'add_contact')
    url = reverse('app:contacts')
    assert b'Cadastrar ramal' in client.get(url).content

    response = client.post(url, {'name': 'Recepcao', 'number': '1234', 'machine': 'PC-1'})
    assert response.status_code == 302
    assert Contact.objects.get().number == '1234'
    assert b'Recepcao' in client.get(url).content


@pytest.mark.django_db
def test_contact_creation_checks_permission_and_required_fields(client):
    url = reverse('app:contacts')
    assert client.post(url, {'name': 'Recepcao', 'number': '1234'}).status_code == 403
    assert not Contact.objects.exists()

    user_with_permission(client, 'add_contact')
    response = client.post(url, {'name': '', 'number': ''})
    assert response.status_code == 200
    assert response.context['contact_form'].errors
    assert not Contact.objects.exists()


@pytest.mark.django_db
def test_notification_can_be_created_for_a_group_from_board(client):
    user_with_permission(client, 'add_notification')
    group = Group.objects.create(name='Financeiro')
    url = reverse('app:notifications')
    assert b'Cadastrar notifica' in client.get(url).content

    response = client.post(url, {
        'title': 'Aviso', 'message': 'Reuniao', 'level': 'A',
        'groups': [str(group.id)], 'start_at': '2026-09-24T10:00',
        'is_active': 'on',
    })
    assert response.status_code == 302
    notification = Notification.objects.get()
    assert list(notification.groups.all()) == [group]
    assert not notification.users.exists()


@pytest.mark.django_db
def test_notification_creation_checks_permission_and_dates(client):
    url = reverse('app:notifications')
    payload = {
        'title': 'Aviso', 'message': 'Texto', 'level': 'I',
        'start_at': '2026-09-24T10:00', 'end_at': '2026-09-24T09:00',
        'is_active': 'on',
    }
    user = User.objects.create_user(username='leitor', password='senha')
    client.force_login(user)
    assert b'Cadastrar notifica' not in client.get(url).content
    assert client.post(url, payload).status_code == 403

    user.user_permissions.add(
        Permission.objects.get(content_type__app_label='app', codename='add_notification')
    )
    response = client.post(url, payload)
    assert response.status_code == 200
    assert 'end_at' in response.context['notification_form'].errors
    assert not Notification.objects.exists()
