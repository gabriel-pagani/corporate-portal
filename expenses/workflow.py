"""
As regras do reembolso: o que entra no valor, os avisos do aprovador, a nota
repetida e as mudanças de status.

Os totais e os avisos saem sempre daqui, a partir do que está no banco. O que o
navegador manda são só os itens e o cabeçalho da nota.
"""
import hashlib
import unicodedata
from collections import Counter
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.urls import reverse
from django.utils import timezone

from app.utils.notifications.delivery import author_name
from expenses.models import Expense, ExpenseEvent, ExpenseItem, ExpensePhoto, IgnoredWord
from expenses.receipts import (
    MAX_PHOTO_SIZE, MAX_PHOTOS, NotAReceipt, ReadingFailed, classify_descriptions, read_receipt, reduce_photo,
    valid_access_key, valid_cnpj,
)


NOT_A_RECEIPT_ERROR = 'Não é uma nota fiscal. Envie a foto da nota ou do cupom fiscal.'

DUPLICATE_ERROR = 'Esta nota já foi enviada para reembolso.'

UNEVALUATED_REASON = 'Os itens digitados pelo funcionário não passaram pela avaliação de itens não reembolsáveis.'

# A despesa descartada ou recusada não segura a nota: ela pode ser enviada de novo
NOT_COUNTED_AS_SENT = (Expense.DRAFT, Expense.REJECTED)

# Depois de decidida (aprovada ou rejeitada), a despesa fica no histórico
DELETABLE = (Expense.DRAFT, Expense.SENT, Expense.CORRECTION)

REVIEW_PERMISSIONS = ('expenses.approve_expense', 'expenses.reimburse_expense')

# O que o aprovador decide, e o status em que a despesa fica
REVIEW_ACTIONS = {
    'approve': Expense.APPROVED,
    'reject': Expense.REJECTED,
    'correction': Expense.CORRECTION,
}

# As que ainda esperam alguém: vão inteiras para a página. As encerradas
# crescem sem parar e são buscadas no banco, uma página por vez.
PENDING = (Expense.SENT, Expense.CORRECTION, Expense.APPROVED)
CLOSED = (Expense.REJECTED, Expense.REIMBURSED)
CLOSED_PAGE = 20
# O valor do filtro de centro de custo para a despesa sem centro
WITHOUT_COST_CENTER = 'sem'


# Quem tem qualquer uma destas não lança despesa: separação de funções, para
# ninguém aprovar ou pagar o próprio pedido, mexer nos tipos não reembolsáveis
# a seu favor, nem trocar favores com o colega
MANAGE_PERMISSIONS = (*REVIEW_PERMISSIONS, 'expenses.manage_expense_settings')


def can_submit(user):
    return not any(user.has_perm(perm) for perm in MANAGE_PERMISSIONS)


def can_review(user):
    return any(user.has_perm(perm) for perm in REVIEW_PERMISSIONS)


def brl(value):
    return 'R$ ' + f'{Decimal(value):,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')


def plain(text):
    """O texto sem acento e em minúscula, como o unaccent do banco."""
    return ''.join(char for char in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(char))


def ignored_words():
    """Os tipos não reembolsáveis, lidos uma vez por operação e conferidos item a item em memória."""
    return list(IgnoredWord.objects.values_list('word', flat=True))


def ignored_words_in(description, words):
    """
    Os tipos não reembolsáveis escritos na descrição, sem diferenciar acento nem
    maiúscula. É o piso da avaliação: o que o modelo deixar passar e estiver
    escrito com todas as letras ainda fica fora do reembolso.
    """
    text = plain(description)
    return [word for word in words if plain(word) in text]


def update_totals(expense):
    totals = expense.items.aggregate(total=Sum('amount'), reimbursable=Sum('amount', filter=Q(ignored=False)))
    expense.total = totals['total'] or Decimal(0)
    expense.reimbursable_total = totals['reimbursable'] or Decimal(0)


