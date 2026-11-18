"""
Quem faz o quê nas despesas.

Cada usuário tem um papel só: ou envia notas (Funcionário), ou confere
ou valida. Quem envia também não gerencia as regras
que a IA usa, para ninguém ajustar regra a favor da própria nota. Quem tiver uma
combinação proibida, por permissão direta ou de grupo, fica fora das telas até
o cadastro ser corrigido; o admin recusa salvar o usuário ou o grupo assim.

O superusuário é a exceção: confere, valida e gerencia
as regras, mas nunca envia nota.
"""
from dataclasses import dataclass

from django.contrib.auth.models import Permission

from expenses.models import ExpenseEvent


SUBMIT = 'submit_expense'
REVIEW = 'review_expense'
VALIDATE = 'validate_expense'
MANAGE = 'manage_expense_rules'

ROLE_PERMISSIONS = {
    SUBMIT: ExpenseEvent.EMPLOYEE,
    REVIEW: ExpenseEvent.CONTROL,
    VALIDATE: ExpenseEvent.FINANCE,
}

ROLE_CONFLICT = (
    'Cada usuário pode ter um só papel nas despesas: enviar notas, conferir ou validar.'
)

SUBMIT_MANAGE_CONFLICT = 'Quem envia notas de despesa não pode gerenciar as regras das despesas.'


@dataclass(frozen=True)
class Access:
    employee: bool = False
    control: bool = False
    finance: bool = False
    manage: bool = False
    # Tem permissões que não podem andar juntas: não entra no fluxo
    conflict: bool = False

    @property
    def reviewer(self):
        return self.control or self.finance

    @property
    def any_role(self):
        return self.employee or self.control or self.finance


def conflict_message(codenames, is_superuser=False):
    """O motivo de a combinação de permissões ser proibida, ou None se ela vale."""
    if is_superuser:
        return None
    if len(set(codenames) & set(ROLE_PERMISSIONS)) > 1:
        return ROLE_CONFLICT
    if SUBMIT in codenames and MANAGE in codenames:
        return SUBMIT_MANAGE_CONFLICT
    return None


def user_codenames(user):
    """As permissões das despesas que o usuário tem, diretas ou de grupo."""
    return {
        name.split('.', 1)[1] for name in user.get_all_permissions() if name.startswith('expenses.')
    }


def access(user):
    if not user.is_authenticated or not user.is_active:
        return Access()
    if user.is_superuser:
        return Access(control=True, finance=True, manage=True)

    codenames = user_codenames(user)
    if conflict_message(codenames):
        return Access(conflict=True)
    return Access(
        employee=SUBMIT in codenames,
        control=REVIEW in codenames,
        finance=VALIDATE in codenames,
        manage=MANAGE in codenames,
    )


def has_any_expense_permission(user):
    """Quem vê o serviço na home: os três papéis, o superusuário e quem está em conflito (para saber disso)."""
    current = access(user)
    return current.any_role or current.conflict


def expense_codenames(permissions=(), groups=()):
    """
    Os codenames das despesas numa lista de permissões somada às dos grupos:
    o que o usuário teria com o formulário do admin como está.
    """
    query = Permission.objects.filter(content_type__app_label='expenses')
    direct = query.filter(pk__in=[permission.pk for permission in permissions])
    from_groups = query.filter(group__in=[group.pk for group in groups])
    return set(direct.values_list('codename', flat=True)) | set(from_groups.values_list('codename', flat=True))
