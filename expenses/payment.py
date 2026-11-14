"""
O pagamento da despesa aprovada.

Hoje o financeiro paga por fora e marca a despesa como reembolsada. A
integração bancária entra aqui e só aqui: o pay() passa a mandar o pagamento
ao banco antes de mudar o status, e o resto do app continua chamando o pay().
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from expenses.models import Expense
from expenses.workflow import change_status


def pay(expense_id, user):
    with transaction.atomic():
        # A trava segura o segundo clique: a mesma despesa não é paga duas vezes
        expense = Expense.objects.select_for_update().get(pk=expense_id)
        if expense.status != Expense.APPROVED:
            raise ValidationError('Só a despesa aprovada pode ser marcada como reembolsada.')
        change_status(expense, Expense.REIMBURSED, user)
    return expense
