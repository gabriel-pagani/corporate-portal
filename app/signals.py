from datetime import timedelta

from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Notification, Toner, User
from .utils import throttle


TONER_MANAGEMENT_PERMISSIONS = ('add_toner', 'change_toner', 'delete_toner')


# Os sinais valem para qualquer backend: a senha local e o LDAP contam para o
# mesmo teto, e o acerto por qualquer um dos dois zera a conta. Contar dentro de
# um backend só contaria o caminho dele — e o login por LDAP, que o backend
# local sempre recusa, viraria uma sequência de erros a cada acerto.
@receiver(user_login_failed)
def count_login_failure(sender, credentials, **kwargs):
    username = credentials.get('username')

    if username:
        throttle.login_failure(username)


@receiver(user_logged_in)
def clear_login_failures(sender, user, **kwargs):
    throttle.login_success(user.get_username())


@receiver(pre_save, sender=Toner)
def remember_toner_stock_state(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._was_low_stock = False
        return

    previous = sender.objects.filter(pk=instance.pk).values('quantity', 'minimum_quantity').first()
    instance._was_low_stock = (
        previous is not None
        and previous['quantity'] <= previous['minimum_quantity']
    )


@receiver(post_save, sender=Toner)
def notify_low_toner_stock(sender, instance, raw=False, **kwargs):
    if raw or instance._was_low_stock or not instance.is_low:
        return

    permissions = Permission.objects.filter(
        content_type__app_label='app',
        content_type__model='toner',
        codename__in=TONER_MANAGEMENT_PERMISSIONS,
    )
    recipients = User.objects.filter(is_active=True).filter(
        Q(is_superuser=True)
        | Q(user_permissions__in=permissions)
        | Q(groups__permissions__in=permissions)
    ).distinct()
    if not recipients.exists():
        return

    now = timezone.now()

    match instance.quantity:
        case 0:
            text = 'nenhuma unidade disponível'
        case 1:
            text = 'apenas 1 unidade disponível'
        case _:
            text = f'apenas {instance.quantity} unidades disponíveis'

    notification = Notification.objects.create(
        title='Estoque baixo',
        message=f'O toner {instance.name} está com {text}.',
        level=Notification.WARNING,
        start_at=now,
        end_at=now + timedelta(days=1),
    )
    notification.users.set(recipients)
