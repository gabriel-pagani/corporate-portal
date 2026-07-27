from app.models import Contact
from app.utils.dashboards.access import get_user_dashboards
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST


def contacts_view(request):
    data = [
        {
            'name': contact.get_display_name(),
            'number': contact.number or '',
            'sector': contact.sector.name if contact.sector else '',
            'machine': contact.machine or '',
        }
        for contact in Contact.objects.select_related('sector', 'user').all()
    ]

    return render(request, 'app/contacts.html', {
        'data': data
    })


@login_required
def dashboards_view(request):
    ...


@login_required
def dashboard_view(request, dashboard_id):
    ...


@login_required
@require_POST
def favorite_dashboard(request, dashboard_id):
    dashboard = get_object_or_404(get_user_dashboards(request.user), id=dashboard_id)
    user = request.user

    if user in dashboard.fav_by.all():
        dashboard.fav_by.remove(user)
        is_favorite = False
    else:
        dashboard.fav_by.add(user)
        is_favorite = True

    return JsonResponse({'status': 'success', 'is_favorite': is_favorite})