def verification_reasons(expense, words):
    """
    Os motivos da verificação obrigatória. Só o aprovador os vê.

    A regra é: qualquer dúvida aciona a verificação. Saem da leitura da foto (o
    que a IA não leu com segurança ou achou estranho) e, principalmente, da
    comparação do que o funcionário enviou com o que está na foto, feita aqui e
    não pela IA: o que vem dela pode ter sido manipulado por texto na imagem.
    """
    reading = expense.ai_reading
    if reading is None:
        # Sem leitura não há com o que comparar o que o funcionário digitou
        return ['A leitura automática da nota falhou: os valores foram digitados pelo funcionário.']

    reasons = []
    # As leituras gravadas antes destes campos contam como dúvida, e não como nota limpa
    if reading.get('instructions_in_image', True):
        reasons.append('A foto tem texto tentando orientar a leitura automática: possível tentativa de fraude.')
    if reading.get('doubts'):
        doubts = '; '.join(doubt.rstrip('.') for doubt in reading['doubts'])
        reasons.append(f'A leitura automática ficou em dúvida: {doubts}.')
    reasons += header_differences(expense, reading)
    reasons += item_differences(expense, reading)
    if previously_rejected(expense):
        reasons.append('Esta nota já foi enviada antes e rejeitada.')

    words = sorted({
        word for item in reading['items']
        for word in [*ignored_words_in(item['description'], words), *filter(None, [item.get('ignored_word')])]
    })
    if words:
        reasons.append(f'A leitura original tem item não reembolsável: {", ".join(words)}.')
    if not all(item['legible'] for item in reading['items']):
        reasons.append('A leitura original tem item rasurado ou ilegível.')
    if reading['total'] is None or not reading.get('total_legible', False):
        reasons.append('O valor total não está claro na foto.')
    if reading['total'] is not None:
        total = Decimal(reading['total'])
        if expense.total != total:
            reasons.append(f'O total enviado ({brl(expense.total)}) é diferente do total da nota ({brl(total)}).')
        read_sum = sum((Decimal(item['amount']) for item in reading['items']), Decimal(0))
        if read_sum != total:
            reasons.append(f'Os itens lidos na foto somam {brl(read_sum)}, e o total da nota é {brl(total)}.')
    return reasons


def header_differences(expense, reading):
    """CNPJ e data enviados que não batem com a foto, ou que a leitura não achou."""
    reasons = []
    if reading['cnpj'] and not valid_cnpj(reading['cnpj']):
        reasons.append(f'O CNPJ da nota ({reading["cnpj"]}) não é válido: a nota pode ser falsa.')
    read_date = date.fromisoformat(reading['date']) if reading['date'] else None
    if reading.get('access_key') and not valid_access_key(reading['access_key'], reading['cnpj'], read_date):
        reasons.append(
            'A chave de acesso não confere com o CNPJ, a data ou o dígito verificador: a nota pode ser falsa.'
        )
    if not reading['cnpj']:
        reasons.append('A leitura não encontrou o CNPJ do emitente.')
    elif expense.cnpj != reading['cnpj']:
        reasons.append(f'O CNPJ enviado ({expense.cnpj or "nenhum"}) é diferente do lido na nota ({reading["cnpj"]}).')
    if not reading['date']:
        reasons.append('A leitura não encontrou a data da nota.')
    elif expense.issue_date is None or expense.issue_date.isoformat() != reading['date']:
        sent = expense.issue_date.strftime('%d/%m/%Y') if expense.issue_date else 'nenhuma'
        read = date.fromisoformat(reading['date']).strftime('%d/%m/%Y')
        reasons.append(f'A data enviada ({sent}) é diferente da lida na nota ({read}).')
    return reasons


def item_differences(expense, reading):
    """
    Os itens enviados que não estão na foto e os da foto que não foram enviados,
    pela descrição e pelo valor: trocar um produto por outro de mesmo preço, ou
    mexer nos valores mantendo o total, também aparece.
    """
    def key(description, amount):
        return plain(' '.join(description.split())), Decimal(amount)

    read = Counter(key(item['description'] or 'Item ilegível', item['amount']) for item in reading['items'])
    sent = Counter(key(*item) for item in expense.items.values_list('description', 'amount'))
    added, removed = sum((sent - read).values()), sum((read - sent).values())
    if not added and not removed:
        return []
    return [
        f'Os itens enviados são diferentes dos lidos na foto: {added} incluído(s) ou alterado(s), '
        f'{removed} retirado(s) ou alterado(s).'
    ]


