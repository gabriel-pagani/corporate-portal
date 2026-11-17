"""A nota como vai para a tela, conforme quem olha."""
from django.urls import reverse
from django.utils import timezone

from expenses.emails import EMPLOYEE_NOTES
from expenses.history import format_cnpj, money
from expenses.models import Expense, ExpenseEvent


# O que o funcionário vê de cada registro: as próprias observações e as que
# são para ele (correção e rejeição). O que o Controle e o Financeiro trocam
# entre si fica entre eles.
EMPLOYEE_VISIBLE_NOTES = {ExpenseEvent.SUBMIT, ExpenseEvent.RESUBMIT, *EMPLOYEE_NOTES}


def local(moment, pattern='%d/%m/%Y %H:%M'):
    return timezone.localtime(moment).strftime(pattern) if moment else ''


def photo_url(photo_id):
    return reverse('expenses:photo', args=[photo_id])


def employee_name(user):
    return user.get_full_name() or user.username


def serialize_summary(expense, current):
    data = {
        'id': expense.pk,
        'status': expense.status,
        'status_display': expense.get_status_display(),
        'created_at': local(expense.created_at),
        'number': expense.number,
        'issue_date': expense.issue_date.strftime('%d/%m/%Y') if expense.issue_date else '',
        'expense_type': expense.expense_type.name if expense.expense_type_id else '',
        'total': money(expense.total),
        'reimbursed_total': money(expense.reimbursed_total),
    }
    if current.reviewer:
        data['employee'] = employee_name(expense.employee)
        data['alerts_count'] = len(expense.ai_alerts or [])
    return data


def serialize_event_for_employee(event):
    return {
        'sequence': event.sequence,
        'action_display': event.get_action_display(),
        'status_display': event.get_status_after_display(),
        'role_display': event.get_author_role_display(),
        'note': event.note if event.action in EMPLOYEE_VISIBLE_NOTES else '',
        'created_at': local(event.created_at),
    }


def serialize_detail(expense, user, current):
    photos = [photo for photo in expense.photos.all() if photo.replaced_at is None]
    events = list(expense.events.all())
    reviewer = current.reviewer
    data = serialize_summary(expense, current)
    data.update({
        'version': expense.version,
        'employee_note': expense.employee_note,
        'fields': {
            'cnpj': expense.cnpj,
            'cnpj_display': format_cnpj(expense.cnpj),
            'access_key': expense.access_key,
            'number': expense.number,
            'issue_date': expense.issue_date.isoformat() if expense.issue_date else '',
            'total': '' if expense.total is None else str(expense.total),
            'expense_type_id': expense.expense_type_id,
        },
        'items': [
            {
                'id': item.pk,
                'description': item.description,
                'quantity': str(item.quantity),
                'amount': str(item.amount),
                'non_reimbursable': item.non_reimbursable,
                'ai_group': item.ai_group,
            }
            for item in expense.items.all()
        ],
        'reimbursed_total_value': str(expense.reimbursed_total),
        'photos': [{'id': photo.pk, 'url': photo_url(photo.pk)} for photo in photos],
        'can': {
            'edit': current.control and expense.status in Expense.WITH_CONTROL,
            'act': (
                (current.control and expense.status in Expense.WITH_CONTROL)
                or (current.finance and expense.status in Expense.WITH_FINANCE)
            ),
            'resubmit': current.employee and expense.employee_id == user.pk
            and expense.status == Expense.AWAITING_CORRECTION,
        },
        'explanation_required': expense.status == Expense.AWAITING_EXPLANATION,
    })

    if reviewer:
        reading = expense.ai_reading or {}
        data.update({
            'employee_username': expense.employee.username,
            'sector': str(expense.sector) if expense.sector_id else '',
            'cost_center': str(expense.cost_center) if expense.cost_center_id else '',
            'alerts': list(expense.ai_alerts or []),
            'ai_status': reading.get('status', ''),
            'last_note': expense.last_note,
            'timeline': [
                {
                    'sequence': event.sequence,
                    'action_display': event.get_action_display(),
                    'status_display': event.get_status_after_display(),
                    'author_name': event.author_name,
                    'role_display': event.get_author_role_display(),
                    'note': event.note,
                    'created_at': local(event.created_at),
                }
                for event in events
            ],
        })
    else:
        last = events[-1] if events else None
        # O motivo da rejeição e a correção pedida ficam à vista na nota
        data['last_note'] = (
            last.note if last and last.action in EMPLOYEE_NOTES and expense.status in (
                Expense.AWAITING_CORRECTION, Expense.REJECTED,
            ) else ''
        )
        data['timeline'] = [serialize_event_for_employee(event) for event in events]
    return data
