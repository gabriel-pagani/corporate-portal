from functools import wraps

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST

from app.views import form_errors_response, json_permission_required, parse_json_body
from app.models import CostCenter, ServiceAccess
from app.utils.notifications.delivery import author_name
from app.utils.services import track_access
from expenses.forms import ExpenseHeaderForm, ExpenseItemForm, IgnoredWordForm, ReviewForm
from expenses.models import Expense, ExpensePhoto, GuideSeen, IgnoredWord, IgnoredWordEvent
from expenses.payment import pay
from expenses.receipts import MAX_ITEMS, MAX_PHOTO_SIZE, MAX_PHOTOS
from expenses.workflow import (
    CLOSED, WITHOUT_COST_CENTER, can_review, can_submit, closed_expenses, closed_page, delete_expense, expenses_queryset,
    my_closed_expenses, my_counts, my_expenses, my_version, read_photos, review_expense, review_expenses, serialize_cost_center,
    serialize_expense, serialize_expenses, submit_expense,
)


def submit_required(view):
    """As rotas de quem lança despesa: quem aprova, paga ou configura não passa, nem chamando a API direto."""
    @wraps(view)
    @json_permission_required('expenses.access_expenses')
    def wrapper(request, *args, **kwargs):
        if not can_submit(request.user):
            return JsonResponse({'detail': 'Quem gerencia o reembolso não pode lançar despesas.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


def settings_payload():
    return {
        'words': [{'id': word.id, 'word': word.word} for word in IgnoredWord.objects.all()],
    }


def log_word(word, action, user):
    """A auditoria da mudança, vista só no admin (expenses/admin.py)."""
    IgnoredWordEvent.objects.create(word=word, action=action, user=user, user_name=author_name(user))


def expense_response(expense, viewer, status=200, **extra):
    # Relida do banco: os itens, as fotos e o histórico acabaram de mudar
    expense = expenses_queryset().get(pk=expense.pk)
    return JsonResponse({'expense': serialize_expense(expense, viewer), **extra}, status=status)


def validation_error_response(error):
    return JsonResponse({'detail': error.messages[0]}, status=400)


@login_required
@permission_required('expenses.access_expenses', raise_exception=True)
@require_http_methods(['GET'])
@track_access(ServiceAccess.EXPENSES)
def expenses_view(request):
    user = request.user
    permissions = {
        'submit': can_submit(user),
        'approve': user.has_perm('expenses.approve_expense'),
        'reimburse': user.has_perm('expenses.reimburse_expense'),
        'settings': user.has_perm('expenses.manage_expense_settings'),
    }
    reviews = permissions['approve'] or permissions['reimburse']
    # As encerradas crescem sem parar e vêm aos poucos, para a página abrir rápido no celular
    return render(request, 'expenses/index.html', {
        'permissions': permissions,
        'reviews': reviews,
        'my_expenses': my_expenses(user) if permissions['submit'] else [],
        'my_counts': my_counts(user) if permissions['submit'] else {},
        'my_version': my_version(user) if permissions['submit'] else '',
        'show_guide': permissions['submit'] and not GuideSeen.objects.filter(user=user).exists(),
        # A fila e os avisos dela só vão para a página de quem aprova ou paga
        'review_expenses': serialize_expenses(review_expenses(), user) if reviews else None,
        'cost_centers': [
            serialize_cost_center(cost_center) for cost_center in CostCenter.objects.filter(is_active=True)
        ] if permissions['approve'] else [],
        # O filtro da fila inclui os inativos: as despesas antigas continuam com eles
        'filter_cost_centers': CostCenter.objects.all() if reviews else [],
        'without_cost_center': WITHOUT_COST_CENTER,
        'photo_limits': {'max_photos': MAX_PHOTOS, 'max_size': MAX_PHOTO_SIZE},
        'settings': settings_payload() if permissions['settings'] else None,
    })


# As fotos ficam no media_volume e só saem por aqui: para o dono da despesa e,
# depois de enviada, para quem aprova ou paga
@login_required
@permission_required('expenses.access_expenses', raise_exception=True)
@require_http_methods(['GET'])
def photo_view(request, photo_id):
    photo = get_object_or_404(ExpensePhoto.objects.select_related('expense'), id=photo_id)
    expense = photo.expense
    reviewer = can_review(request.user) and expense.status != Expense.DRAFT
    if expense.user_id != request.user.id and not reviewer:
        raise Http404('Foto não encontrada.')
    try:
        file = photo.file.open('rb')
    except FileNotFoundError:
        raise Http404('Foto não encontrada.')

    # Toda foto guardada foi regravada em JPEG pelo Pillow
    response = FileResponse(file, content_type='image/jpeg')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    return response


def read_response(request, expense=None):
    try:
        expense, was_read = read_photos(request.user, request.FILES.getlist('photos'), expense)
    except ValidationError as error:
        return validation_error_response(error)
    return expense_response(expense, request.user, status=201, read=was_read)


@require_POST
@submit_required
def expenses_api(request):
    return read_response(request)


@require_POST
@submit_required
def expense_photos_api(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id, user=request.user, status__in=Expense.EDITABLE)
    return read_response(request, expense)


def clean_items(raw_items):
    """Os itens conferidos, ou a resposta de erro no lugar deles."""
    if not isinstance(raw_items, list) or not raw_items:
        return None, JsonResponse({'detail': 'Informe pelo menos um item da nota.'}, status=400)
    if len(raw_items) > MAX_ITEMS:
        return None, JsonResponse({'detail': f'A despesa aceita até {MAX_ITEMS} itens.'}, status=400)

    items = []
    for raw_item in raw_items:
        form = ExpenseItemForm(raw_item if isinstance(raw_item, dict) else {})
        if not form.is_valid():
            return None, form_errors_response(form)
        items.append(form.cleaned_data)
    return items, None


@require_http_methods(['POST', 'DELETE'])
@submit_required
def expense_api(request, expense_id):
    if request.method == 'DELETE':
        return expense_delete(request, expense_id)
    return expense_submit(request, expense_id)


def expense_submit(request, expense_id):
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)
    header = ExpenseHeaderForm(payload)
    if not header.is_valid():
        return form_errors_response(header)
    items, error = clean_items(payload.get('items'))
    if error:
        return error

    try:
        expense = submit_expense(expense_id, request.user, header.cleaned_data, items)
    except ValidationError as error:
        return validation_error_response(error)
    return expense_response(expense, request.user)


def expense_delete(request, expense_id):
    try:
        delete_expense(expense_id, request.user)
    except Expense.DoesNotExist:
        raise Http404
    except ValidationError as error:
        return validation_error_response(error)
    return JsonResponse({'status': 'success'})


@require_POST
@json_permission_required('expenses.approve_expense')
def expense_review_api(request, expense_id):
    get_object_or_404(Expense.objects.exclude(status=Expense.DRAFT), id=expense_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)
    form = ReviewForm(payload)
    if not form.is_valid():
        return form_errors_response(form)
    review = form.cleaned_data

    if review['action'] == 'reject':
        # A rejeição não depende de os itens estarem bem preenchidos: dela só fica
        # registrado o que o aprovador marcou como fora do reembolso
        raw_items = payload.get('items')
        items = {
            item.get('id'): item.get('ignored') is True
            for item in (raw_items if isinstance(raw_items, list) else []) if isinstance(item, dict)
        }
    else:
        items, error = clean_items(payload.get('items'))
        if error:
            return error

    try:
        expense = review_expense(
            expense_id, request.user, review['action'], review['note'], review['photo_checked'],
            review['cost_center'], items,
        )
    except ValidationError as error:
        return validation_error_response(error)
    return expense_response(expense, request.user)


@require_http_methods(['GET'])
@json_permission_required('expenses.access_expenses')
def closed_expenses_api(request):
    if not can_review(request.user):
        return JsonResponse({'detail': 'Você não tem permissão para esta ação.'}, status=403)
    cost_center = request.GET.get('cost_center', '')
    offset = request.GET.get('offset', '0')
    if not offset.isdigit() or not (cost_center in ('', WITHOUT_COST_CENTER) or cost_center.isdigit()):
        return JsonResponse({'detail': 'Filtro inválido.'}, status=400)

    expenses = closed_expenses(request.GET.get('q', '')[:200], cost_center, request.GET.get('needs_check') == '1')
    page, has_more = closed_page(expenses, int(offset), request.user)
    return JsonResponse({'expenses': page, 'count': expenses.count(), 'has_more': has_more})


@require_http_methods(['GET'])
@submit_required
def my_expenses_api(request):
    """A tela do funcionário pergunta se algo mudou: só a versão, ou a lista nova quando mudou."""
    version = my_version(request.user)
    if request.GET.get('version') == version:
        return JsonResponse({'changed': False})
    return JsonResponse({
        'changed': True, 'version': version, 'expenses': my_expenses(request.user), 'counts': my_counts(request.user),
    })


@require_POST
@submit_required
def guide_seen_api(request):
    """O guia abriu: não abre sozinho de novo para esta pessoa, nem em outro aparelho."""
    GuideSeen.objects.get_or_create(user=request.user)
    return JsonResponse({})


@require_http_methods(['GET'])
@submit_required
def my_closed_expenses_api(request):
    offset = request.GET.get('offset', '0')
    status = request.GET.get('status', '')
    if not offset.isdigit() or (status and status not in CLOSED):
        return JsonResponse({'detail': 'Filtro inválido.'}, status=400)
    page, has_more = closed_page(my_closed_expenses(request.user, status or None), int(offset), request.user)
    return JsonResponse({'expenses': page, 'has_more': has_more})


@require_POST
@json_permission_required('expenses.reimburse_expense')
def expense_reimburse_api(request, expense_id):
    get_object_or_404(Expense.objects.exclude(status=Expense.DRAFT), id=expense_id)
    try:
        expense = pay(expense_id, request.user)
    except ValidationError as error:
        return validation_error_response(error)
    return expense_response(expense, request.user)


@require_POST
@json_permission_required('expenses.manage_expense_settings')
def ignored_words_api(request):
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = IgnoredWordForm(payload)
    if not form.is_valid():
        return form_errors_response(form)
    # A mudança e o registro dela andam juntos: não existe uma sem o outro
    with transaction.atomic():
        word = form.save()
        log_word(word.word, IgnoredWordEvent.ADDED, request.user)
    return JsonResponse(settings_payload(), status=201)


@require_http_methods(['DELETE'])
@json_permission_required('expenses.manage_expense_settings')
def ignored_word_api(request, word_id):
    with transaction.atomic():
        word = get_object_or_404(IgnoredWord.objects.select_for_update(), id=word_id)
        log_word(word.word, IgnoredWordEvent.REMOVED, request.user)
        word.delete()
    return JsonResponse(settings_payload())