def same_receipt(cnpj, issue_date, total, access_key=''):
    """
    As despesas da mesma nota. A chave de acesso é única por nota fiscal e não
    depende de a IA ler os outros três campos; o trio CNPJ + data + total cobre
    o cupom sem chave. Vale o que foi enviado e o que a IA leu na foto: editar o
    cabeçalho não faz a mesma nota passar duas vezes.
    """
    same = Q(pk__in=[])
    if access_key:
        same |= Q(ai_reading__access_key=access_key)
    if cnpj and issue_date is not None and total:
        same |= Q(cnpj=cnpj, issue_date=issue_date, total=total)
        same |= Q(ai_reading__cnpj=cnpj, ai_reading__date=issue_date.isoformat(), ai_reading__total=f'{total:.2f}')
    return Expense.objects.filter(same)


def previously_rejected(expense):
    reading = expense.ai_reading or {}
    return (
        same_receipt(expense.cnpj, expense.issue_date, expense.total, reading.get('access_key', ''))
        .filter(status=Expense.REJECTED).exclude(pk=expense.pk).exists()
    )


def find_duplicate(cnpj, issue_date, total, access_key='', exclude=None):
    """Outra despesa da mesma nota que ainda conta como enviada."""
    # ponytail: conferência sem trava; dois envios da mesma nota no mesmo instante
    # passam os dois e caem na fila do aprovador. Índice único parcial se isso aparecer.
    return (
        same_receipt(cnpj, issue_date, total, access_key)
        .exclude(status__in=NOT_COUNTED_AS_SENT)
        .exclude(pk=exclude.pk if exclude else None)
        .first()
    )


def find_duplicate_photo(hashes, exclude=None):
    return (
        ExpensePhoto.objects.filter(sha256__in=hashes)
        .exclude(expense__status__in=NOT_COUNTED_AS_SENT)
        .exclude(expense=exclude)
        .first()
    )


def change_status(expense, status, user, note=''):
    """Muda o status e registra no histórico quem mudou e por quê."""
    expense.status = status
    expense.save()
    ExpenseEvent.objects.create(expense=expense, status=status, user=user, note=note)


def read_photos(user, files, expense=None):
    """
    Lê as fotos do recibo e abre o rascunho da despesa, já com os itens lidos.

    Com uma despesa em correção, troca as fotos dela. Devolve a despesa e se a
    leitura saiu; quando não sai, o funcionário preenche à mão. Levanta
    ValidationError para foto inválida, nota repetida e imagem que não é nota
    fiscal, sem salvar nada.
    """
    if not 1 <= len(files) <= MAX_PHOTOS:
        raise ValidationError(f'Envie de 1 a {MAX_PHOTOS} fotos do recibo.')

    originals, photos = [], []
    for number, file in enumerate(files, start=1):
        if file.size > MAX_PHOTO_SIZE:
            raise ValidationError(f'A foto {number} passa de {MAX_PHOTO_SIZE // 1024 // 1024} MB.')
        originals.append(hashlib.sha256(file.read()).hexdigest())
        file.seek(0)
        try:
            photos.append(reduce_photo(file))
        except ValueError:
            raise ValidationError(f'A foto {number} não é uma imagem válida. Envie em JPG ou PNG.')

    if find_duplicate_photo(originals, exclude=expense):
        raise ValidationError(DUPLICATE_ERROR)

    # Fora de transação: a leitura leva segundos, e não segura nada no banco
    try:
        words = ignored_words()
        reading = read_receipt(photos, words)
    except NotAReceipt:
        raise ValidationError(NOT_A_RECEIPT_ERROR)
    except ReadingFailed:
        reading = None

    if reading:
        issue_date = date.fromisoformat(reading['date']) if reading['date'] else None
        total = Decimal(reading['total']) if reading['total'] else None
        if find_duplicate(reading['cnpj'], issue_date, total, reading['access_key'], exclude=expense):
            raise ValidationError(DUPLICATE_ERROR)

    with transaction.atomic():
        if expense is None:
            # Um rascunho por funcionário: o que ficou para trás é de uma nota que ele desistiu de enviar
            Expense.objects.filter(user=user, status=Expense.DRAFT).delete()
            expense = Expense(user=user)
        else:
            expense.photos.all().delete()

        expense.ai_reading = reading
        # Sem leitura das fotos novas fica o que o funcionário já tinha preenchido
        if reading:
            expense.merchant = reading['merchant']
            expense.cnpj = reading['cnpj']
            expense.issue_date = issue_date
        expense.save()

        for original, photo in zip(originals, photos):
            ExpensePhoto(expense=expense, sha256=original).file.save('foto.jpg', ContentFile(photo))

        if reading:
            expense.items.all().delete()
            ExpenseItem.objects.bulk_create(
                ExpenseItem(
                    expense=expense,
                    description=item['description'] or 'Item ilegível',
                    quantity=item['quantity'],
                    amount=item['amount'],
                    unreadable=not item['legible'],
                    ignored=(
                        not item['legible'] or bool(item['ignored_word'])
                        or bool(ignored_words_in(item['description'], words))
                    ),
                )
                for item in reading['items']
            )
        update_totals(expense)
        expense.save()

    return expense, reading is not None


