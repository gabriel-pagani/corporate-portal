from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from expenses.history import compare, money, snapshot, state_at
from expenses.models import Expense, ExpenseEvent, ImmutableRecord
from expenses.workflow import act, resubmit_photos
from tests.expenses_helpers import (  # noqa: F401
    catalog, control, employee, finance, media_root, openai, photo, submitted,
)


@pytest.fixture(autouse=True)
def isolated_media(media_root):
    return media_root


def edited_data(expense, **changes):
    data = {
        'cnpj': expense.cnpj, 'access_key': expense.access_key, 'number': expense.number,
        'issue_date': expense.issue_date.isoformat(), 'total': str(expense.total),
        'expense_type': expense.expense_type_id,
        'items': [
            {'id': item.pk, 'description': item.description, 'quantity': str(item.quantity),
             'amount': str(item.amount), 'non_reimbursable': item.non_reimbursable}
            for item in expense.items.all()
        ],
    }
    data.update(changes)
    return data


@pytest.mark.django_db
def test_every_stage_records_the_full_state(openai):
    user = employee()
    expense = submitted(openai, user, note='Almoço')
    act(control(), expense.pk, 'request_correction', 'Foto cortada.', 1)

    first, second = expense.events.all()
    assert first.action == ExpenseEvent.SUBMIT and second.action == ExpenseEvent.REQUEST_CORRECTION
    state = second.snapshot
    assert state['status'] == Expense.AWAITING_CORRECTION
    assert state['fields']['number'] == '000123' and state['fields']['expense_type'] == 'Alimentação'
    assert [item['description'] for item in state['items']] == ['Refeição executiva', 'Cerveja lata']
    assert state['reimbursed_total'] == '45.00'
    assert state['employee_note'] == 'Almoço' and state['last_note'] == 'Foto cortada.'
    assert [photo_['id'] for photo_ in state['photos']] == [expense.photos.get().pk]
    assert state['ai_reading']['status'] == 'ok' and state['ai_alerts'] == []
    assert second.author_name == 'controle' and second.author_role == ExpenseEvent.CONTROL
    assert second.status_before == Expense.AWAITING_REVIEW


@pytest.mark.django_db
def test_records_cannot_be_changed_or_deleted(openai):
    expense = submitted(openai, employee())
    event = expense.events.get()

    event.note = 'outra coisa'
    with pytest.raises(ImmutableRecord):
        event.save()
    with pytest.raises(ImmutableRecord):
        event.delete()

    # O gatilho do banco barra também o que passa por fora do model
    with pytest.raises(DatabaseError), transaction.atomic():
        ExpenseEvent.objects.filter(pk=event.pk).update(note='alterado')
    with pytest.raises(DatabaseError), transaction.atomic():
        ExpenseEvent.objects.filter(pk=event.pk).delete()

    event.refresh_from_db()
    assert event.note == ''


@pytest.mark.django_db
def test_state_at_any_moment(openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)
    first, second = expense.events.all()

    assert state_at(expense, first.created_at - timedelta(seconds=1)) is None
    assert state_at(expense, first.created_at) == first
    assert state_at(expense, second.created_at + timedelta(days=1)) == second


@pytest.mark.django_db
def test_compare_shows_what_changed_between_stages(openai, catalog):
    user = employee()
    expense = submitted(openai, user)
    meal, beer = expense.items.all()
    act(control(), expense.pk, 'request_correction', 'Refaça a foto.', 1, data=edited_data(
        expense, number='999', expense_type=catalog['types']['Hospedagem'].pk,
        items=[
            {'id': meal.pk, 'description': 'Refeição', 'quantity': '1', 'amount': '40.00', 'non_reimbursable': False},
            {'id': None, 'description': 'Água', 'quantity': '1', 'amount': '3.00', 'non_reimbursable': False},
        ],
    ))
    resubmit_photos(user, expense.pk, [photo(color='gray')])
    first, second, third = expense.events.all()

    changes = compare(first.snapshot, second.snapshot)
    assert changes['status'] == {'before': 'Aguardando conferência', 'after': 'Aguardando correção'}
    assert {change['label']: (change['before'], change['after']) for change in changes['fields']} == {
        'Número da nota': ('000123', '999'),
        'Tipo': ('Alimentação', 'Hospedagem'),
    }
    assert [item['description'] for item in changes['items']['added']] == ['Água']
    assert [item['description'] for item in changes['items']['removed']] == ['Cerveja lata']
    assert changes['items']['changed'] == [{
        'description': 'Refeição',
        'changes': [
            {'label': 'Descrição', 'before': 'Refeição executiva', 'after': 'Refeição'},
            {'label': 'Valor', 'before': 'R$ 45,00', 'after': 'R$ 40,00'},
        ],
    }]
    assert changes['reimbursed_total'] == {'label': 'Valor reembolsado', 'before': 'R$ 45,00', 'after': 'R$ 43,00'}
    assert changes['photos'] is None

    changes = compare(second.snapshot, third.snapshot)
    assert changes['fields'] == [] and changes['photos']['removed'] == [first.snapshot['photos'][0]['id']]
    assert changes['photos']['added'] == [third.snapshot['photos'][0]['id']]


