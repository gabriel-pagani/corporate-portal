"""
O estado da nota em cada etapa.

Cada ExpenseEvent guarda em snapshot o estado completo da nota logo depois da
ação. A auditoria consulta esses registros no admin (Histórico das Notas) ou
direto no banco.
"""
from decimal import Decimal, InvalidOperation

from expenses.models import ExpenseItem, ExpensePhoto


def money(value):
    """O valor como R$ 1.234,56; vazio quando não há valor."""
    if value in (None, ''):
        return ''
    try:
        number = Decimal(str(value)).quantize(Decimal('0.01'))
    except InvalidOperation:
        return str(value)
    whole, cents = f'{number:,.2f}'.split('.')
    return f'R$ {whole.replace(",", ".")},{cents}'


def format_cnpj(value):
    if len(value or '') != 14:
        return value or ''
    return f'{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}'


def snapshot(expense):
    """O estado completo da nota agora, como fica gravado no registro do histórico."""
    items = ExpenseItem.objects.filter(expense=expense).order_by('position', 'id')
    photos = ExpensePhoto.objects.filter(expense=expense, replaced_at__isnull=True).order_by('position', 'id')
    employee = expense.employee
    return {
        'status': expense.status,
        'status_display': expense.get_status_display(),
        'employee': {
            'id': employee.pk,
            'username': employee.username,
            'name': employee.get_full_name() or employee.username,
        },
        'sector': str(expense.sector) if expense.sector_id else '',
        'cost_center': str(expense.cost_center) if expense.cost_center_id else '',
        'fields': {
            'cnpj': expense.cnpj,
            'access_key': expense.access_key,
            'number': expense.number,
            'issue_date': expense.issue_date.isoformat() if expense.issue_date else '',
            'total': '' if expense.total is None else str(expense.total),
            'expense_type': expense.expense_type.name if expense.expense_type_id else '',
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
            for item in items
        ],
        'reimbursed_total': str(expense.reimbursed_total),
        'employee_note': expense.employee_note,
        'last_note': expense.last_note,
        'photos': [
            {'id': photo.pk, 'round': photo.round, 'position': photo.position, 'sha256': photo.sha256}
            for photo in photos
        ],
        'ai_reading': expense.ai_reading,
        'ai_alerts': list(expense.ai_alerts or []),
        'version': expense.version,
    }
