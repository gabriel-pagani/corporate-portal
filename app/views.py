import json
from functools import wraps
from app.models import Contact, Toner, TonerLocation, TonerMovement
from app.forms import LoginForm, TonerForm, TonerUpdateForm, TonerMovementForm
from app.utils.dashboards.access import get_user_dashboards
from app.utils.customer_vendor.auth import api_token_required
from app.utils.customer_vendor.registration import register_customers_vendors
from app.utils.toners.stock import (
    serialize_toner, serialize_movement, register_movement, toners_queryset, has_movements,
)
from app.utils.notifications.delivery import unread_notifications, serialize_notification
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme


def get_safe_next_url(request, next_url):
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


@login_required
def home_view(request):
    return render(request, 'app/home.html')


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        next_url = get_safe_next_url(request, request.POST.get('next'))

        if form.is_valid():
            user = authenticate(
                username=form.cleaned_data.get('username', ''),
                password=form.cleaned_data.get('password', ''),
            )

            if user is not None:
                login(request, user)
                return redirect(next_url or reverse('app:home'))
            else:
                messages.error(request, 'Dados inválidos!')
        else:
            messages.error(request, 'Preencha todos os campos!')
    else:
        form = LoginForm()
        next_url = get_safe_next_url(request, request.GET.get('next'))

    return render(request, 'app/login.html', {
        'form': form,
        'next': next_url
    })


def logout_view(request):
    logout(request)
    messages.success(request, 'Você se desconectou com sucesso!')
    return redirect('app:login')


def contacts_view(request):
    contacts = [
        {
            'name': contact.get_display_name(),
            'number': contact.number or '',
            'sector': contact.sector.name if contact.sector else '',
            'machine': contact.machine or '',
        }
        for contact in Contact.objects.select_related('sector', 'user').all()
    ]

    return render(request, 'app/contacts.html', {
        'contacts': contacts
    })


@login_required
def dashboards_view(request):
    user = request.user
    dashboards = get_user_dashboards(user)

    dashboards_dict = {'Favoritos': []}
    for dashboard in dashboards:
        is_fav = user in dashboard.fav_by.all()
        sector = dashboard.sector.name if dashboard.sector else 'Sem Setor'
        dashboard_payload = {
            'id': dashboard.id,
            'title': dashboard.title,
            'url': dashboard.get_absolute_url(),
            'status': dashboard.status,
            'is_fav': is_fav,
            'sector': sector,
        }

        if is_fav:
            dashboards_dict['Favoritos'].append(dashboard_payload)
            continue

        dashboards_dict.setdefault(sector, []).append(dashboard_payload)

    if not dashboards_dict['Favoritos']:
        del dashboards_dict['Favoritos']

    if 'Sem Setor' in dashboards_dict:
        dashboards_dict['Sem Setor'] = dashboards_dict.pop('Sem Setor')

    return render(request, 'app/dashboards.html', {
        'dashboards': dashboards_dict
    })


@login_required
def dashboard_view(request, dashboard_id):
    user = request.user
    current_dashboard = get_object_or_404(get_user_dashboards(user), id=dashboard_id)
    dashboards = get_user_dashboards(user)

    dashboards_dict = {'Favoritos': []}
    for dashboard in dashboards:
        is_fav = user in dashboard.fav_by.all()
        sector = dashboard.sector.name if dashboard.sector else 'Sem Setor'
        dashboard_payload = {
            'id': dashboard.id,
            'title': dashboard.title,
            'url': dashboard.get_absolute_url(),
            'status': dashboard.status,
            'is_fav': is_fav,
            'sector': sector,
        }

        if is_fav:
            dashboards_dict['Favoritos'].append(dashboard_payload)
            continue

        dashboards_dict.setdefault(sector, []).append(dashboard_payload)

    if not dashboards_dict['Favoritos']:
        del dashboards_dict['Favoritos']

    if 'Sem Setor' in dashboards_dict:
        dashboards_dict['Sem Setor'] = dashboards_dict.pop('Sem Setor')

    current_dashboard = {
        'id': current_dashboard.id,
        'url_iframe': current_dashboard.metabase_url or current_dashboard.powerbi_url or '',
    }

    return render(request, 'app/dashboards.html', {
        'current_dashboard': current_dashboard,
        'dashboards': dashboards_dict
    })


@login_required
@require_POST
def favorite_dashboard(request, dashboard_id):
    user = request.user
    dashboard = get_object_or_404(get_user_dashboards(user), id=dashboard_id)

    if user in dashboard.fav_by.all():
        dashboard.fav_by.remove(user)
        is_favorite = False
    else:
        dashboard.fav_by.add(user)
        is_favorite = True

    return JsonResponse({'status': 'success', 'is_favorite': is_favorite})


@csrf_exempt
@require_POST
@api_token_required
def customers_vendors_api(request):
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    entries = payload.get('customers_vendors') if isinstance(payload, dict) else payload

    if not isinstance(entries, list):
        return JsonResponse(
            {'detail': 'Body vazio.'},
            status=400,
        )

    if not entries:
        return JsonResponse({'detail': 'Body vazio.'}, status=400)

    data = register_customers_vendors(entries)

    status = 207 if data['summary']['errors'] and data['summary']['errors'] < data['summary']['total'] else (
        400 if data['summary']['errors'] == data['summary']['total'] else 200
    )

    return JsonResponse(data, status=status)


