from django.core.exceptions import PermissionDenied

from .utils import throttle


class ThrottleBackend:
    """
    O teto de palpites por usuário, na frente de quem confere a senha.

    Não autentica ninguém: só interrompe a fila de backends quando o usuário já
    errou demais na janela. Fica aqui, e não na tela de login, porque toda porta
    que autentica passa por esta fila — inclusive a do portal de administração.

    O tamanho do teto e o porquê dele estão no app.utils.throttle; quem conta as
    tentativas é o app.signals, que escuta o resultado de todos os backends.

    Sem herdar do BaseBackend, como o backend do axes: o get_user que ele traz
    devolve None, e bastava esta classe aparecer primeiro na lista para uma
    sessão presa a ela nunca mais encontrar o usuário dela.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and throttle.login_blocked(username):
            # Como o backend do axes: interrompe antes de conferir a senha, e o
            # authenticate devolve None a quem chamou.
            raise PermissionDenied

        return None