@pytest.mark.django_db
def test_compare_of_the_same_stage_has_no_changes(openai):
    expense = submitted(openai, employee())
    event = expense.events.get()

    changes = compare(event.snapshot, event.snapshot)

    assert changes['status'] is None and changes['fields'] == [] and changes['photos'] is None
    assert changes['items'] == {'added': [], 'removed': [], 'changed': []}


@pytest.mark.django_db
def test_history_api_is_for_control_and_finance(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'approve', '', 1)
    url = reverse('expenses:expense-history-api', args=[expense.pk])

    client.force_login(user)
    assert client.get(url).status_code == 403

    client.force_login(finance())
    events = client.get(url).json()['events']
    assert [event['sequence'] for event in events] == [1, 2]
    assert events[1]['author_name'] == 'controle' and events[1]['role_display'] == 'Controle'
    assert events[0]['state']['photos'][0]['url'] == reverse(
        'expenses:photo', args=[events[0]['state']['photos'][0]['id']],
    )


@pytest.mark.django_db
def test_history_api_filters_a_period(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)
    client.force_login(finance())
    url = reverse('expenses:expense-history-api', args=[expense.pk])
    today = timezone.localdate()

    assert len(client.get(url, {'start': today.isoformat(), 'end': today.isoformat()}).json()['events']) == 2
    assert client.get(url, {'start': (today + timedelta(days=1)).isoformat()}).json()['events'] == []
    assert client.get(url, {'start': 'ontem'}).status_code == 400


@pytest.mark.django_db
def test_state_api_returns_the_note_at_the_moment(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'request_correction', 'Refaça.', 1)
    client.force_login(finance())
    url = reverse('expenses:expense-state-api', args=[expense.pk])
    first = expense.events.first()

    moment = timezone.localtime(first.created_at).replace(tzinfo=None)
    response = client.get(url, {'at': moment.isoformat()})
    assert response.status_code == 200 and response.json()['event']['sequence'] == 1

    response = client.get(url, {'at': (timezone.localtime() + timedelta(hours=1)).replace(tzinfo=None).isoformat()})
    assert response.json()['event']['sequence'] == 2
    assert response.json()['event']['state']['status_display'] == 'Aguardando correção'

    response = client.get(url, {'at': (moment - timedelta(days=1)).isoformat()})
    assert response.status_code == 404 and 'ainda não existia' in response.json()['detail']
    assert client.get(url, {'at': 'agora'}).status_code == 400


@pytest.mark.django_db
def test_compare_api(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)
    client.force_login(finance())
    url = reverse('expenses:expense-compare-api', args=[expense.pk])

    data = client.get(url, {'from': 1, 'to': 2}).json()
    assert data['from']['sequence'] == 1 and data['to']['sequence'] == 2
    assert data['changes']['status'] == {'before': 'Aguardando conferência', 'after': 'Aguardando validação'}
    assert client.get(url, {'from': 1, 'to': 9}).status_code == 404
    assert client.get(url, {'from': 'a'}).status_code == 400


@pytest.mark.django_db
def test_snapshot_formats(openai):
    expense = submitted(openai, employee())

    state = snapshot(expense)

    assert set(state) == {
        'status', 'status_display', 'employee', 'sector', 'cost_center', 'fields', 'items', 'reimbursed_total',
        'employee_note', 'last_note', 'photos', 'ai_reading', 'ai_alerts', 'version',
    }
    assert money('1234.5') == 'R$ 1.234,50' and money(None) == ''
