import pytest
from django.core.cache import cache


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
