import json
import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from app.models import Contact, Notification, Sector, User


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
    page = client.get(url)
    assert b'Cadastrar ramal' in page.content
    assert list(page.context['contact_form'].fields)[:2] == ['user', 'name']

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
def test_contact_edit_updates_row_and_checks_permission(client):
    sector = Sector.objects.create(name='Atendimento')
    contact = Contact.objects.create(name='Recepcao', number='1234')
    url = reverse('app:contact-update-api', args=[contact.id])
    payload = {
        'user': '', 'name': 'Portaria', 'number': '5678',
        'sector': sector.id, 'machine': 'PC-2',
    }

    user_with_permission(client, 'add_contact')
    assert client.post(url, json.dumps(payload), content_type='application/json').status_code == 403
    assert b'data-action' not in client.get(reverse('app:contacts')).content

    user = User.objects.get(username='editor')
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label='app', codename='change_contact')
    )
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['contact']['sector'] == 'Atendimento'
    contact.refresh_from_db()
    assert (contact.name, contact.number, contact.sector, contact.machine) == (
        'Portaria', '5678', sector, 'PC-2',
    )
    assert b'data-can-edit="1"' in client.get(reverse('app:contacts')).content

    payload['number'] = ''
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 400
    contact.refresh_from_db()
    assert contact.number == '5678'


@pytest.mark.django_db
def test_edit_preserves_linked_contact_user(client):
    user_with_permission(client, 'change_contact')
    linked_user = User.objects.create_user(username='vinculado', password='senha')
    contact = Contact.objects.create(user=linked_user, number='1000')
    url = reverse('app:contact-update-api', args=[contact.id])
    response = client.post(url, json.dumps({
        'user': linked_user.id, 'name': '', 'number': '1001', 'sector': '', 'machine': '',
    }), content_type='application/json')
    assert response.status_code == 200
    contact.refresh_from_db()
    assert contact.user == linked_user
    assert contact.number == '1001'


@pytest.mark.django_db
def test_edit_can_change_or_unlink_contact_user(client):
    user_with_permission(client, 'change_contact')
    first = User.objects.create_user(username='ana', first_name='Ana', password='senha')
    second = User.objects.create_user(username='bruno', first_name='Bruno', password='senha')
    contact = Contact.objects.create(user=first, number='1000')
    url = reverse('app:contact-update-api', args=[contact.id])
    page = client.get(reverse('app:contacts'))
    assert any(item['id'] == second.id for item in page.context['users'])

    payload = {'user': second.id, 'name': '', 'number': '1000', 'sector': '', 'machine': ''}
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['contact']['name'] == 'Bruno'
    contact.refresh_from_db()
    assert contact.user == second

    payload['name'] = 'Portaria'
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['contact']['name'] == 'Bruno'
    contact.refresh_from_db()
    assert contact.user == second
    assert contact.name == 'Portaria'

    payload['name'] = ''
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['contact']['name'] == 'Bruno'

    payload.update(user='', name='Recepcao')
    response = client.post(url, json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['contact']['name'] == 'Recepcao'
    contact.refresh_from_db()
    assert contact.user is None
    assert contact.name == 'Recepcao'

    payload['name'] = ''
    assert client.post(url, json.dumps(payload), content_type='application/json').status_code == 400
    contact.refresh_from_db()
    assert contact.name == 'Recepcao'


@pytest.mark.django_db
def test_contact_delete_requires_permission_and_keeps_linked_user(client):
    linked_user = User.objects.create_user(username='vinculado', password='senha')
    contact = Contact.objects.create(user=linked_user, number='1234')
    url = reverse('app:contact-update-api', args=[contact.id])
    editor = user_with_permission(client, 'add_contact')

    assert client.delete(url).status_code == 403
    assert Contact.objects.filter(id=contact.id).exists()

    editor.user_permissions.add(
        Permission.objects.get(content_type__app_label='app', codename='delete_contact')
    )
    page = client.get(reverse('app:contacts'))
    assert b'data-can-delete="1"' in page.content
    assert b'data-can-edit="0"' in page.content

    response = client.delete(url)
    assert response.status_code == 200
    assert not Contact.objects.filter(id=contact.id).exists()
    assert User.objects.filter(id=linked_user.id).exists()


@pytest.mark.django_db
def test_staff_sees_actions_column_for_copy_without_edit_permission(client):
    staff = User.objects.create_user(username='equipe', password='senha', is_staff=True)
    client.force_login(staff)
    Contact.objects.create(name='Recepcao', number='1234', machine='PC-1')

    response = client.get(reverse('app:contacts'))
    assert response.status_code == 200
    assert b'<th class="actions-heading"' in response.content
    assert b'data-can-edit="0"' in response.content
    assert b'data-can-delete="0"' in response.content


@pytest.mark.django_db
def test_notification_board_is_read_only_even_with_add_permission(client):
    user_with_permission(client, 'add_notification')
    notification = Notification.objects.create(title='Aviso', message='Texto')
    url = reverse('app:notifications')

    response = client.get(url)
    assert response.status_code == 200
    assert b'Cadastrar notifica' not in response.content
    assert [item['id'] for item in response.context['notifications']] == [notification.id]
    assert client.post(url, {'title': 'Outro', 'message': 'Texto'}).status_code == 405
    assert Notification.objects.count() == 1
