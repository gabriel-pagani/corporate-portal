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

Enquanto ninguém tratou a despesa, o funcionário pode excluí-la: sai tudo,
inclusive o registro do envio, sem aviso por e-mail.

Quando a IA não leu a nota no envio (fora do ar, ou sem configuração), a
conferência pede uma nova leitura, uma chamada por vez, até a leitura sair.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q
from django.utils import timezone

from expenses import emails, rm
from expenses.forms import MAX_ITEMS, ExpenseDataForm, ExpenseItemForm, first_error
from expenses.history import snapshot
from expenses.models import Expense, ExpenseEvent, ExpenseItem, ExpensePhoto
from expenses.photos import ai_copy, prepare_photos
from expenses.reading import OK as READ_OK, read_expense
from expenses.roles import access
from expenses.validators import clean_number


DUPLICATE_MESSAGE = 'Esta nota já foi enviada ao portal e não pode ser enviada de novo.'

NOT_A_DOCUMENT_MESSAGE = (
    'As fotos não parecem ser de uma nota fiscal ou de um recibo. Envie a foto do documento da despesa.'
)

REPEATED_PHOTO_MESSAGE = 'Esta foto já foi enviada e não pode ser enviada de novo.'

SAME_PHOTO_TWICE_MESSAGE = 'A mesma foto foi escolhida mais de uma vez. Envie fotos diferentes.'

RESUBMIT_REFUSED = 'Só é possível reenviar as fotos de uma despesa que aguarda correção.'

REREAD_DONE = 'A IA já leu esta nota.'

REREAD_NOT_WITH_CONTROL = 'Só dá para pedir a leitura enquanto a despesa está na conferência.'

REREAD_FAILED = 'A IA ainda não conseguiu ler a nota. Tente de novo mais tarde ou preencha a partir das fotos.'

# A nota já entrou: o que no envio seria recusado vira alerta para a conferência decidir
REREAD_DUPLICATE_ALERT = 'A nota lida pela IA já está em outra despesa do portal. Confira antes de aprovar.'

REREAD_NOT_A_DOCUMENT_ALERT = 'A IA diz que as fotos não são de uma nota fiscal nem de um recibo.'

REREAD_KEPT_ITEMS_ALERT = 'A IA leu os itens da nota, mas os itens já preenchidos foram mantidos.'

DISCARD_REFUSED = 'Esta despesa já foi tratada e não pode mais ser excluída.'

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


def refuse_repeated_photos(photos, expense=None):
    """
    Recusa a foto que já está no portal, pelo arquivo enviado ou pela imagem
    regravada, sem passar pela IA. No reenvio, as fotos da própria despesa
    podem voltar (a correção pode pedir só uma foto a mais).
    """
    sources = [photo.source_sha256 for photo in photos]
    images = [photo.sha256 for photo in photos]
    if len(set(sources)) < len(sources) or len(set(images)) < len(images):
        raise ValidationError(SAME_PHOTO_TWICE_MESSAGE)
    sent = ExpensePhoto.objects.filter(Q(source_sha256__in=sources) | Q(sha256__in=images))
    if expense is not None:
        sent = sent.exclude(expense=expense)
    if sent.exists():
        raise ValidationError(REPEATED_PHOTO_MESSAGE)


def same_number(number):
    """O número da nota para comparar: 000123 e 123 são a mesma nota."""
    return clean_number(number).lstrip('0') or '0'


def refuse_duplicate_note(fields, expense=None):
    """
    Recusa a nota que já está no portal: pela chave de acesso ou pelo mesmo
    CNPJ do emitente, número e data. Duas notas com chaves diferentes são notas
    diferentes (de outra série, por exemplo), então o CNPJ, o número e a data
    só contam quando falta a chave em uma delas, como quando a IA não a leu.
    Vale contra os dados atuais das outras despesas, já com o que a
    conferência corrigiu.
    """
    others = Expense.objects.all()
    if expense is not None:
        others = others.exclude(pk=expense.pk)
    access_key = fields.get('access_key')
    if access_key and others.filter(access_key=access_key).exists():
        raise ValidationError(DUPLICATE_MESSAGE)
    cnpj, number, issue_date = fields.get('cnpj'), fields.get('number'), fields.get('issue_date')
    if cnpj and number and issue_date:
        candidates = others.filter(cnpj=cnpj, issue_date=issue_date).values_list('number', 'access_key')
        for other_number, other_key in candidates:
            if other_number and same_number(other_number) == same_number(number) and not (access_key and other_key):
                raise ValidationError(DUPLICATE_MESSAGE)


