from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .utils import throttle


# Os sinais valem para qualquer backend: a senha local e o LDAP contam para o
# mesmo teto, e o acerto por qualquer um dos dois zera a conta. Contar dentro de
# um backend só contaria o caminho dele — e o login por LDAP, que o backend
# local sempre recusa, viraria uma sequência de erros a cada acerto.
@receiver(user_login_failed)
def count_login_failure(sender, credentials, **kwargs):
    username = credentials.get('username')

    if username:
        throttle.login_failure(username)


@receiver(user_logged_in)
def clear_login_failures(sender, user, **kwargs):
    throttle.login_success(user.get_username())
