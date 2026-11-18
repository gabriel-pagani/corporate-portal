import pytest
from django.db import DatabaseError, connection, transaction
from django.urls import NoReverseMatch, reverse

from expenses.history import money, snapshot
from expenses.models import Expense, ExpenseEvent, ImmutableRecord
from expenses.workflow import act
from tests.expenses_helpers import (  # noqa: F401
    access_key, catalog, control, employee, finance, media_root, openai, submitted,
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


def mark_discarding(expense):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('expenses.discarding_expense', %s, true)", [str(expense.pk)])


@pytest.mark.django_db
def test_database_allows_only_the_discard_of_the_marked_submission(openai):
    first = submitted(openai, employee())
    second = submitted(openai, employee('outro', email='outro@empresa.com'), access_key=access_key(2))
    act(control(), second.pk, 'approve', '', 1)

    # A marcação vale para uma despesa só
    with pytest.raises(DatabaseError), transaction.atomic():
        mark_discarding(first)
        ExpenseEvent.objects.filter(expense=second).delete()
    # E só para o registro do envio: o da conferência continua sem sair
    with pytest.raises(DatabaseError), transaction.atomic():
        mark_discarding(second)
        ExpenseEvent.objects.filter(expense=second, action=ExpenseEvent.APPROVE_REVIEW).delete()
    # Alterar continua recusado, mesmo com a marcação
    with pytest.raises(DatabaseError), transaction.atomic():
        mark_discarding(first)
        ExpenseEvent.objects.filter(expense=first).update(note='alterado')
    # A marcação some com a transação
    with pytest.raises(DatabaseError), transaction.atomic():
        ExpenseEvent.objects.filter(expense=first).delete()

    with transaction.atomic():
        mark_discarding(first)
        ExpenseEvent.objects.filter(expense=first).delete()
    assert not first.events.exists() and second.events.count() == 2


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