def flagged_descriptions(expense_id, items):
    """
    As descrições que o funcionário digitou (item novo ou alterado) e que o
    modelo encaixou num tipo não reembolsável: "cervejinha" e "skol lata" caem
    em "bebida alcoólica". Devolve também se a avaliação saiu; quando não sai, a despesa
    segue só com a comparação por escrito e o aprovador é avisado.
    """
    current = dict(ExpenseItem.objects.filter(expense_id=expense_id).values_list('id', 'description'))
    words = ignored_words()
    typed = sorted({
        item['description'] for item in items
        if current.get(item['id']) != item['description'] and not ignored_words_in(item['description'], words)
    })
    if not typed or not words:
        return set(), True
    try:
        found = classify_descriptions(typed, words)
    except ReadingFailed:
        return set(), False
    return {description for description, word in zip(typed, found) if word}, True


def apply_items(expense, items, words, by_approver=False, flagged=()):
    """
    Deixa os itens da despesa como vieram: altera os que já existem, cria os
    novos e apaga os que não vieram.

    Do funcionário, o item novo ou com a descrição alterada é avaliado de novo
    pelos tipos não reembolsáveis (`flagged` traz os que o modelo pegou), e o
    ilegível continua fora do reembolso. Do aprovador vale o que ele marcou:
    a última palavra sobre cada item é dele.
    """
    existing = {item.id: item for item in expense.items.all()}
    kept, new = {}, []
    for data in items:
        item = existing.get(data['id'])
        if item is None or item.id in kept:
            item = ExpenseItem(expense=expense)
            new.append(item)
        else:
            kept[item.id] = item
        changed = item.description != data['description']
        item.description = data['description']
        item.quantity = data['quantity']
        item.amount = data['amount']
        if by_approver:
            item.ignored = data['ignored']
        elif changed:
            item.ignored = (
                item.unreadable or item.description in flagged or bool(ignored_words_in(item.description, words))
            )

    # Em lote: a despesa fica travada enquanto isto roda, e uma consulta por item a seguraria mais
    expense.items.exclude(id__in=kept).delete()
    ExpenseItem.objects.bulk_update(kept.values(), ['description', 'quantity', 'amount', 'ignored'])
    ExpenseItem.objects.bulk_create(new)
    update_totals(expense)


def submit_expense(expense_id, user, header, items):
    """O funcionário envia o rascunho, ou devolve a despesa corrigida, para a fila do aprovador."""
    # Fora da transação: a avaliação leva segundos, e não segura a despesa no banco
    flagged, evaluated = flagged_descriptions(expense_id, items)
    with transaction.atomic():
        expense = Expense.objects.select_for_update().filter(
            pk=expense_id, user=user, status__in=Expense.EDITABLE,
        ).first()
        if expense is None:
            raise ValidationError('Esta despesa não pode mais ser alterada.')

        expense.merchant = header['merchant']
        expense.cnpj = header['cnpj']
        expense.issue_date = header['issue_date']
        words = ignored_words()
        apply_items(expense, items, words, flagged=flagged)
        if expense.total <= 0:
            raise ValidationError('Informe o valor de pelo menos um item.')
        access_key = (expense.ai_reading or {}).get('access_key', '')
        if find_duplicate(expense.cnpj, expense.issue_date, expense.total, access_key, exclude=expense):
            raise ValidationError(DUPLICATE_ERROR)

        # A avaliação que falhou num envio continua valendo no reenvio da correção
        unevaluated = not evaluated or UNEVALUATED_REASON in expense.verification_reasons
        expense.verification_reasons = (
            verification_reasons(expense, words) + ([UNEVALUATED_REASON] if unevaluated else [])
        )
        expense.photo_checked = False
        # O centro de custo vem do cadastro do funcionário; o que o aprovador já trocou fica
        if expense.cost_center_id is None:
            expense.cost_center = user.cost_center
        # O prazo conta até o primeiro envio: a correção não envelhece a nota
        if expense.sent_at is None:
            expense.sent_at = timezone.now()
        change_status(expense, Expense.SENT, user)
    return expense


