import hmac
from functools import wraps
from django.conf import settings
from django.http import JsonResponse


def api_token_required(view_func):
    """Exige o header X-API-KEY com o valor de settings.API_TOKEN."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = settings.API_TOKEN

        if not expected:
            return JsonResponse(
                {'detail': 'API_TOKEN não configurado no servidor.'},
                status=503,
            )

        provided = request.headers.get('X-API-KEY', '')

        if not hmac.compare_digest(provided, expected):
            return JsonResponse({'detail': 'Token inválido ou ausente.'}, status=401)

        return view_func(request, *args, **kwargs)

    return wrapper
