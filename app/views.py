import json
import requests
from functools import wraps
from datetime import datetime, timedelta
from app.models import (
    Contact, HomeLayout, LibraryDocument, LibraryFolder, Sector, ServiceAccess, Toner, TonerLocation, TonerMovement,
    User,
)
from app.forms import (
    LoginForm, TonerForm, TonerUpdateForm, TonerMovementForm, ContactForm, LibraryDocumentForm, LibraryFolderForm,
)
from app.utils import otp, throttle
from app.utils.dashboards.access import get_user_dashboards
from app.utils.home import quick_access_cards
from app.utils.services import (
    CARD_DEFAULT_HEIGHT, CARD_MAX_HEIGHT, CARD_MIN_HEIGHT, TICKETS_URL, ranked_services, save_layout, track_access,
)
from app.utils.customer_vendor.auth import api_token_required
from app.utils.customer_vendor.registration import register_customers_vendors, sanitize_entry
from app.utils.toners.stock import (
    serialize_toner, serialize_movement, serialize_request_item, register_movement, request_toners,
    toners_queryset, has_movements,
)
from app.utils.notifications.delivery import (
    visible_notifications, unread_notifications, serialize_notification,
)
from app.utils.library import (
    ALLOWED_EXTENSIONS, MAX_FILE_SIZE, PREVIEW_CONTENT_TYPES, TEXT_PREVIEW_BYTES, file_extension,
    library_permissions, preview_kind, preview_text, recipient_choices, serialize_document, serialize_folder,
    visible_documents, visible_folders,
)
from django.shortcuts import render, get_object_or_404, redirect
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, ProtectedError
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csp import csp_override
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.csp import CSP
from axes.handlers.proxy import AxesProxyHandler
from django_otp import login as otp_login, match_token


LOGIN_THROTTLED_ERROR = 'Muitas tentativas de login. Espere uma hora e tente novamente.'

TOKEN_INVALID_ERROR = 'Código inválido! Digite o código que o aplicativo mostra agora.'

# Entre a senha e o código o usuário fica guardado na sessão, e só isso: a
# sessão segue anônima, e nada do portal abre com essa espera na mão.
PENDING_LOGIN = 'otp_pending'

# Tempo para digitar o código. Vencido, a senha é pedida de novo: a espera não
# pode virar meia sessão esquecida num computador emprestado.
PENDING_LOGIN_TIMEOUT = timedelta(minutes=5)


def login_throttled(request, username):
    # A recusa por teto de tentativas chega igual à de senha errada: os dois
    # tetos interrompem a fila de backends, e o authenticate devolve None.
    # Quem espera uma hora precisa saber por quê, e saber que o teto estourou
    # não conta nada sobre a conta que já não se soubesse.
    return throttle.login_blocked(username) or not AxesProxyHandler.is_allowed(request, {'username': username})


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
    cards = quick_access_cards(request.user)
    contacts = next(
        (card['preview']['contacts'] for card in cards if card['service'].key == ServiceAccess.CONTACTS), [],
    )
    return render(request, 'app/home.html', {
        'has_dashboards': any(card['service'].key == ServiceAccess.DASHBOARDS for card in cards),
        'cards': cards,
        'visible_cards': [card for card in cards if not card['hidden']],
        'card_default_height': CARD_DEFAULT_HEIGHT,
        'card_min_height': CARD_MIN_HEIGHT,
        'card_max_height': CARD_MAX_HEIGHT,
        'contacts': contacts,
        # A ordem pelos acessos, que o "Restaurar padrão" mostra sem ir ao
        # servidor: só o Concluir grava, para o Esc poder desfazer tudo
        'default_order': [service.key for service in ranked_services(request.user)],
    })


