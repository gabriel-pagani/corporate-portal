import unicodedata
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.models import ServiceAccess
from app.utils.services import track_access
from app.views import json_login_required, parse_json_body
from expenses.models import Expense, ExpenseEvent, ExpenseItem, ExpensePhoto, ExpenseType
from expenses.photos import ACCEPTED_TYPES, MAX_PHOTO_SIZE, MAX_PHOTOS
from expenses.roles import access
from expenses.serializers import serialize_detail, serialize_summary
from expenses.workflow import Conflict, act, resubmit_photos, submit_expense, visible_expenses


PAGE_SIZE = 25

BLOCKED_MESSAGE = (
    'O seu cadastro tem uma combinação de permissões das despesas que não é permitida. '
    'Procure o administrador do portal.'
)

NO_PERMISSION = 'Você não tem permissão para esta ação.'


def expense_access_required(view):
    """As rotas da API das despesas: quem não tem papel, ou tem papel em conflito, não passa."""
    @wraps(view)
    @json_login_required
    def wrapper(request, *args, **kwargs):
        current = access(request.user)
        if current.conflict:
            return JsonResponse({'detail': BLOCKED_MESSAGE}, status=403)
        if not current.any_role:
            return JsonResponse({'detail': NO_PERMISSION}, status=403)
        request.expense_access = current
        return view(request, *args, **kwargs)
    return wrapper


def error_response(error, status=400):
    if hasattr(error, 'error_dict'):
        errors = error.message_dict
        first = next(iter(errors.values()))[0]
        return JsonResponse({'detail': first, 'errors': errors}, status=status)
    return JsonResponse({'detail': error.messages[0]}, status=status)


def portal_link(request):
    return request.build_absolute_uri(reverse('expenses:expenses'))


def detail_queryset(user):
    return visible_expenses(user).prefetch_related(
        Prefetch('items', queryset=ExpenseItem.objects.order_by('position', 'id')),
        Prefetch('photos', queryset=ExpensePhoto.objects.order_by('position', 'id')),
        Prefetch('events', queryset=ExpenseEvent.objects.select_related('author').order_by('sequence')),
    )


def detail_response(request, expense_id, status=200):
    expense = get_object_or_404(detail_queryset(request.user), pk=expense_id)
    return JsonResponse(
        {'expense': serialize_detail(expense, request.user, request.expense_access)}, status=status,
    )


@login_required
@require_GET
@track_access(ServiceAccess.EXPENSES)
def expenses_view(request, expense_id=None, screen='list'):
    """A tela das despesas. A lista, o envio (/expenses/add/) e cada despesa (/expenses/12/) têm a sua rota."""
    current = access(request.user)
    if current.conflict:
        return render(request, 'expenses/blocked.html', {'message': BLOCKED_MESSAGE}, status=403)
    if not current.any_role:
        raise PermissionDenied
    if screen == 'add' and not current.employee:
        raise PermissionDenied
    if expense_id is not None:
        # Quem não pode ver a despesa recebe o mesmo 404 de uma que não existe
        get_object_or_404(visible_expenses(request.user), pk=expense_id)

    return render(request, 'expenses/index.html', {
        'access': {
            'employee': current.employee,
            'control': current.control,
            'finance': current.finance,
        },
        'types': [{'id': item.id, 'name': item.name} for item in ExpenseType.objects.all()] if current.control else [],
        'limits': {'max_photos': MAX_PHOTOS, 'max_size': MAX_PHOTO_SIZE, 'accepted': ACCEPTED_TYPES},
        'statuses': [{'value': value, 'label': label} for value, label in Expense.STATUS],
    })


def without_accents(text):
    # O unaccent do banco tira o acento da coluna; o termo digitado chega como veio
    return ''.join(
        letter for letter in unicodedata.normalize('NFD', text) if not unicodedata.combining(letter)
    )


def queue_statuses(current):
    statuses = []
    if current.control:
        statuses += Expense.WITH_CONTROL
    if current.finance:
        statuses += Expense.WITH_FINANCE
    return statuses


