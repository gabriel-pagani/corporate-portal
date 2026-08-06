import json
from app.models import Contact
from app.forms import LoginForm
from app.utils.dashboards.access import get_user_dashboards
from app.utils.customer_vendor.auth import api_token_required
from app.utils.customer_vendor.registration import register_customers_vendors
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
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