def delete_expense(expense_id, user):
    """O funcionário exclui a própria despesa enquanto ela não foi aprovada nem rejeitada."""
    with transaction.atomic():
        # O bloqueio espera a decisão do aprovador que estiver em andamento
        expense = Expense.objects.select_for_update().filter(pk=expense_id, user=user).first()
        if expense is None:
            raise Expense.DoesNotExist
        if expense.status not in DELETABLE:
            raise ValidationError('Esta despesa não pode mais ser excluída.')
        expense.delete()


def review_expense(expense_id, reviewer, action, note, photo_checked, cost_center, items):
    """
    O aprovador decide a despesa enviada: aprova, rejeita ou pede correção.

    Os itens e o centro de custo vão como ele os deixou. Na rejeição os itens
    ficam como o funcionário mandou, e `items` traz só o que o aprovador marcou
    como fora do reembolso ({id: marcado}): é o que explica a decisão a quem
    abrir a despesa depois.
    """
    status = REVIEW_ACTIONS[action]
    with transaction.atomic():
        expense = Expense.objects.select_for_update().get(pk=expense_id)
        if expense.user_id == reviewer.id:
            raise ValidationError('Você não pode aprovar a própria despesa.')
        if expense.status != Expense.SENT:
            raise ValidationError('Esta despesa não está mais aguardando aprovação.')
        if status != Expense.APPROVED and not note:
            raise ValidationError('Escreva a observação: é ela que explica ao funcionário o que fazer.')

        if status == Expense.REJECTED:
            for item in expense.items.all():
                if item.id in items and item.ignored != items[item.id]:
                    item.ignored = items[item.id]
                    item.save(update_fields=['ignored'])
            update_totals(expense)
        else:
            apply_items(expense, items, (), by_approver=True)
            if cost_center and cost_center.pk != expense.cost_center_id:
                if not cost_center.is_active:
                    raise ValidationError('Este centro de custo está inativo. Escolha outro.')
                expense.cost_center = cost_center

        if status == Expense.APPROVED:
            if expense.cost_center_id is None:
                raise ValidationError('Preencha o centro de custo para aprovar a despesa.')
            if expense.verification_reasons and not photo_checked:
                raise ValidationError('Esta despesa pede verificação: confira a foto e marque a conferência para aprovar.')
            if expense.reimbursable_total <= 0:
                raise ValidationError('Não sobrou valor a reembolsar. Reveja os itens ou rejeite a despesa.')
            duplicate = find_duplicate(
                expense.cnpj, expense.issue_date, expense.total, (expense.ai_reading or {}).get('access_key', ''),
                exclude=expense,
            )
            if duplicate:
                raise ValidationError(
                    f'A despesa nº {duplicate.pk} tem o mesmo CNPJ, a mesma data e o mesmo valor total desta.'
                )
            expense.photo_checked = photo_checked

        change_status(expense, status, reviewer, note)
    return expense


def expenses_queryset():
    return Expense.objects.select_related('user', 'cost_center').prefetch_related('items', 'photos', 'events__user')


def review_expenses():
    """As pendentes da tela de aprovações, da mais antiga para a mais nova."""
    return expenses_queryset().filter(status__in=PENDING).order_by('sent_at')


def closed_page(expenses, offset, viewer):
    """Uma página das encerradas, e se ainda há outra depois dela."""
    # Um a mais que a página só para saber se ainda há outra
    page = list(expenses[offset:offset + CLOSED_PAGE + 1])
    return serialize_expenses(page[:CLOSED_PAGE], viewer), len(page) > CLOSED_PAGE


def my_open_expenses(user):
    """As do funcionário que ainda pedem algo dele ou da empresa: vão inteiras para a página."""
    return expenses_queryset().filter(user=user).exclude(status__in=CLOSED)


def my_closed_expenses(user, status=None):
    """As encerradas do funcionário (ou só as de um status), da mais nova para a mais antiga, uma página por vez."""
    return expenses_queryset().filter(
        user=user, status__in=[status] if status else CLOSED,
    ).order_by('-created_at', '-id')


def my_expenses(user):
    """
    A lista do funcionário: as em aberto, que vêm todas, e a primeira página de
    cada status encerrado. As mais antigas vêm pela aba de cada um.
    """
    closed = [expense for status in CLOSED for expense in closed_page(my_closed_expenses(user, status), 0, user)[0]]
    return serialize_expenses(my_open_expenses(user), user) + closed