def search_filter(term):
    term = term.strip()
    plain = without_accents(term)
    query = (
        Q(number__icontains=term)
        | Q(cnpj__icontains=term.replace('.', '').replace('/', '').replace('-', ''))
        | Q(employee__username__icontains=term)
        | Q(employee__first_name__unaccent__icontains=plain)
        | Q(employee__last_name__unaccent__icontains=plain)
    )
    if term.lstrip('#').isdigit():
        query |= Q(pk=int(term.lstrip('#')))
    return query


@require_http_methods(['GET', 'POST'])
@expense_access_required
def expenses_api(request):
    if request.method == 'POST':
        return expense_submit(request)

    current = request.expense_access
    if current.reviewer:
        scope = 'queue' if request.GET.get('scope') == 'queue' else 'all'
    else:
        scope = 'mine'
    expenses = visible_expenses(request.user)
    if scope == 'queue':
        expenses = expenses.filter(status__in=queue_statuses(current)).order_by('created_at', 'id')
    else:
        expenses = expenses.order_by('-created_at', '-id')

    # Uma situação ou várias, separadas por vírgula ("C,E,V" é o "em andamento" do funcionário)
    statuses = [value for value in request.GET.get('status', '').split(',') if value in dict(Expense.STATUS)]
    if statuses:
        expenses = expenses.filter(status__in=statuses)
    term = request.GET.get('q', '')
    if term.strip() and current.reviewer:
        expenses = expenses.filter(search_filter(term))

    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except ValueError:
        page = 1
    start = (page - 1) * PAGE_SIZE
    rows = list(expenses[start:start + PAGE_SIZE + 1])

    data = {
        'scope': scope,
        'expenses': [serialize_summary(expense, current) for expense in rows[:PAGE_SIZE]],
        'page': page,
        'has_next': len(rows) > PAGE_SIZE,
    }
    if current.reviewer:
        data['queue_count'] = Expense.objects.filter(status__in=queue_statuses(current)).count()
    else:
        # Os números dos filtros do funcionário, pelas notas dele
        data['counts'] = {
            row['status']: row['total']
            for row in Expense.objects.filter(employee=request.user).values('status').annotate(total=Count('id'))
        }
    return JsonResponse(data)


def expense_submit(request):
    if not request.expense_access.employee:
        return JsonResponse({'detail': 'Só o funcionário envia notas.'}, status=403)
    try:
        expense = submit_expense(
            request.user, request.FILES.getlist('photos'), request.POST.get('note', ''), link=portal_link(request),
        )
    except ValidationError as error:
        return error_response(error)
    return detail_response(request, expense.pk, status=201)


@require_GET
@expense_access_required
def expense_api(request, expense_id):
    return detail_response(request, expense_id)


@require_POST
@expense_access_required
def expense_action_api(request, expense_id):
    if not request.expense_access.reviewer:
        return JsonResponse({'detail': NO_PERMISSION}, status=403)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)
    get_object_or_404(visible_expenses(request.user), pk=expense_id)

    try:
        version = int(payload.get('version'))
    except (TypeError, ValueError):
        version = None
    try:
        act(
            request.user, expense_id, payload.get('action'), payload.get('note', ''), version,
            data=payload.get('data'), link=portal_link(request),
        )
    except Conflict as error:
        return JsonResponse({'detail': str(error)}, status=409)
    except PermissionDenied as error:
        return JsonResponse({'detail': str(error) or NO_PERMISSION}, status=403)
    except ValidationError as error:
        return error_response(error)
    return detail_response(request, expense_id)


@require_POST
@expense_access_required
def expense_photos_api(request, expense_id):
    if not request.expense_access.employee:
        return JsonResponse({'detail': 'Só o funcionário reenvia as fotos.'}, status=403)
    get_object_or_404(Expense, pk=expense_id, employee=request.user)
    try:
        resubmit_photos(
            request.user, expense_id, request.FILES.getlist('photos'), request.POST.get('note', ''),
            link=portal_link(request),
        )
    except ValidationError as error:
        return error_response(error)
    return detail_response(request, expense_id)


# As fotos ficam no media_volume e só saem por aqui, para quem vê a nota. As
# substituídas no reenvio continuam abrindo: o histórico aponta para elas.
@login_required
@require_GET
def photo_view(request, photo_id):
    photo = get_object_or_404(ExpensePhoto, pk=photo_id)
    if not visible_expenses(request.user).filter(pk=photo.expense_id).exists():
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
