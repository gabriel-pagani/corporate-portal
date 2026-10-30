"""
O segundo fator dos administradores, na tela principal e no painel.

Quem já cadastrou o aplicativo não entra sem o código; quem ainda não cadastrou
entra com a senha, mas não anda no portal antes de cadastrar. Usuário comum
continua entrando só com a senha.
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from app.models import User
from app.utils.otp import secret_of
from app.views import PENDING_LOGIN, PENDING_LOGIN_TIMEOUT
from tests.conftest import sign_in


PASSWORD = 'senha'


@pytest.fixture
def staff(db):
    return User.objects.create_user(username='equipe', password=PASSWORD, is_staff=True)


@pytest.fixture
def common(db):
    return User.objects.create_user(username='operador', password=PASSWORD)


def code(device):
    """O código que o aplicativo mostraria agora para este dispositivo."""
    return format(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits), f'0{device.digits}d')


def enter(client, user, **extra):
    return client.post(reverse('app:login'), {'username': user.username, 'password': PASSWORD, **extra})


def confirm(client, token):
    return client.post(reverse('app:login-token'), {'token': token})


def verified(client):
    return DEVICE_ID_SESSION_KEY in client.session


def logged_in(client):
    return '_auth_user_id' in client.session


# Login -------------------------------------------------------------------

def test_common_user_enters_with_the_password_only(client, common):
    response = enter(client, common)

    assert response.url == reverse('app:home')
    assert client.get(reverse('app:home')).status_code == 200


def test_password_alone_does_not_open_the_staff_session(client, staff):
    TOTPDevice.objects.create(user=staff, name='default', confirmed=True)

    response = enter(client, staff)

    assert response.url == reverse('app:login-token')
    assert not logged_in(client)


def test_superuser_also_needs_the_code(client, db):
    admin = User.objects.create_superuser(username='admin', password=PASSWORD)
    TOTPDevice.objects.create(user=admin, name='default', confirmed=True)

    assert enter(client, admin).url == reverse('app:login-token')


def test_right_code_opens_a_verified_session(client, staff):
    device = TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff)

    response = confirm(client, code(device))

    assert response.url == reverse('app:home')
    assert logged_in(client)
    assert verified(client)


def test_wrong_code_does_not_enter(client, staff):
    device = TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff)

    wrong = format((int(code(device)) + 1) % 10 ** device.digits, f'0{device.digits}d')
    confirm(client, wrong)

    assert not logged_in(client)


def test_wrong_password_does_not_reach_the_code(client, staff):
    TOTPDevice.objects.create(user=staff, name='default', confirmed=True)

    client.post(reverse('app:login'), {'username': staff.username, 'password': 'errada'})

    assert client.get(reverse('app:login-token')).url == reverse('app:login')


def test_code_of_another_user_does_not_work(client, staff):
    TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    other = User.objects.create_user(username='outro', password=PASSWORD, is_staff=True)
    other_device = TOTPDevice.objects.create(user=other, name='default', confirmed=True)
    enter(client, staff)

    confirm(client, code(other_device))

    assert not logged_in(client)


def test_code_step_without_the_password_goes_back_to_login(client, db):
    assert client.get(reverse('app:login-token')).url == reverse('app:login')


def test_the_wait_expires_and_the_password_is_asked_again(client, staff):
    device = TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff)

    session = client.session
    since = timezone.now() - PENDING_LOGIN_TIMEOUT - timedelta(seconds=1)
    session[PENDING_LOGIN] = {**session[PENDING_LOGIN], 'since': since.isoformat()}
    session.save()

    response = confirm(client, code(device))

    assert response.url == reverse('app:login')
    assert not logged_in(client)


def test_opening_the_login_again_discards_the_wait(client, staff):
    TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff)

    client.get(reverse('app:login'))

    assert PENDING_LOGIN not in client.session


def test_account_deactivated_between_the_steps_does_not_enter(client, staff):
    device = TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff)
    User.objects.filter(pk=staff.pk).update(is_active=False)

    confirm(client, code(device))

    assert not logged_in(client)


def test_next_survives_both_steps(client, staff):
    device = TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    enter(client, staff, next=reverse('app:contacts'))

    assert confirm(client, code(device)).url == reverse('app:contacts')


# Cadastro ----------------------------------------------------------------

def test_staff_without_app_enters_and_is_sent_to_setup(client, staff):
    enter(client, staff)

    assert logged_in(client)
    assert client.get(reverse('app:home')).url == reverse('app:otp-setup')


@pytest.mark.parametrize('route', ['app:home', 'app:contacts', 'app:notifications-api', 'admin:index'])
def test_portal_and_admin_are_blocked_until_setup(client, staff, route):
    enter(client, staff)

    assert client.get(reverse(route)).url == reverse('app:otp-setup')


def test_setup_page_shows_qr_code_and_secret(client, staff):
    enter(client, staff)

    content = client.get(reverse('app:otp-setup')).content.decode()
    device = TOTPDevice.objects.get(user=staff)

    assert '<svg' in content
    assert secret_of(device) in content
    assert not device.confirmed


def test_reloading_setup_keeps_the_same_secret(client, staff):
    enter(client, staff)

    client.get(reverse('app:otp-setup'))
    client.get(reverse('app:otp-setup'))

    assert TOTPDevice.objects.filter(user=staff).count() == 1


def test_setup_with_wrong_code_does_not_confirm(client, staff):
    enter(client, staff)
    client.get(reverse('app:otp-setup'))

    client.post(reverse('app:otp-setup'), {'token': '000000'})

    assert not TOTPDevice.objects.get(user=staff).confirmed
    assert not verified(client)


def test_confirmed_setup_opens_portal_and_admin(client, staff):
    enter(client, staff)
    client.get(reverse('app:otp-setup'))
    device = TOTPDevice.objects.get(user=staff)

    response = client.post(reverse('app:otp-setup'), {'token': code(device)})

    assert response.url == reverse('app:home')
    assert TOTPDevice.objects.get(user=staff).confirmed
    assert client.get(reverse('app:home')).status_code == 200
    assert client.get(reverse('admin:index')).status_code == 200


def test_who_already_has_the_app_does_not_set_up_again(client, staff):
    sign_in(client, staff)

    assert client.get(reverse('app:otp-setup')).url == reverse('app:home')
    assert TOTPDevice.objects.filter(user=staff).count() == 1


def test_common_user_has_no_setup(client, common):
    enter(client, common)

    assert client.get(reverse('app:otp-setup')).url == reverse('app:home')
    assert not TOTPDevice.objects.filter(user=common).exists()


def test_session_opened_without_the_code_is_ended(client, staff):
    # Uma sessão aberta antes de o segundo fator existir: o usuário já tem o
    # aplicativo, mas a sessão nunca passou pelo código.
    TOTPDevice.objects.create(user=staff, name='default', confirmed=True)
    client.force_login(staff)

    response = client.get(reverse('app:home'))

    assert response.url == reverse('app:login')
    assert not logged_in(client)


def test_logout_works_in_the_middle_of_setup(client, staff):
    enter(client, staff)

    client.post(reverse('app:logout'))

    assert not logged_in(client)


# Painel ------------------------------------------------------------------

def test_admin_login_goes_to_the_portal_login(client, db):
    response = client.get(reverse('admin:login') + '?next=/admin/')

    assert response.url == reverse('app:login') + '?next=/admin/'


def test_admin_requires_a_verified_session(client, staff):
    sign_in(client, staff)

    assert client.get(reverse('admin:index')).status_code == 200
