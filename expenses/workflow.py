"""
O fluxo da nota, etapa a etapa:

    envio (com a análise da IA) -> Aguardando conferência
    Conferência: pedir correção -> Aguardando correção (funcionário)
                rejeitar       -> Rejeitada
                aprovar        -> Aguardando validação
    funcionário reenvia as fotos -> Aguardando conferência
    Validação:  pedir correção -> Aguardando explicação (volta à conferência)
                rejeitar       -> Rejeitada
                aprovar        -> Aprovada, e o lançamento no RM

Cada etapa grava um ExpenseEvent com o estado completo da nota, avisa o
funcionário por e-mail e sobe a versão da nota: a ação feita sobre uma versão
que já mudou é recusada.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from expenses import emails, rm
from expenses.forms import MAX_ITEMS, ExpenseDataForm, ExpenseItemForm, first_error
from expenses.history import snapshot
from expenses.models import Expense, ExpenseEvent, ExpenseItem, ExpensePhoto
from expenses.photos import prepare_photos
from expenses.reading import read_expense
from expenses.roles import access


DUPLICATE_MESSAGE = 'Esta nota já foi enviada ao portal e não pode ser enviada de novo.'

CONFLICT_MESSAGE = 'A despesa foi alterada por outra pessoa desde que você a abriu. Abra-a de novo para ver a versão atual.'

MAX_NOTE = 2000

REQUEST_CORRECTION = 'request_correction'
REJECT = 'reject'
APPROVE = 'approve'
ACTIONS = (REQUEST_CORRECTION, REJECT, APPROVE)

TRANSITIONS = {
    (ExpenseEvent.CONTROL, REQUEST_CORRECTION): (Expense.AWAITING_CORRECTION, ExpenseEvent.REQUEST_CORRECTION),
    (ExpenseEvent.CONTROL, REJECT): (Expense.REJECTED, ExpenseEvent.REJECT),
    (ExpenseEvent.CONTROL, APPROVE): (Expense.AWAITING_VALIDATION, ExpenseEvent.APPROVE_REVIEW),
    (ExpenseEvent.FINANCE, REQUEST_CORRECTION): (Expense.AWAITING_EXPLANATION, ExpenseEvent.REQUEST_EXPLANATION),
    (ExpenseEvent.FINANCE, REJECT): (Expense.REJECTED, ExpenseEvent.REJECT),
    (ExpenseEvent.FINANCE, APPROVE): (Expense.APPROVED, ExpenseEvent.APPROVE_VALIDATION),
}

# Sem estes campos a nota não é aprovada
REQUIRED_TO_APPROVE = [
    ('number', 'número da nota'),
    ('issue_date', 'data'),
    ('total', 'valor total'),
    ('cnpj', 'CNPJ do emitente'),
    ('expense_type', 'tipo'),
]


class Conflict(Exception):
    """A nota mudou desde que a pessoa a abriu."""


def visible_expenses(user):
    """O funcionário vê só as dele; quem confere e quem valida veem todas."""
    current = access(user)
    expenses = Expense.objects.select_related('employee', 'expense_type', 'sector', 'cost_center')
    if current.reviewer:
        return expenses
    if current.employee:
        return expenses.filter(employee=user)
    return expenses.none()


def clean_note(note):
    note = str(note or '').strip()
    if len(note) > MAX_NOTE:
        raise ValidationError(f'A observação pode ter até {MAX_NOTE} caracteres.')
    return note


def recompute_totals(expense):
    amounts = ExpenseItem.objects.filter(expense=expense, non_reimbursable=False).values_list('amount', flat=True)
    expense.reimbursed_total = sum(amounts, Decimal('0.00'))


def record_event(expense, action, user, role, status_before, note):
    last = expense.events.aggregate(last=Max('sequence'))['last'] or 0
    return ExpenseEvent.objects.create(
        expense=expense,
        sequence=last + 1,
        action=action,
        status_before=status_before,
        status_after=expense.status,
        author=user,
        author_name=user.get_full_name() or user.username,
        author_role=role,
        note=note,
        snapshot=snapshot(expense),
    )


def after_commit(expense, event, link):
    transaction.on_commit(lambda: emails.notify_status_change(expense, event, link))


def store_photos(expense, photos, round_number, saved):
    for position, photo in enumerate(photos):
        record = ExpensePhoto(expense=expense, sha256=photo.sha256, round=round_number, position=position)
        record.file.save('foto.jpg', ContentFile(photo.content), save=False)
        saved.append((record.file.storage, record.file.name))
        record.save()


def discard_files(saved):
    # A transação voltou atrás: os arquivos gravados não pertencem a nota nenhuma
    for storage, name in saved:
        storage.delete(name)


def submit_expense(user, files, note='', link=''):
    """
    Cria a nota com as fotos, a observação e a análise da IA. A chamada à IA
    acontece antes da gravação, fora da transação; a nota com chave de acesso
    já enviada é recusada.
    """
    if not access(user).employee:
        raise PermissionDenied('Você não pode enviar notas.')
    note = clean_note(note)
    photos = prepare_photos(files)
    reading = read_expense([photo.ai_content for photo in photos], note)

    access_key = reading.fields.get('access_key', '')
    if access_key and Expense.objects.filter(access_key=access_key).exists():
        raise ValidationError(DUPLICATE_MESSAGE)

    saved = []
    try:
        with transaction.atomic():
            expense = Expense.objects.create(
                employee=user,
                sector_id=user.sector_id,
                cost_center_id=user.cost_center_id,
                employee_note=note,
                ai_reading=reading.record,
                ai_alerts=reading.alerts,
                **reading.fields,
            )
            ExpenseItem.objects.bulk_create([
                ExpenseItem(expense=expense, position=position, **item)
                for position, item in enumerate(reading.items)
            ])
            recompute_totals(expense)
            expense.save(update_fields=['reimbursed_total'])
            store_photos(expense, photos, 1, saved)
            event = record_event(expense, ExpenseEvent.SUBMIT, user, ExpenseEvent.EMPLOYEE, '', note)
            after_commit(expense, event, link)
    except IntegrityError as error:
        discard_files(saved)
        # Outro envio da mesma nota entrou entre a conferência e a gravação
        if 'unique_expense_access_key' in str(error):
            raise ValidationError(DUPLICATE_MESSAGE) from error
        raise
    except BaseException:
        discard_files(saved)
        raise
    return expense


def resubmit_photos(user, expense_id, files, note='', link=''):
    """
    Troca as fotos da nota que aguarda correção e a devolve para a conferência.
    A IA não analisa de novo, e o que foi editado na conferência fica como está.
    """
    if not access(user).employee:
        raise PermissionDenied('Você não pode enviar notas.')
    note = clean_note(note)
    photos = prepare_photos(files)

    saved = []
    try:
        with transaction.atomic():
            expense = Expense.objects.select_for_update().get(pk=expense_id, employee=user)
            if expense.status != Expense.AWAITING_CORRECTION:
                raise ValidationError('Só é possível reenviar as fotos de uma despesa que aguarda correção.')

            round_number = (expense.photos.aggregate(last=Max('round'))['last'] or 0) + 1
            expense.photos.filter(replaced_at__isnull=True).update(replaced_at=timezone.now())
            store_photos(expense, photos, round_number, saved)

            status_before = expense.status
            expense.status = Expense.AWAITING_REVIEW
            expense.last_note = note
            expense.version += 1
            expense.save(update_fields=['status', 'last_note', 'version', 'updated_at'])
            event = record_event(expense, ExpenseEvent.RESUBMIT, user, ExpenseEvent.EMPLOYEE, status_before, note)
            after_commit(expense, event, link)
    except BaseException:
        discard_files(saved)
        raise
    return expense


def apply_edits(expense, data):
    """Grava os campos e os itens editados na conferência. Levanta ValidationError com os erros por campo."""
    if not isinstance(data, dict):
        raise ValidationError('Envie os dados da nota.')

    errors = {}
    form = ExpenseDataForm(data, expense=expense)
    if not form.is_valid():
        errors.update({field: list(messages) for field, messages in form.errors.items()})

    items = data.get('items', [])
    if not isinstance(items, list):
        items = None
        errors['items'] = ['Envie os itens como uma lista.']
    elif len(items) > MAX_ITEMS:
        errors['items'] = [f'A nota pode ter até {MAX_ITEMS} itens.']
    item_forms = [ExpenseItemForm(item if isinstance(item, dict) else {}) for item in items or []]
    for index, item_form in enumerate(item_forms, start=1):
        if not item_form.is_valid():
            errors.setdefault('items', []).append(f'Item {index}: {first_error(item_form)}')
    if errors:
        raise ValidationError(errors)

    cleaned = form.cleaned_data
    expense.cnpj = cleaned['cnpj']
    expense.access_key = cleaned['access_key']
    expense.number = cleaned['number']
    expense.issue_date = cleaned['issue_date']
    expense.total = cleaned['total']
    expense.expense_type = cleaned['expense_type']

    existing = {item.pk: item for item in expense.items.all()}
    kept = set()
    for position, item_form in enumerate(item_forms):
        values = item_form.cleaned_data
        # Um id de fora desta nota, ou repetido, vira um item novo
        item = existing.get(values['id']) if values['id'] not in kept else None
        if item is None:
            item = ExpenseItem(expense=expense)
        item.position = position
        item.description = ' '.join(values['description'].split())
        item.quantity = values['quantity']
        item.amount = values['amount']
        item.non_reimbursable = values['non_reimbursable']
        item.save()
        kept.add(item.pk)
    expense.items.exclude(pk__in=kept).delete()
    recompute_totals(expense)


def check_ready_to_approve(expense):
    missing = [
        label for field, label in REQUIRED_TO_APPROVE
        if getattr(expense, field) in (None, '')
    ]
    if missing:
        raise ValidationError(f'Para aprovar, preencha: {", ".join(missing)}.')
    if expense.reimbursed_total <= 0:
        raise ValidationError('Para aprovar, a despesa precisa ter valor reembolsado maior que zero.')


def acting_role(expense, current):
    """O papel de quem age, pela etapa em que a nota está."""
    if expense.status in Expense.WITH_CONTROL:
        if not current.control:
            raise PermissionDenied('Esta despesa está na conferência.')
        return ExpenseEvent.CONTROL
    if expense.status in Expense.WITH_FINANCE:
        if not current.finance:
            raise PermissionDenied('Esta despesa está na validação.')
        return ExpenseEvent.FINANCE
    if expense.status == Expense.AWAITING_CORRECTION:
        raise ValidationError('Esta despesa aguarda a correção do funcionário.')
    raise ValidationError('Esta despesa já está encerrada.')


def note_required(role, action, status):
    if action in (REQUEST_CORRECTION, REJECT):
        return True
    # A explicação pedida na validação vai na observação da aprovação
    return role == ExpenseEvent.CONTROL and status == Expense.AWAITING_EXPLANATION


def act(user, expense_id, action, note='', version=None, data=None, link=''):
    """
    Pedir correção, rejeitar ou aprovar, na conferência ou na validação,
    conforme a etapa. Quem confere manda junto os dados que editou; quem valida
    só vê, e o que ele mandar de dados é ignorado.
    """
    if action not in ACTIONS:
        raise ValidationError('Ação desconhecida.')
    current = access(user)
    if not current.reviewer:
        raise PermissionDenied('Você não pode conferir nem validar notas.')
    note = clean_note(note)

    with transaction.atomic():
        expense = Expense.objects.select_for_update().get(pk=expense_id)
        role = acting_role(expense, current)
        if version != expense.version:
            raise Conflict(CONFLICT_MESSAGE)

        if role == ExpenseEvent.CONTROL and data is not None:
            apply_edits(expense, data)
        if note_required(role, action, expense.status) and not note:
            if action == APPROVE:
                raise ValidationError('Escreva na observação a explicação pedida na validação.')
            raise ValidationError('Escreva a observação: ela é obrigatória para esta ação.')
        if action == APPROVE:
            check_ready_to_approve(expense)

        status_before = expense.status
        expense.status, event_action = TRANSITIONS[(role, action)]
        if event_action == ExpenseEvent.APPROVE_REVIEW and status_before == Expense.AWAITING_EXPLANATION:
            event_action = ExpenseEvent.EXPLAIN
        expense.last_note = note
        expense.version += 1
        expense.save()
        event = record_event(expense, event_action, user, role, status_before, note)
        after_commit(expense, event, link)
        if expense.status == Expense.APPROVED:
            transaction.on_commit(lambda: rm.launch_in_rm(expense))
    return expense
