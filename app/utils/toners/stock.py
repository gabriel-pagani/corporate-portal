from django.db import transaction
from django.core.exceptions import ValidationError
from app.models import Toner, TonerMovement


def serialize_toner(toner):
    return {
        'id': toner.id,
        'name': toner.name,
        'location': toner.location,
        'observations': toner.observations,
        'quantity': toner.quantity,
        'minimum_quantity': toner.minimum_quantity,
        'is_low': toner.is_low,
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
