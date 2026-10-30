import pytest
from django.core.cache import cache
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


# O cache guarda o teto de tentativas de login e, em produção, as sessões. Os
# testes usam a memória do próprio processo: limpar entre um teste e outro não
# apaga a sessão de ninguém que esteja usando o sistema, e a suíte roda sem
# depender do Redis.
@pytest.fixture(autouse=True)
def isolated_cache(settings):
    settings.CACHES = {
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    }
    cache.clear()
    yield
    cache.clear()


# O storage de produção resolve cada arquivo pelo manifesto que o collectstatic
# escreve, e sem ele qualquer página com {% static %} quebra. Nos testes o
# arquivo é servido pelo nome mesmo: o que está sob teste é a view, não o hash.
@pytest.fixture(autouse=True)
def serving(settings):
    # Fora do DEBUG o SECURE_SSL_REDIRECT é sempre ligado, e aí todo GET do teste
    # viraria 301 antes de chegar na view.
    settings.SECURE_SSL_REDIRECT = False
    settings.STORAGES = {
        **settings.STORAGES,
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }


# Administrador só anda no portal com o segundo fator, então a sessão do teste
# nasce como a de quem entrou pela tela com o código na mão. Quem testa o
# próprio login ou o cadastro monta a sessão por conta, sem isto.
def sign_in(client, user):
    device = TOTPDevice.objects.create(user=user, name='default', confirmed=True)
    client.force_login(user)

    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()

    return device
