import pytest


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
