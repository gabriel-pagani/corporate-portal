import pytest
from django.db import DatabaseError, transaction
from django.urls import NoReverseMatch, reverse

from expenses.history import money, snapshot
from expenses.models import Expense, ExpenseEvent, ImmutableRecord
from expenses.workflow import act
from tests.expenses_helpers import (  # noqa: F401
    catalog, control, employee, finance, media_root, openai, submitted,
)


@pytest.fixture(autouse=True)
def isolated_media(media_root):
    return media_root


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
def test_snapshot_formats(openai):
    expense = submitted(openai, employee())

    state = snapshot(expense)

    assert set(state) == {
        'status', 'status_display', 'employee', 'sector', 'cost_center', 'fields', 'items', 'reimbursed_total',
        'employee_note', 'last_note', 'photos', 'ai_reading', 'ai_alerts', 'version',
    }
    assert money('1234.5') == 'R$ 1.234,50' and money(None) == ''


@pytest.mark.django_db
def test_reviewers_see_only_the_history_on_the_screen(client, openai):
    # A auditoria de cada etapa é consultada no admin ou no banco, e não na tela
    expense = submitted(openai, employee(), note='Almoço')
    act(control(), expense.pk, 'approve', 'Conferido.', 1)
    client.force_login(finance())

    content = client.get(reverse('expenses:expenses')).content.decode()
    assert 'id="timeline"' in content
    assert 'Auditoria' not in content and 'id="audit' not in content

    timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
    assert [(event['action_display'], event['note']) for event in timeline] == [
        ('Nota enviada', 'Almoço'), ('Conferida', 'Conferido.'),
    ]
    for name in ('expense-history-api', 'expense-state-api', 'expense-compare-api'):
        with pytest.raises(NoReverseMatch):
            reverse(f'expenses:{name}', args=[expense.pk])
