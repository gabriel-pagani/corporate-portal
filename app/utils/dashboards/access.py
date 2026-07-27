from django.db.models import Q
from app.models import Dashboard


def get_user_dashboards(user):
    if user.has_perm('app.view_all_dashboards'):
        return Dashboard.objects.all()

    return Dashboard.objects.filter(
        Q(user=user) | Q(groupdashboards__group__in=user.groups.all())
    ).distinct()
