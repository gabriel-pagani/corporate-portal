from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from app.models import Notification


def unread_notifications(user):
    now = timezone.now()
    through_users = Notification.users.through
    through_groups = Notification.groups.through

    # Sem usuários nem grupos a notificação vale para todos
    for_everyone = ~Exists(through_users.objects.filter(notification=OuterRef('pk'))) & ~Exists(
        through_groups.objects.filter(notification=OuterRef('pk'))
    )
    for_user = Exists(through_users.objects.filter(notification=OuterRef('pk'), user=user))
    for_groups = Exists(through_groups.objects.filter(notification=OuterRef('pk'), group__user=user))
    already_read = Exists(Notification.read_by.through.objects.filter(notification=OuterRef('pk'), user=user))

    return (
        Notification.objects
        .filter(is_active=True, start_at__lte=now)
        .filter(Q(end_at__isnull=True) | Q(end_at__gt=now))
        .filter(for_everyone | for_user | for_groups)
        .exclude(already_read)
        .order_by('start_at')
    )


def serialize_notification(notification):
    return {
        'id': notification.id,
        'title': notification.title,
        'message': notification.message,
        'level': notification.level,
        'level_display': notification.get_level_display(),
        'start_at': timezone.localtime(notification.start_at).strftime('%d/%m/%Y %H:%M'),
    }