def store_photos(expense, photos, round_number, saved):
    for position, photo in enumerate(photos):
        record = ExpensePhoto(
            expense=expense, sha256=photo.sha256, source_sha256=photo.source_sha256, round=round_number,
            position=position,
        )
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
    acontece antes da gravação, fora da transação. Antes dela é recusada a foto
    que já está no portal; depois, o envio que a IA diz não ser nota fiscal nem
    recibo, e a nota que já foi enviada (refuse_duplicate_note). Sem a análise
    (IA fora do ar ou não configurada), a nota entra e a conferência vê as fotos.
    """
    if not access(user).employee:
        raise PermissionDenied('Você não pode enviar notas.')
    note = clean_note(note)
    photos = prepare_photos(files)
    refuse_repeated_photos(photos)
    reading = read_expense([photo.ai_content for photo in photos], note)
    if reading.not_a_document:
        raise ValidationError(NOT_A_DOCUMENT_MESSAGE)

    refuse_duplicate_note(reading.fields)

    saved = []
    try:
        with transaction.atomic():
            # De novo, perto da gravação: outro envio da mesma foto ou nota pode ter entrado durante a análise
            refuse_repeated_photos(photos)
            refuse_duplicate_note(reading.fields)
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


def discard_expense(user, expense_id):
    """
    Exclui a despesa que o funcionário enviou e ninguém tratou ainda, com os
    itens, as fotos (os arquivos também) e o registro do envio. A conferência
    é feita de novo com a despesa travada: se alguém agiu nesse meio tempo, a
    exclusão é recusada.
    """
    if not access(user).employee:
        raise PermissionDenied('Você não pode enviar notas.')
    with transaction.atomic():
        expense = Expense.objects.select_for_update().get(pk=expense_id, employee=user)
        if not expense.untouched():
            raise ValidationError(DISCARD_REFUSED)
        photos = list(ExpensePhoto.objects.filter(expense=expense))
        files = [(photo.file.storage, photo.file.name) for photo in photos]
        # O banco só deixa apagar o registro do envio desta despesa, e só nesta transação
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('expenses.discarding_expense', %s, true)", [str(expense.pk)])
        ExpenseEvent.objects.filter(expense=expense).delete()
        ExpensePhoto.objects.filter(expense=expense).delete()
        expense.delete()
        # Os arquivos saem só depois que a exclusão está gravada
        transaction.on_commit(lambda: discard_files(files))


def check_rereadable(expense, version):
    if version != expense.version:
        raise Conflict(CONFLICT_MESSAGE)
    if expense.status not in Expense.WITH_CONTROL:
        raise ValidationError(REREAD_NOT_WITH_CONTROL)
    if (expense.ai_reading or {}).get('status') == READ_OK:
        raise ValidationError(REREAD_DONE)


def apply_reading(expense, reading):
    """
    Preenche a nota com a nova leitura, sem passar por cima do que a
    conferência já gravou: só os campos vazios, e os itens só se não houver
    nenhum. A chave de acesso de outra despesa não entra (é única no portal).
    """
    alerts = []
    fields = dict(reading.fields)
    key = fields.get('access_key')
    if key and Expense.objects.exclude(pk=expense.pk).filter(access_key=key).exists():
        fields['access_key'] = ''
        alerts.append(REREAD_DUPLICATE_ALERT)
    else:
        try:
            refuse_duplicate_note(fields, expense)
        except ValidationError:
            alerts.append(REREAD_DUPLICATE_ALERT)
    if reading.not_a_document:
        alerts.insert(0, REREAD_NOT_A_DOCUMENT_ALERT)

    for name, value in fields.items():
        if value not in (None, '') and getattr(expense, name) in (None, ''):
            setattr(expense, name, value)

    if not expense.items.exists():
        ExpenseItem.objects.bulk_create([
            ExpenseItem(expense=expense, position=position, **item)
            for position, item in enumerate(reading.items)
        ])
        recompute_totals(expense)
    elif reading.items:
        alerts.append(REREAD_KEPT_ITEMS_ALERT)
    expense.ai_alerts = alerts + list(reading.alerts)


def reread_expense(user, expense_id, version):
    """
    A conferência pede de novo a leitura da nota que a IA não leu. Uma chamada
    por pedido: se falhar, a tentativa fica registrada em ai_reading e o pedido
    pode ser feito de novo; deu certo, a leitura não se repete. Devolve True
    quando a nota foi lida.
    """
    if not access(user).control:
        raise PermissionDenied('Só a conferência pede a leitura da nota.')
    expense = Expense.objects.get(pk=expense_id)
    check_rereadable(expense, version)
    photos = expense.photos.filter(replaced_at__isnull=True).order_by('position', 'id')
    reading = read_expense([ai_copy(photo.file) for photo in photos], expense.employee_note)

    with transaction.atomic():
        expense = Expense.objects.select_for_update().get(pk=expense_id)
        check_rereadable(expense, version)
        previous = dict(expense.ai_reading or {})
        # As tentativas que falharam ficam no registro da leitura, para a auditoria
        attempts = previous.pop('failed_attempts', []) + [
            {key: previous.get(key, '') for key in ('status', 'model', 'read_at', 'error')}
        ]
        if reading.status != READ_OK:
            expense.ai_reading = {**previous, 'failed_attempts': attempts}
            expense.save(update_fields=['ai_reading', 'updated_at'])
            return False
        apply_reading(expense, reading)
        expense.ai_reading = {**reading.record, 'failed_attempts': attempts}
        expense.version += 1
        expense.save()
    return True


def resubmit_photos(user, expense_id, files, note='', link=''):
    """
    Troca as fotos da nota que aguarda correção e a devolve para a conferência.
    A IA olha as fotos novas só para recusar o que não é nota fiscal nem
    recibo, ou é uma nota de outra despesa: os dados da nota não mudam, e o que
    foi editado na conferência fica como está.
    """
    if not access(user).employee:
        raise PermissionDenied('Você não pode enviar notas.')
    note = clean_note(note)
    photos = prepare_photos(files)

    # Antes da IA, para não gastar a análise com um reenvio que seria recusado
    expense = Expense.objects.get(pk=expense_id, employee=user)
    if expense.status != Expense.AWAITING_CORRECTION:
        raise ValidationError(RESUBMIT_REFUSED)
    refuse_repeated_photos(photos, expense)
    reading = read_expense([photo.ai_content for photo in photos], note)
    if reading.not_a_document:
        raise ValidationError(NOT_A_DOCUMENT_MESSAGE)
    refuse_duplicate_note(reading.fields, expense)

    saved = []
    try:
        with transaction.atomic():
            expense = Expense.objects.select_for_update().get(pk=expense_id, employee=user)
            if expense.status != Expense.AWAITING_CORRECTION:
                raise ValidationError(RESUBMIT_REFUSED)
            refuse_repeated_photos(photos, expense)
            refuse_duplicate_note(reading.fields, expense)

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
