from django.db import transaction
from django.db.models import Exists, OuterRef
from django.core.exceptions import ValidationError
from app.models import Toner, TonerMovement


def toners_queryset():
    # A anotação evita uma consulta por linha ao montar a lista
    return Toner.objects.annotate(
        has_movements=Exists(TonerMovement.objects.filter(toner=OuterRef('pk')))
    )


def has_movements(toner):
    if not hasattr(toner, 'has_movements'):
        return toner.movements.exists()
    return toner.has_movements


def serialize_toner(toner):
    return {
        'id': toner.id,
        'name': toner.name,
        'location': toner.location,
        'observations': toner.observations,
        'quantity': toner.quantity,
        'minimum_quantity': toner.minimum_quantity,
        'is_low': toner.is_low,
        # O nome deixa de ser editável assim que o toner tem histórico
        'can_rename': not has_movements(toner),
    }


def serialize_movement(movement):
    user = movement.user
    return {
        'id': movement.id,
        'type': movement.type,
        'type_display': movement.get_type_display(),
        'quantity': movement.quantity,
        'reason': movement.reason,
        'user': (user.get_full_name() or user.username) if user else '',
        'created_at': movement.created_at.isoformat(),
    }


def register_movement(toner_id, type, quantity, reason='', user=None):
    # O lock na linha evita que duas movimentações simultâneas se sobrescrevam
    with transaction.atomic():
        toner = Toner.objects.select_for_update().get(pk=toner_id)

        if type == TonerMovement.EXIT:
            if quantity > toner.quantity:
                raise ValidationError(f'Estoque insuficiente: há apenas {toner.quantity} unidade(s).')
            toner.quantity -= quantity
        else:
            toner.quantity += quantity

        toner.save(update_fields=['quantity', 'updated_at'])
        movement = TonerMovement.objects.create(
            toner=toner, type=type, quantity=quantity, reason=reason, user=user,
        )

    return toner, movement
