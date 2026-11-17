"""
O e-mail ao funcionário a cada mudança de situação da nota.

Só o funcionário recebe: o Controle e o Financeiro acompanham pela fila. O
envio acontece depois do commit, e a falha do servidor de e-mail não desfaz a
ação, só fica no log.
"""
import logging
import smtplib

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from expenses.history import money
from expenses.models import Expense, ExpenseEvent


logger = logging.getLogger(__name__)

MESSAGES = {
    ExpenseEvent.SUBMIT: 'Recebemos a sua nota. Ela agora aguarda a conferência do Controle.',
    ExpenseEvent.RESUBMIT: 'Recebemos as novas fotos da sua nota. Ela volta para a conferência do Controle.',
    ExpenseEvent.REQUEST_CORRECTION: 'O Controle pediu uma correção na sua nota. Veja a observação abaixo e envie novas fotos pelo portal.',
    ExpenseEvent.APPROVE_REVIEW: 'A sua nota foi conferida pelo Controle e agora aguarda a validação do Financeiro.',
    ExpenseEvent.EXPLAIN: 'O Controle respondeu ao Financeiro sobre a sua nota, que volta a aguardar a validação.',
    ExpenseEvent.REQUEST_EXPLANATION: 'O Financeiro pediu uma explicação ao Controle sobre a sua nota. Você não precisa fazer nada por enquanto.',
    ExpenseEvent.APPROVE_VALIDATION: 'A sua nota foi aprovada.',
    ExpenseEvent.REJECT: 'A sua nota foi rejeitada e está encerrada.',
}

# As observações que são para o funcionário. As trocadas entre o Controle e o
# Financeiro ficam entre eles.
EMPLOYEE_NOTES = {
    ExpenseEvent.REQUEST_CORRECTION: 'Correção pedida',
    ExpenseEvent.REJECT: 'Motivo da rejeição',
}


def notify_status_change(expense, event, link=''):
    """Avisa o funcionário da nova situação. Devolve True se o e-mail saiu."""
    employee = expense.employee
    if not employee.email:
        logger.info('Nota #%s: funcionário sem e-mail, aviso não enviado.', expense.pk)
        return False

    note_label = EMPLOYEE_NOTES.get(event.action)
    body = render_to_string('expenses/emails/status_changed.txt', {
        'name': employee.get_full_name() or employee.username,
        'message': MESSAGES[event.action],
        'expense': expense,
        'created_at': timezone.localtime(expense.created_at).strftime('%d/%m/%Y %H:%M'),
        'total': money(expense.total),
        'reimbursed': money(expense.reimbursed_total) if expense.status == Expense.APPROVED else '',
        'note_label': note_label,
        'note': event.note if note_label else '',
        'link': link,
    })
    try:
        send_mail(f'Nota #{expense.pk}: {expense.get_status_display()}', body, None, [employee.email])
    except (smtplib.SMTPException, OSError) as error:
        logger.warning('Nota #%s: e-mail ao funcionário não enviado (%s).', expense.pk, type(error).__name__)
        return False
    return True
