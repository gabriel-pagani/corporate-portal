from app.models import Contact
from app.forms import LoginForm
from app.utils.dashboards.access import get_user_dashboards
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST


@login_required
def home_view(request):
    return render(request, 'app/home.html')


def login_view(request):
    form = LoginForm()
    return render(request, 'app/login.html', {
        'form': form,
        'form_action': reverse('app:login-done')
    })


def login_done(request):
    if not request.POST:
        raise Http404()

    form = LoginForm(request.POST)

    if form.is_valid():
        username = form.cleaned_data.get('username', '')
        password = form.cleaned_data.get('password', '')

        user = authenticate(
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)
            return redirect(reverse('app:home'))
        else:
            messages.error(request, 'Dados inválidos!')
    else:
        messages.error(request, 'Preencha todos os campos!')

    return render(request, 'app/login.html', {
        'form': form,
        'form_action': reverse('app:login-done')
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
