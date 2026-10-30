from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from app.utils.otp import confirmed_device, requires_otp


class RequireOTPMiddleware:
    """
    Administrador sem código conferido não anda no portal, nem no painel.

    Quem ainda não cadastrou o aplicativo vai para o cadastro. Quem já cadastrou
    não tem como chegar aqui sem passar pelo código, a não ser numa sessão
    aberta antes disto existir, que não vale e é encerrada.
    """

    def __init__(self, get_response):
        self.get_response = get_response

        # A entrada e a saída ficam abertas, senão não há como entrar nem sair
        # da tela de cadastro.
        self.open_paths = {
            reverse('app:otp-setup'), reverse('app:login'), reverse('app:login-token'), reverse('app:logout'),
        }
        self.static_url = settings.STATIC_URL

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if (
            user is not None and user.is_authenticated and requires_otp(user)
            and not user.is_verified() and not self.is_open(request.path)
        ):
            if confirmed_device(user):
                logout(request)
                return redirect('app:login')
            return redirect('app:otp-setup')

        return self.get_response(request)

    def is_open(self, path):
        return path in self.open_paths or path.startswith(self.static_url)


class PermissionsPolicyMiddleware:
    FEATURES = {
        'accelerometer': '()',
        'autoplay': '()',
        'camera': '()',
        'display-capture': '()',
        'encrypted-media': '()',
        'fullscreen': '(self)',
        'geolocation': '()',
        'gyroscope': '()',
        'magnetometer': '()',
        'microphone': '()',
        'midi': '()',
        'payment': '()',
        'usb': '()',
        'xr-spatial-tracking': '()',
    }

    POLICY = ', '.join(f'{feature}={origins}' for feature, origins in FEATURES.items())

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Permissions-Policy', self.POLICY)
        return response