def my_counts(user):
    """Quantas despesas o funcionário tem em cada status, para as abas da tela dele."""
    # Sem o order_by() vazio, a ordenação padrão do modelo entraria no GROUP BY
    return dict(Expense.objects.filter(user=user).order_by().values_list('status').annotate(Count('id')))


def my_version(user):
    """
    Muda sempre que alguma despesa do funcionário muda (status, itens, exclusão).
    A tela dele confere só isto de tempos em tempos, numa consulta pequena, e
    pede a lista inteira apenas quando a versão é outra.
    """
    stats = Expense.objects.filter(user=user).aggregate(count=Count('id'), last=Max('updated_at'))
    return f'{stats["count"]}-{stats["last"].timestamp() if stats["last"] else 0}'


def closed_expenses(search='', cost_center='', needs_check=False):
    """
    As encerradas, da última mexida para a primeira. Cada palavra da busca
    precisa aparecer no usuário, no nome, no sobrenome ou no e-mail do
    funcionário, sem diferenciar acento nem maiúscula.
    """
    expenses = expenses_queryset().filter(status__in=CLOSED)
    # ponytail: o "contém" nos campos do usuário não usa índice; a tabela de
    # usuários é pequena. Índice de trigrama (pg_trgm) se ela crescer muito.
    for term in search.split():
        expenses = expenses.filter(
            Q(user__username__unaccent__icontains=term) | Q(user__first_name__unaccent__icontains=term)
            | Q(user__last_name__unaccent__icontains=term) | Q(user__email__unaccent__icontains=term)
        )
    if needs_check:
        expenses = expenses.exclude(verification_reasons=[])
    if cost_center == WITHOUT_COST_CENTER:
        expenses = expenses.filter(cost_center__isnull=True)
    elif cost_center:
        expenses = expenses.filter(cost_center_id=cost_center)
    return expenses.order_by('-updated_at', '-id')


def serialize_expenses(expenses, viewer):
    return [serialize_expense(expense, viewer) for expense in expenses]


def serialize_cost_center(cost_center):
    return {'id': cost_center.id, 'label': str(cost_center)} if cost_center else None


def serialize_expense(expense, viewer):
    events = list(expense.events.all())
    is_own = expense.user_id == viewer.id
    data = {
        'id': expense.id,
        'status': expense.status,
        'status_display': expense.get_status_display(),
        'user': author_name(expense.user),
        'is_own': is_own,
        'merchant': expense.merchant,
        'cnpj': expense.cnpj,
        'issue_date': expense.issue_date.isoformat() if expense.issue_date else None,
        'total': str(expense.total),
        'reimbursable_total': str(expense.reimbursable_total),
        'cost_center': serialize_cost_center(expense.cost_center),
        'created_at': timezone.localtime(expense.created_at).strftime('%d/%m/%Y %H:%M'),
        # A observação que vale é a da última mudança: depois que o funcionário
        # reenvia, a do pedido de correção fica só no histórico
        'note': events[-1].note if events else '',
        'photos': [
            {'id': photo.id, 'url': reverse('expenses:photo', args=[photo.id])} for photo in expense.photos.all()
        ],
        'items': [
            {
                'id': item.id,
                'description': item.description,
                'quantity': str(item.quantity.normalize() if item.quantity % 1 else item.quantity.to_integral()),
                'amount': str(item.amount),
                'unreadable': item.unreadable,
                'ignored': item.ignored,
            }
            for item in expense.items.all()
        ],
        'events': [
            {
                'status': event.status,
                'status_display': event.get_status_display(),
                'user': author_name(event.user),
                'note': event.note,
                'created_at': timezone.localtime(event.created_at).strftime('%d/%m/%Y %H:%M'),
            }
            for event in events
        ],
    }
    # Os avisos e a leitura original são de quem aprova ou paga. O funcionário
    # nunca os recebe, nem quando ele mesmo é aprovador.
    if can_review(viewer) and not is_own:
        data.update({
            'verification_reasons': expense.verification_reasons,
            'photo_checked': expense.photo_checked,
            'reading': expense.ai_reading,
            # O que a busca da fila consulta, num campo só
            'user_search': ' '.join(filter(None, (
                expense.user.username, expense.user.first_name, expense.user.last_name, expense.user.email,
            ))),
        })
    return data
