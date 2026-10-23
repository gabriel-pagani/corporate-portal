import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings


def send_toner_request(items: list) -> None:
    if not settings.TONER_REQUEST_WEBHOOK_URL or not settings.RM_USER or not settings.RM_PASSWORD:
        raise RuntimeError('Integração de solicitação de toners não configurada.')

    # O webhook do n8n autentica com o mesmo usuário do RM
    resp = requests.post(
        settings.TONER_REQUEST_WEBHOOK_URL,
        json={'items': items},
        auth=HTTPBasicAuth(settings.RM_USER, settings.RM_PASSWORD),
        headers={'Accept': 'application/json'},
        timeout=30,
    )
    resp.raise_for_status()
