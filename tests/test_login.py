import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.urls import reverse
from app.models import User
from app.utils import throttle
from app.views import LOGIN_THROTTLED_ERROR


# O client.login() não serve aqui: ele chama o authenticate() sem request, e o
# backend do axes exige o request para saber de qual IP veio a tentativa. Estes
# testes entram pela tela, que é por onde as pessoas entram.
def attempt(client, username='operador', password='senha'):
    return client.post(reverse('app:login'), {'username': username, 'password': password})


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


@pytest.fixture
def user(db):
    return User.objects.create_user(username='operador', password='senha')


@pytest.mark.django_db
def test_login_redirects_to_home(client, user):
    response = attempt(client)
    assert response.status_code == 302
    assert response.url == reverse('app:home')


@pytest.mark.django_db
def test_wrong_password_does_not_say_which_field_failed(client, user):
    response = attempt(client, password='errada')
    assert messages_of(response) == ['Dados inválidos!']


@pytest.mark.django_db
def test_failures_are_counted_by_username(client, user):
    attempt(client, password='errada')
    assert throttle.login_blocked('operador') is False
    assert client.session.get('_auth_user_id') is None


@pytest.mark.django_db
def test_success_clears_the_failure_count(client, user):
    attempt(client, password='errada')
    attempt(client)
    # A conta zerada é o que diz que o teto é para o palpite automático, e não
    # para quem errou a senha e depois acertou.
    assert cache.get(throttle.login_key('operador')) is None


@pytest.mark.django_db
def test_username_over_the_limit_is_blocked_with_the_right_password(client, user):
    for _ in range(throttle.LOGIN_FAILURES_LIMIT):
        throttle.login_failure('operador')

    response = attempt(client)

    assert messages_of(response) == [LOGIN_THROTTLED_ERROR]
    assert client.session.get('_auth_user_id') is None


@pytest.mark.django_db
def test_upper_case_username_counts_for_the_same_limit(client, user):
    for _ in range(throttle.LOGIN_FAILURES_LIMIT):
        throttle.login_failure('OPERADOR')

    assert throttle.login_blocked('operador') is True


@pytest.mark.django_db
def test_axes_blocks_the_pair_after_the_failure_limit(client, settings, user):
    for _ in range(settings.AXES_FAILURE_LIMIT):
        attempt(client, password='errada')

    response = attempt(client)

    assert messages_of(response) == [LOGIN_THROTTLED_ERROR]
    assert client.session.get('_auth_user_id') is None