def json_permission_required(perm):
    # Equivalente ao permission_required, mas respondendo JSON para as chamadas da API
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'detail': 'Sessão expirada, faça login novamente.'}, status=401)
            if not request.user.has_perm(perm):
                return JsonResponse({'detail': 'Você não tem permissão para esta ação.'}, status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def parse_json_body(request):
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def form_errors_response(form):
    errors = {field: [str(error) for error in field_errors] for field, field_errors in form.errors.items()}
    first_error = next(iter(errors.values()))[0]
    return JsonResponse({'detail': first_error, 'errors': errors}, status=400)


@login_required
@permission_required('app.view_toner', raise_exception=True)
def toners_view(request):
    user = request.user
    toners = [serialize_toner(toner) for toner in toners_queryset()]

    return render(request, 'app/toners.html', {
        'toners': toners,
        'locations': list(TonerLocation.objects.values('id', 'name')),
        'permissions': {
            'add': user.has_perm('app.add_toner'),
            'change': user.has_perm('app.change_toner'),
            'delete': user.has_perm('app.delete_toner'),
            'move': user.has_perm('app.add_tonermovement'),
        },
    })


@require_http_methods(['GET', 'POST'])
def toners_api(request):
    if request.method == 'GET':
        return toners_list(request)
    return toner_create(request)


@json_permission_required('app.view_toner')
def toners_list(request):
    return JsonResponse({'toners': [serialize_toner(toner) for toner in toners_queryset()]})


@json_permission_required('app.add_toner')
def toner_create(request):
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = TonerForm(payload)
    if not form.is_valid():
        return form_errors_response(form)

    try:
        initial_quantity = int(payload.get('quantity') or 0)
    except (TypeError, ValueError):
        initial_quantity = -1
    if initial_quantity < 0:
        return JsonResponse({'detail': 'Informe uma quantidade válida.'}, status=400)

    with transaction.atomic():
        toner = form.save()
        # O estoque inicial entra como movimentação para o histórico ficar consistente
        if initial_quantity:
            toner, _ = register_movement(
                toner.id, TonerMovement.ENTRY, initial_quantity, 'Estoque inicial', request.user,
            )

    return JsonResponse({'toner': serialize_toner(toner)}, status=201)


@require_http_methods(['POST', 'DELETE'])
def toner_api(request, toner_id):
    if request.method == 'DELETE':
        return toner_delete(request, toner_id)
    return toner_update(request, toner_id)


@json_permission_required('app.change_toner')
def toner_update(request, toner_id):
    toner = get_object_or_404(toners_queryset(), id=toner_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    # O nome identifica o toner no histórico, então só muda enquanto não houver movimentação
    form_class = TonerUpdateForm if has_movements(toner) else TonerForm
    form = form_class(payload, instance=toner)
    if not form.is_valid():
        return form_errors_response(form)

    toner = form.save()
    return JsonResponse({'toner': serialize_toner(toner)})


@json_permission_required('app.delete_toner')
def toner_delete(request, toner_id):
    toner = get_object_or_404(Toner, id=toner_id)
    toner.delete()
    return JsonResponse({'status': 'success'})


@require_http_methods(['GET', 'POST'])
def toner_movements_api(request, toner_id):
    if request.method == 'GET':
        return toner_movements_list(request, toner_id)
    return toner_movement_create(request, toner_id)


@json_permission_required('app.view_toner')
def toner_movements_list(request, toner_id):
    toner = get_object_or_404(Toner, id=toner_id)
    movements = toner.movements.select_related('user')
    return JsonResponse({'movements': [serialize_movement(movement) for movement in movements]})


@json_permission_required('app.add_tonermovement')
def toner_movement_create(request, toner_id):
    get_object_or_404(Toner, id=toner_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = TonerMovementForm(payload)
    if not form.is_valid():
        return form_errors_response(form)

    try:
        toner, movement = register_movement(
            toner_id,
            form.cleaned_data['type'],
            form.cleaned_data['quantity'],
            form.cleaned_data['reason'],
            request.user,
        )
    except ValidationError as error:
        return JsonResponse({'detail': error.messages[0]}, status=400)

    return JsonResponse({'toner': serialize_toner(toner), 'movement': serialize_movement(movement)}, status=201)


@require_http_methods(['GET'])
def notifications_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Sessão expirada, faça login novamente.'}, status=401)

    notifications = unread_notifications(request.user)
    return JsonResponse({'notifications': [serialize_notification(n) for n in notifications]})


@require_POST
def notification_read_api(request, notification_id):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Sessão expirada, faça login novamente.'}, status=401)

    # Só marca como lida o que realmente foi entregue a este usuário
    notification = get_object_or_404(unread_notifications(request.user), id=notification_id)
    notification.read_by.add(request.user)
    return JsonResponse({'status': 'success'})
