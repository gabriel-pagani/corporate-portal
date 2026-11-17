"""
O estado da nota em cada etapa, para o histórico e a auditoria.

Cada ExpenseEvent guarda em snapshot o estado completo da nota logo depois da
ação: com isso o histórico mostra a nota em qualquer momento (o último registro
até ali) e compara duas etapas quaisquer.
"""
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from expenses.models import ExpenseItem, ExpensePhoto


FIELDS = [
    ('cnpj', 'CNPJ do emitente'),
    ('access_key', 'Chave de acesso'),
    ('number', 'Número da nota'),
    ('issue_date', 'Data da nota'),
    ('total', 'Valor total'),
    ('expense_type', 'Tipo'),
]

ITEM_FIELDS = [
    ('description', 'Descrição'),
    ('quantity', 'Quantidade'),
    ('amount', 'Valor'),
    ('non_reimbursable', 'Não reembolsável'),
]

MONEY_FIELDS = {'total', 'amount', 'reimbursed_total'}


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


def quantity(value):
    if value in (None, ''):
        return ''
    number = Decimal(str(value)).normalize()
    # O normalize escreve 10 como 1E+1
    text = f'{number:f}'
    return text.replace('.', ',')


def format_date(value):
    if not value:
        return ''
    year, month, day = str(value).split('-')
    return f'{day}/{month}/{year}'


def format_cnpj(value):
    if len(value or '') != 14:
        return value or ''
    return f'{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}'


def display(name, value):
    """O valor do snapshot como aparece na tela."""
    if name in MONEY_FIELDS:
        return money(value)
    if name == 'quantity':
        return quantity(value)
    if name == 'issue_date':
        return format_date(value)
    if name == 'cnpj':
        return format_cnpj(value)
    if isinstance(value, bool):
        return 'Sim' if value else 'Não'
    return '' if value is None else str(value)


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


def change(label, name, before, after):
    return {'label': label, 'before': display(name, before), 'after': display(name, after)}


def compare(before, after):
    """O que mudou de um snapshot para outro: situação, campos, itens, totais, fotos e alertas."""
    fields = [
        change(label, name, before['fields'].get(name), after['fields'].get(name))
        for name, label in FIELDS
        if before['fields'].get(name) != after['fields'].get(name)
    ]

    old_items = {item['id']: item for item in before['items']}
    new_items = {item['id']: item for item in after['items']}
    changed_items = []
    for item_id in [item_id for item_id in new_items if item_id in old_items]:
        old, new = old_items[item_id], new_items[item_id]
        changes = [
            change(label, name, old.get(name), new.get(name))
            for name, label in ITEM_FIELDS if old.get(name) != new.get(name)
        ]
        if changes:
            changed_items.append({'description': new['description'], 'changes': changes})

    def item_summary(item):
        return {
            'description': item['description'],
            'quantity': display('quantity', item['quantity']),
            'amount': display('amount', item['amount']),
            'non_reimbursable': item['non_reimbursable'],
        }

    old_photos = {photo['id'] for photo in before['photos']}
    new_photos = {photo['id'] for photo in after['photos']}

    return {
        'status': (
            {'before': before['status_display'], 'after': after['status_display']}
            if before['status'] != after['status'] else None
        ),
        'fields': fields,
        'items': {
            'added': [item_summary(item) for item_id, item in new_items.items() if item_id not in old_items],
            'removed': [item_summary(item) for item_id, item in old_items.items() if item_id not in new_items],
            'changed': changed_items,
        },
        'reimbursed_total': (
            change('Valor reembolsado', 'reimbursed_total', before['reimbursed_total'], after['reimbursed_total'])
            if before['reimbursed_total'] != after['reimbursed_total'] else None
        ),
        'photos': (
            {
                'removed': sorted(old_photos - new_photos),
                'added': sorted(new_photos - old_photos),
            }
            if old_photos != new_photos else None
        ),
        'alerts': (
            {'before': before['ai_alerts'], 'after': after['ai_alerts']}
            if before['ai_alerts'] != after['ai_alerts'] else None
        ),
    }


def state_at(expense, moment):
    """O registro que vale para a nota no momento dado: o último até ali, ou None se ela ainda não existia."""
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return expense.events.filter(created_at__lte=moment).order_by('-sequence').first()
