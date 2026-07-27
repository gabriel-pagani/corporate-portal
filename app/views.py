from app.models import Contact
from django.shortcuts import render
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
    ...
