from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from app.models import Notification


def visible_notifications(user):
    now = timezone.now()
    through_users = Notification.users.through
    through_groups = Notification.groups.through

    # Sem usuários nem grupos a notificação vale para todos
    for_everyone = ~Exists(through_users.objects.filter(notification=OuterRef('pk'))) & ~Exists(
        through_groups.objects.filter(notification=OuterRef('pk'))
    )
    for_user = Exists(through_users.objects.filter(notification=OuterRef('pk'), user=user))
    for_groups = Exists(through_groups.objects.filter(notification=OuterRef('pk'), group__user=user))
    is_read = Exists(Notification.read_by.through.objects.filter(notification=OuterRef('pk'), user=user))

    return (
        Notification.objects
        .filter(is_active=True, start_at__lte=now)
        .filter(Q(end_at__isnull=True) | Q(end_at__gt=now))
        .filter(for_everyone | for_user | for_groups)
        .annotate(is_read=is_read)
        .select_related('created_by')
    )


def unread_notifications(user):
    return visible_notifications(user).filter(is_read=False).order_by('start_at')


def author_name(user):
    if user is None:
        return None
    return user.get_full_name() or user.username


def serialize_notification(notification):
    return {
        'id': notification.id,
        'title': notification.title,
        'message': notification.message,
        'level': notification.level,
        'level_display': notification.get_level_display(),
        'start_at': timezone.localtime(notification.start_at).strftime('%d/%m/%Y %H:%M'),
        'is_read': notification.is_read,
        'author': author_name(notification.created_by),
        'views': notification.views,
    }