# A central de chamados é um sistema de fora: o link passa por aqui só para o
# acesso contar na ordem dos cards da home
@login_required
@require_http_methods(['GET'])
@track_access(ServiceAccess.TICKETS)
def tickets_view(request):
    return redirect(TICKETS_URL)


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        next_url = get_safe_next_url(request, request.POST.get('next'))

        if form.is_valid():
            username = form.cleaned_data.get('username', '')
            # O request vai junto: é dele que o axes tira o IP para contar as
            # tentativas, e sem ele o teto por usuário e IP não existe.
            user = authenticate(
                request,
                username=username,
                password=form.cleaned_data.get('password', ''),
            )

            if user is not None:
                # Administrador com aplicativo cadastrado só entra com o código.
                # O que ainda não cadastrou entra e é levado ao cadastro pelo
                # RequireOTPMiddleware, antes de chegar a qualquer tela.
                if otp.requires_otp(user) and otp.confirmed_device(user):
                    request.session[PENDING_LOGIN] = {
                        'user': user.pk,
                        # O backend que conferiu a senha, para o login entrar pelo
                        # mesmo: o do LDAP e o local guardam a sessão diferente.
                        'backend': user.backend,
                        'next': next_url,
                        'since': timezone.now().isoformat(),
                    }
                    return redirect('app:login-token')

                login(request, user)
                return redirect(next_url or reverse('app:home'))
            elif login_throttled(request, username):
                messages.error(request, LOGIN_THROTTLED_ERROR)
            else:
                messages.error(request, 'Dados inválidos!')
        else:
            messages.error(request, 'Preencha todos os campos!')
    else:
        # Abrir a tela da senha é recomeçar: a espera de código que sobrou de
        # outra tentativa não vale mais.
        request.session.pop(PENDING_LOGIN, None)
        form = LoginForm()
        next_url = get_safe_next_url(request, request.GET.get('next'))

    return render(request, 'app/login.html', {
        'form': form,
        'next': next_url
    })


def pending_login(request):
    """Quem já passou pela senha e ainda deve o código; None se não há ou venceu."""
    data = request.session.get(PENDING_LOGIN)
    if not data:
        return None

    if timezone.now() - datetime.fromisoformat(data['since']) > PENDING_LOGIN_TIMEOUT:
        del request.session[PENDING_LOGIN]
        return None

    # Relido do banco: entre uma etapa e outra a conta pode ter sido desativada.
    return User.objects.filter(pk=data['user'], is_active=True).first()


def login_token_view(request):
    user = pending_login(request)
    if user is None:
        return redirect('app:login')

    if request.method == 'POST':
        # O match_token segura a repetição: cada código errado dobra a espera
        # até o próximo palpite ser conferido.
        device = match_token(user, request.POST.get('token', '').strip())

        if device is not None:
            data = request.session.pop(PENDING_LOGIN)
            login(request, user, backend=data['backend'])
            otp_login(request, device)
            return redirect(data['next'] or reverse('app:home'))

        messages.error(request, TOKEN_INVALID_ERROR)

    return render(request, 'app/login_token.html')


@login_required
def otp_setup_view(request):
    """
    O cadastro do aplicativo autenticador, no primeiro login do administrador.

    O segredo só é confirmado quando a pessoa devolve um código gerado por ele:
    assim ninguém fica com um segundo fator que nunca conseguiu usar.
    """
    user = request.user

    # Um segundo dispositivo deixaria dois segredos válidos para a mesma conta.
    # Para trocar de celular, apague o dispositivo no portal de administração.
    if not otp.requires_otp(user) or otp.confirmed_device(user):
        return redirect('app:home')

    device = otp.pending_device(user)

    if request.method == 'POST':
        if device.verify_token(request.POST.get('token', '').strip()):
            device.confirmed = True
            device.save(update_fields=['confirmed'])
            # A pessoa acabou de provar que tem o aplicativo: pedir o código de
            # novo agora seria só atrito.
            otp_login(request, device)
            return redirect('app:home')

        messages.error(request, TOKEN_INVALID_ERROR)

    return render(request, 'app/otp_setup.html', {
        'qr': otp.qr_of(device),
        'secret': otp.secret_of(device),
    })


def logout_view(request):
    logout(request)
    messages.success(request, 'Você se desconectou com sucesso!')
    return redirect('app:login')


