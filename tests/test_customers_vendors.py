from unittest.mock import patch
import json

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from app.models import User


@pytest.fixture
def operator(db, client):
    user = User.objects.create_user(username='cadastro', password='senha')
    user.user_permissions.add(Permission.objects.get(
        content_type__app_label='app', codename='register_customers_suppliers',
    ))
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_registration_requires_login_and_permission(client):
    url = reverse('app:customers-vendors')
    assert client.get(url).status_code == 302
    client.force_login(User.objects.create_user(username='sem-permissao'))
    with patch('app.views.register_customers_vendors') as register:
        assert client.get(url).status_code == 403
        assert client.post(url, {'cnpj': '123'}).status_code == 403
        register.assert_not_called()
    assert url.encode() not in client.get(reverse('app:home')).content


@pytest.mark.django_db
@pytest.mark.parametrize('status', ['created', 'skipped', 'error'])
def test_registration_shows_service_message(client, operator, status):
    entry = {'cnpj': '12.345.678/0001-90', 'ie': 'isento', 'type': 'a'}
    data = {
        'summary': {'total': 1, 'created': 0, 'skipped': 0, 'errors': 0},
        'results': [{'cnpj': entry['cnpj'], 'status': status, 'message': 'Mensagem do cadastro <teste>'}],
    }
    with patch('app.views.register_customers_vendors', return_value=data) as register:
        response = client.post(reverse('app:customers-vendors'), entry)
    register.assert_called_once_with([entry])
    assert response.status_code == 200
    assert b'Mensagem do cadastro &lt;teste&gt;' in response.content
    assert f'result-{status}'.encode() in response.content
    assert reverse('app:customers-vendors').encode() in client.get(reverse('app:home')).content


@pytest.mark.django_db
def test_registration_enforces_csrf(operator):
    client = Client(enforce_csrf_checks=True)
    client.force_login(operator)
    with patch('app.views.register_customers_vendors') as register:
        assert client.post(reverse('app:customers-vendors'), {'cnpj': '123'}).status_code == 403
        register.assert_not_called()


@pytest.mark.django_db
def test_invalid_cnpj_uses_existing_validation(client, operator):
    with patch('app.utils.customer_vendor.registration.execute_query') as query:
        response = client.post(reverse('app:customers-vendors'), {
            'cnpj': '123', 'ie': '', 'type': 'c',
        })
        query.assert_not_called()
    assert 'Cnpj inválido!'.encode() in response.content


@pytest.mark.django_db
def test_batch_registration_preserves_failed_entries(client, operator):
    entries = [
        {'cnpj': '123', 'ie': '', 'type': 'c'},
        {'cnpj': '456', 'ie': 'isento', 'type': 'f'},
    ]
    data = {
        'summary': {'total': 2, 'created': 1, 'skipped': 0, 'errors': 1},
        'results': [
            {'status': 'created', 'message': 'Primeiro cadastrado'},
            {'status': 'error', 'message': 'Segundo com erro'},
        ],
    }
    with patch('app.views.register_customers_vendors', return_value=data) as register:
        response = client.post(reverse('app:customers-vendors'), {
            'customers_vendors': json.dumps(entries),
        })
    register.assert_called_once_with(entries)
    assert response.context['pending'] == [entries[1]]
    assert b'Primeiro cadastrado' in response.content
    assert b'Segundo com erro' in response.content


@pytest.mark.django_db
@pytest.mark.parametrize('payload', ['[]', '{}', 'invalid'])
def test_invalid_batch_does_not_register(client, operator, payload):
    with patch('app.views.register_customers_vendors') as register:
        response = client.post(reverse('app:customers-vendors'), {'customers_vendors': payload})
    register.assert_not_called()
    assert response.context['batch_error']
