from django.db import transaction
from django.db.models import Exists, OuterRef
from django.core.exceptions import ValidationError
from app.models import Toner, TonerMovement
from app.utils.toners.request import send_toner_request


def toners_queryset():
    # A anotação evita uma consulta por linha ao montar a lista
    return Toner.objects.select_related('location').annotate(
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
        'location': toner.location.name if toner.location else '',
        'location_id': toner.location_id,
        'observations': toner.observations,
        'quantity': toner.quantity,
        'minimum_quantity': toner.minimum_quantity,
        'is_low': toner.is_low,
        'requested_quantity': toner.requested_quantity,
        'expected_quantity': toner.expected_quantity,
        # O IDPRD só interessa ao RM; a tela precisa saber apenas se dá para solicitar
        'can_request': toner.idprd is not None,
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
            # A entrada é o recebimento do que foi solicitado; uma entrega parcial deixa o resto pendente
            toner.requested_quantity = max(0, toner.requested_quantity - quantity)

        toner.save(update_fields=['quantity', 'requested_quantity', 'updated_at'])
        movement = TonerMovement.objects.create(
            toner=toner, type=type, quantity=quantity, reason=reason, user=user,
        )

    return toner, movement


def parse_request_items(items):
    if not isinstance(items, list) or not items:
        raise ValidationError('Informe a quantidade de pelo menos um toner.')

    quantities = {}
    for item in items:
        try:
            toner_id = int(item['toner'])
            quantity = int(item['quantity'])
        except (KeyError, TypeError, ValueError):
            raise ValidationError('Solicitação inválida.')
        if quantity <= 0:
            raise ValidationError('Informe uma quantidade válida.')
        if toner_id in quantities:
            raise ValidationError('O mesmo toner aparece mais de uma vez na solicitação.')
        quantities[toner_id] = quantity

    return quantities


def request_toners(items):
    quantities = parse_request_items(items)
    toners = Toner.objects.in_bulk(quantities.keys())

    for toner_id in quantities:
        toner = toners.get(toner_id)
        if toner is None:
            raise ValidationError('Toner não encontrado.')
        if toner.idprd is None:
            raise ValidationError(f'O toner {toner.name} não tem o IDPRD do RM cadastrado.')

    send_toner_request([
        {'idprd': toners[toner_id].idprd, 'quantity': quantity}
        for toner_id, quantity in quantities.items()
    ])

    # Só conta como solicitado depois que o n8n aceitou o pedido: se o envio
    # falhar, o toner continua aparecendo como pendente de compra
    # A ordenação padrão junta o local por LEFT JOIN, que o FOR UPDATE não aceita
    with transaction.atomic():
        for toner in Toner.objects.select_for_update().filter(pk__in=quantities).order_by('pk'):
            toner.requested_quantity += quantities[toner.id]
            toner.save(update_fields=['requested_quantity', 'updated_at'])

    return toners_queryset().filter(pk__in=quantities)