@login_required
@track_access(ServiceAccess.CONTACTS)
def contacts_view(request):
    can_add = request.user.has_perm('app.add_contact')
    can_change = request.user.has_perm('app.change_contact')
    form = None
    if request.method == 'POST':
        if not can_add:
            raise PermissionDenied
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contato cadastrado com sucesso.')
            return redirect('app:contacts')
    elif can_add:
        form = ContactForm()

    contacts = [
        serialize_contact(contact)
        for contact in Contact.objects.select_related('sector', 'user').all()
    ]

    return render(request, 'app/contacts.html', {
        'contacts': contacts,
        'contact_form': form,
        'sectors': list(Sector.objects.values('id', 'name')),
        'users': [
            {'id': user.id, 'name': user.get_full_name() or user.username}
            for user in User.objects.order_by('username')
        ] if can_change else [],
        'can_change_contact': can_change,
        'can_delete_contact': request.user.has_perm('app.delete_contact'),
    })


def serialize_contact(contact):
    return {
        'id': contact.id,
        'user_id': contact.user_id,
        'name': contact.get_display_name(),
        'custom_name': contact.name,
        'number': contact.number or '',
        'sector_id': contact.sector_id,
        'sector': contact.sector.name if contact.sector else '',
        'machine': contact.machine or '',
    }


@login_required
@track_access(ServiceAccess.DASHBOARDS)
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
@track_access(ServiceAccess.DASHBOARDS)
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


@login_required
@permission_required('app.register_customers_suppliers', raise_exception=True)
@require_http_methods(['GET', 'POST'])
@track_access(ServiceAccess.CUSTOMERS_VENDORS)
def customers_vendors_view(request):
    entry = {'cnpj': '', 'ie': '', 'type': 'c'}
    data = None
    pending = []
    batch_error = None
    if request.method == 'POST':
        if 'customers_vendors' in request.POST:
            try:
                entries = json.loads(request.POST['customers_vendors'])
            except (ValueError, TypeError):
                entries = None
            if not isinstance(entries, list) or not entries:
                batch_error = 'Adicione pelo menos um CNPJ à lista de cadastros.'
            else:
                seen = set()
                for index, item in enumerate(entries, start=1):
                    try:
                        if not isinstance(item, dict):
                            raise ValueError('Cada cadastro deve informar CNPJ, inscrição estadual e tipo.')
                        normalized = sanitize_entry(item)
                        if normalized['cnpj'] in seen:
                            raise ValueError('Esse CNPJ está duplicado na lista!')
                        seen.add(normalized['cnpj'])
                    except ValueError as error:
                        batch_error = f'Cadastro {index}: {error}'
                        pending = [item for item in entries if isinstance(item, dict)]
                        break
        else:
            entry = {field: request.POST.get(field, '') for field in entry}
            entries = [entry]
        if batch_error is None:
            data = register_customers_vendors(entries)
            pending = [item for item, result in zip(entries, data['results'])
                       if result['status'] == 'error' and isinstance(item, dict)]
    return render(request, 'app/customers_vendors.html', {
        'entry': entry,
        'registration': data,
        'pending': pending,
        'batch_error': batch_error,
    })


def json_login_required(view):
    # Equivalente ao login_required, mas respondendo JSON para as chamadas da API
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'detail': 'Sessão expirada, faça login novamente.'}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def json_permission_required(perm):
    # Equivalente ao permission_required, mas respondendo JSON para as chamadas da API
    def decorator(view):
        @wraps(view)
        @json_login_required
        def wrapper(request, *args, **kwargs):
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


@require_http_methods(['POST', 'DELETE'])
def contact_update_api(request, contact_id):
    if request.method == 'DELETE':
        return contact_delete(request, contact_id)
    return contact_update(request, contact_id)


