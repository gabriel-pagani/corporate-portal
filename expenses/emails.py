"""
O e-mail ao funcionário a cada mudança de situação da nota.

Só o funcionário recebe: quem confere e quem valida acompanham pela fila. O
envio acontece depois do commit, e a falha do servidor de e-mail não desfaz a
ação, só fica no log.
"""
import logging
import smtplib
from urllib.parse import urljoin

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from expenses.history import money
from expenses.models import Expense, ExpenseEvent


logger = logging.getLogger(__name__)

MESSAGES = {
    ExpenseEvent.SUBMIT: 'Recebemos a sua despesa. Ela agora aguarda a conferência.',
    ExpenseEvent.RESUBMIT: 'Recebemos as novas fotos da sua despesa. Ela volta para a conferência.',
    ExpenseEvent.REQUEST_CORRECTION: 'Foi pedida uma correção na sua despesa. Veja a observação abaixo e envie novas fotos pelo portal.',
    ExpenseEvent.APPROVE_REVIEW: 'A sua despesa foi conferida e agora aguarda a validação.',
    ExpenseEvent.EXPLAIN: 'A dúvida sobre a sua despesa foi esclarecida, e ela volta a aguardar a validação.',
    ExpenseEvent.REQUEST_EXPLANATION: 'Surgiu uma dúvida sobre a sua despesa na validação, e ela voltou para a conferência. Você não precisa fazer nada por enquanto.',
    ExpenseEvent.APPROVE_VALIDATION: 'A sua despesa foi aprovada.',
    ExpenseEvent.REJECT: 'A sua despesa foi rejeitada e está encerrada.',
}

# As observações que são para o funcionário. As trocadas entre a conferência e
# a validação ficam entre elas.
EMPLOYEE_NOTES = {
    ExpenseEvent.REQUEST_CORRECTION: 'Correção pedida',
    ExpenseEvent.REJECT: 'Motivo da rejeição',
}


def notify_status_change(expense, event, link=''):
    """Avisa o funcionário da nova situação. Devolve True se o e-mail saiu."""
    employee = expense.employee
    if not employee.email:
        logger.info('Despesa #%s: funcionário sem e-mail, aviso não enviado.', expense.pk)
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
        # O link chega como o endereço da lista; o e-mail aponta para a rota da despesa
        'link': urljoin(link, reverse('expenses:expense', args=[expense.pk])) if link else '',
    })
    try:
        send_mail(f'Despesa #{expense.pk}: {expense.get_status_display()}', body, None, [employee.email])
    except (smtplib.SMTPException, OSError) as error:
        logger.warning('Despesa #%s: e-mail ao funcionário não enviado (%s).', expense.pk, type(error).__name__)
        return False
    return True
