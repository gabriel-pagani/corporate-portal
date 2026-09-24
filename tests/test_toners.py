import json
import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from app.models import User, Toner, TonerLocation, TonerMovement


def make_user(*codenames):
    user = User.objects.create_user(username='operador', password='senha')
    user.user_permissions.set(Permission.objects.filter(content_type__app_label='app', codename__in=codenames))
    return user


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type='application/json')


@pytest.fixture
def location(db):
    return TonerLocation.objects.create(name='Almoxarifado')


@pytest.fixture
def operator(client):
    user = make_user('view_toner', 'add_toner', 'change_toner', 'delete_toner', 'add_tonermovement')
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_page_requires_view_permission(client):
    client.force_login(make_user())
    assert client.get(reverse('app:toners')).status_code == 403


@pytest.mark.django_db
def test_page_lists_toners(client, operator):
    Toner.objects.create(name='CF410A', quantity=3)
    response = client.get(reverse('app:toners'))
    assert response.status_code == 200
    assert b'CF410A' in response.content
    assert b'id="open-toner-modal"' in response.content
    assert b'<dialog id="toner-modal"' in response.content
    assert b'id="success-message"' in response.content
    assert b'Toners em estoque' not in response.content


@pytest.mark.django_db
def test_api_rejects_anonymous(client):
    assert client.get(reverse('app:toners-api')).status_code == 401


@pytest.mark.django_db
def test_is_low_uses_minimum_quantity():
    assert Toner(quantity=3, minimum_quantity=3).is_low
    assert not Toner(quantity=4, minimum_quantity=3).is_low
    assert not Toner(quantity=1, minimum_quantity=0).is_low


@pytest.mark.django_db
def test_create_records_initial_stock_as_movement(client, operator, location):
    response = post_json(client, reverse('app:toners-api'), {
        'name': 'CF411A', 'location': location.id, 'quantity': 5, 'minimum_quantity': 2,
    })
    assert response.status_code == 201

    toner = Toner.objects.get()
    assert (toner.quantity, toner.minimum_quantity, toner.location) == (5, 2, location)
    movement = toner.movements.get()
    assert (movement.type, movement.quantity, movement.user) == (TonerMovement.ENTRY, 5, operator)


@pytest.mark.django_db
def test_create_requires_name(client, operator):
    response = post_json(client, reverse('app:toners-api'), {'name': ' ', 'minimum_quantity': 1})
    assert response.status_code == 400
    assert not Toner.objects.exists()


@pytest.mark.django_db
def test_create_rejects_duplicated_name(client, operator):
    Toner.objects.create(name='CF411A', quantity=1)
    response = post_json(client, reverse('app:toners-api'), {'name': 'CF411A', 'minimum_quantity': 1})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Já existe um toner cadastrado com este nome.'
    assert Toner.objects.count() == 1


@pytest.mark.django_db
def test_update_does_not_change_quantity(client, operator, location):
    toner = Toner.objects.create(name='CF412A', quantity=4)
    response = post_json(client, reverse('app:toner-api', args=[toner.id]), {
        'name': 'CF412A', 'location': location.id, 'minimum_quantity': 5, 'quantity': 99,
    })
    assert response.status_code == 200
    assert response.json()['toner']['is_low'] is True

    toner.refresh_from_db()
    assert (toner.quantity, toner.minimum_quantity, toner.location) == (4, 5, location)


@pytest.mark.django_db
def test_name_changes_while_toner_has_no_movements(client, operator):
    toner = Toner.objects.create(name='CF412A', quantity=4)
    assert client.get(reverse('app:toners-api')).json()['toners'][0]['can_rename'] is True

    response = post_json(client, reverse('app:toner-api', args=[toner.id]), {
        'name': 'CF412B', 'minimum_quantity': 1,
    })
    assert response.status_code == 200

    toner.refresh_from_db()
    assert toner.name == 'CF412B'


@pytest.mark.django_db
def test_name_is_frozen_once_toner_has_movements(client, operator, location):
    toner = Toner.objects.create(name='CF412A', quantity=4)
    TonerMovement.objects.create(toner=toner, type=TonerMovement.EXIT, quantity=1)
    assert client.get(reverse('app:toners-api')).json()['toners'][0]['can_rename'] is False

    response = post_json(client, reverse('app:toner-api', args=[toner.id]), {
        'name': 'OUTRO', 'location': location.id, 'minimum_quantity': 1,
    })
    assert response.status_code == 200

    toner.refresh_from_db()
    assert (toner.name, toner.location) == ('CF412A', location)


@pytest.mark.django_db
def test_movements_update_stock(client, operator):
    toner = Toner.objects.create(name='CF413A', quantity=2)
    url = reverse('app:toner-movements-api', args=[toner.id])

    assert post_json(client, url, {'type': 'S', 'quantity': 2, 'reason': 'troca'}).status_code == 201
    assert post_json(client, url, {'type': 'E', 'quantity': 3}).status_code == 201

    toner.refresh_from_db()
    assert toner.quantity == 3
    history = client.get(url).json()['movements']
    assert [(m['type'], m['quantity']) for m in history] == [('E', 3), ('S', 2)]


@pytest.mark.django_db
def test_exit_cannot_exceed_stock(client, operator):
    toner = Toner.objects.create(name='CB435', quantity=1)
    response = post_json(client, reverse('app:toner-movements-api', args=[toner.id]), {'type': 'S', 'quantity': 2})
    assert response.status_code == 400

    toner.refresh_from_db()
    assert toner.quantity == 1
    assert not toner.movements.exists()


@pytest.mark.django_db
def test_movement_requires_permission(client):
    client.force_login(make_user('view_toner'))
    toner = Toner.objects.create(name='D204 TN', quantity=1)
    response = post_json(client, reverse('app:toner-movements-api', args=[toner.id]), {'type': 'E', 'quantity': 1})
    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_toner(client, operator):
    toner = Toner.objects.create(name='750-C', quantity=3)
    response = client.delete(reverse('app:toner-api', args=[toner.id]))
    assert response.status_code == 200
    assert not Toner.objects.exists()