@json_permission_required('app.change_contact')
def contact_update(request, contact_id):
    contact = get_object_or_404(Contact.objects.select_related('sector', 'user'), id=contact_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = ContactForm(payload, instance=contact)
    if not form.is_valid():
        return form_errors_response(form)

    contact = form.save()
    return JsonResponse({'contact': serialize_contact(contact)})


@json_permission_required('app.delete_contact')
def contact_delete(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)
    contact.delete()
    return JsonResponse({'status': 'success'})


@login_required
@permission_required('app.view_toner', raise_exception=True)
@track_access(ServiceAccess.TONERS)
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
            'request': user.has_perm('app.request_toner'),
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
        toner = form.save(commit=False)
        toner.quantity = initial_quantity
        toner.save()
        # O estoque inicial entra como movimentação para o histórico ficar consistente
        if initial_quantity:
            TonerMovement.objects.create(
                toner=toner,
                type=TonerMovement.ENTRY,
                quantity=initial_quantity,
                reason='Estoque inicial',
                user=request.user,
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
    request_items = toner.request_items.select_related('request__user')
    return JsonResponse({
        'movements': [serialize_movement(movement) for movement in movements],
        'requests': [serialize_request_item(item) for item in request_items],
    })


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


@require_POST
@json_permission_required('app.request_toner')
def toner_requests_api(request):
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    try:
        toners = request_toners(payload.get('items'), request.user)
    except ValidationError as error:
        return JsonResponse({'detail': error.messages[0]}, status=400)
    # As falhas da integração saem como 503, não 502: a Cloudflare troca qualquer
    # 502 da origem pela página de erro dela, e a mensagem daqui se perderia
    except RuntimeError as error:
        return JsonResponse({'detail': str(error)}, status=503)
    except requests.RequestException:
        return JsonResponse({'detail': 'Não foi possível enviar a solicitação. Tente novamente mais tarde.'}, status=503)

    return JsonResponse({'toners': [serialize_toner(toner) for toner in toners]}, status=201)


@login_required
@require_http_methods(['GET'])
@track_access(ServiceAccess.NOTIFICATIONS)
def notifications_view(request):
    notifications = [serialize_notification(n) for n in visible_notifications(request.user)]
    return render(request, 'app/notifications.html', {
        'notifications': notifications,
    })


@require_http_methods(['GET'])
@json_login_required
def notifications_api(request):
    # Os alertas pedem só as não lidas; o mural pede todas com ?all=1
    if request.GET.get('all'):
        notifications = visible_notifications(request.user)
    else:
        notifications = unread_notifications(request.user)
    return JsonResponse({'notifications': [serialize_notification(n) for n in notifications]})


@require_POST
@json_login_required
def notification_read_api(request, notification_id):
    # Só marca como lida o que realmente foi entregue a este usuário
    notification = get_object_or_404(visible_notifications(request.user), id=notification_id)
    notification.read_by.add(request.user)
    notification.views += 1
    notification.save(update_fields=['views'])
    return JsonResponse({'status': 'success'})


@require_POST
@json_login_required
def notifications_read_all_api(request):
    request.user.read_notifications.add(*unread_notifications(request.user))
    return JsonResponse({'status': 'success'})


@require_http_methods(['POST', 'DELETE'])
@json_login_required
def home_layout_api(request):
    # Apagar o layout devolve a home à ordem dos acessos, com todos os cards
    if request.method == 'DELETE':
        HomeLayout.objects.filter(user=request.user).delete()
        return JsonResponse({'order': [service.key for service in ranked_services(request.user)]})

    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)
    try:
        save_layout(request.user, payload.get('order'), payload.get('hidden', []), payload.get('sizes', {}))
    except ValueError as error:
        return JsonResponse({'detail': str(error)}, status=400)
    return JsonResponse({'status': 'success'})



@login_required
@require_http_methods(['GET'])
@track_access(ServiceAccess.LIBRARY)
def library_view(request):
    user = request.user
    permissions = library_permissions(user)
    documents = list(visible_documents(user).prefetch_related('users', 'groups'))
    manages = permissions['add_document'] or permissions['change_document']

    return render(request, 'app/library.html', {
        'folders': [serialize_folder(folder) for folder in visible_folders(user, documents)],
        'documents': [serialize_document(document, user) for document in documents],
        'permissions': permissions,
        # A lista de quem pode receber só vai para quem escolhe os destinatários
        'recipients': recipient_choices() if manages else {'users': [], 'groups': []},
        'accept': ','.join(f'.{extension}' for extension in ALLOWED_EXTENSIONS),
        'max_file_size': MAX_FILE_SIZE,
    })


@login_required
@require_http_methods(['GET'])
def library_download_view(request, document_id):
    # Só baixa o que foi liberado para este usuário
    document = get_object_or_404(visible_documents(request.user), id=document_id)
    try:
        file = document.file.open('rb')
    except FileNotFoundError:
        raise Http404('Arquivo não encontrado.')
    LibraryDocument.objects.filter(pk=document.pk).update(downloads=F('downloads') + 1)
    return FileResponse(file, as_attachment=True, filename=document.file_name)


# A prévia do PDF vai num iframe da própria biblioteca, e só ela pode ser
# embutida: o resto do portal segue sem poder ir para dentro de um frame
@login_required
@require_http_methods(['GET'])
@xframe_options_sameorigin
@csp_override({'frame-ancestors': [CSP.SELF]})
def library_preview_view(request, document_id):
    document = get_object_or_404(visible_documents(request.user), id=document_id)
    kind = preview_kind(document.file_name)
    if kind is None:
        raise Http404('Este arquivo não tem prévia.')
    try:
        file = document.file.open('rb')
    except FileNotFoundError:
        raise Http404('Arquivo não encontrado.')

    if kind == 'text':
        with file:
            text = preview_text(file.read(TEXT_PREVIEW_BYTES))
        response = HttpResponse(text, content_type='text/plain; charset=utf-8')
    else:
        response = FileResponse(
            file, filename=document.file_name, content_type=PREVIEW_CONTENT_TYPES[file_extension(document.file_name)],
        )
    # O navegador mostra o arquivo como o tipo acima, sem tentar adivinhar outro
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    return response


@require_POST
@json_permission_required('app.add_libraryfolder')
def library_folders_api(request):
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = LibraryFolderForm(payload)
    if not form.is_valid():
        return form_errors_response(form)
    return JsonResponse({'folder': serialize_folder(form.save())}, status=201)


@require_http_methods(['POST', 'DELETE'])
def library_folder_api(request, folder_id):
    if request.method == 'DELETE':
        return library_folder_delete(request, folder_id)
    return library_folder_update(request, folder_id)


@json_permission_required('app.change_libraryfolder')
def library_folder_update(request, folder_id):
    folder = get_object_or_404(LibraryFolder, id=folder_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = LibraryFolderForm(payload, instance=folder)
    if not form.is_valid():
        return form_errors_response(form)
    return JsonResponse({'folder': serialize_folder(form.save())})


@json_permission_required('app.delete_libraryfolder')
def library_folder_delete(request, folder_id):
    folder = get_object_or_404(LibraryFolder, id=folder_id)
    # A pasta só sai vazia: apagar os documentos junto é fácil demais de fazer sem querer
    try:
        folder.delete()
    except ProtectedError:
        return JsonResponse(
            {'detail': 'A pasta ainda tem documentos. Mova ou exclua os documentos antes de excluí-la.'},
            status=400,
        )
    return JsonResponse({'status': 'success'})


@require_POST
@json_permission_required('app.add_librarydocument')
def library_documents_api(request):
    form = LibraryDocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return form_errors_response(form)

    with transaction.atomic():
        document = form.save(commit=False)
        document.created_by = request.user
        document.save()
        form.save_m2m()
    return JsonResponse({'document': serialize_document(document, request.user)}, status=201)


@require_http_methods(['POST', 'DELETE'])
def library_document_api(request, document_id):
    if request.method == 'DELETE':
        return library_document_delete(request, document_id)
    return library_document_update(request, document_id)


@json_permission_required('app.change_librarydocument')
def library_document_update(request, document_id):
    document = get_object_or_404(LibraryDocument, id=document_id)
    form = LibraryDocumentForm(request.POST, request.FILES, instance=document)
    if not form.is_valid():
        return form_errors_response(form)

    with transaction.atomic():
        document = form.save()
    return JsonResponse({'document': serialize_document(document, request.user)})


@json_permission_required('app.delete_librarydocument')
def library_document_delete(request, document_id):
    document = get_object_or_404(LibraryDocument, id=document_id)
    document.delete()
    return JsonResponse({'status': 'success'})
