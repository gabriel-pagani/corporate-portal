"""A nova leitura da nota pela IA, pedida pela conferência quando a IA não leu no envio."""
import base64
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import requests
from django.contrib.staticfiles import finders
from django.urls import reverse

from expenses.models import Expense, ExpenseItem
from expenses.reading import FAILED, FAILED_ALERT, OK
from expenses.workflow import (
    REREAD_DONE, REREAD_DUPLICATE_ALERT, REREAD_FAILED, REREAD_KEPT_ITEMS_ALERT, REREAD_NOT_A_DOCUMENT_ALERT,
    REREAD_NOT_WITH_CONTROL, act, submit_expense,
)
from tests.expenses_helpers import (  # noqa: F401
    VALID_CNPJ, access_key, api_response, catalog, control, employee, finance, media_root, openai, photo,
    post_json, reading_payload, submitted,
)


@pytest.fixture(autouse=True)
def isolated_media(media_root):
    return media_root


def unread_expense(openai, user=None):
    """Uma despesa enviada com a IA fora do ar: entra sem leitura, com o alerta da falha."""
    openai.side_effect = requests.Timeout('demorou')
    expense = submit_expense(user or employee(), [photo()])
    openai.side_effect = None
    openai.reset_mock()
    return expense


def reread(client, expense, version=None):
    expense.refresh_from_db()
    return post_json(
        client, reverse('expenses:expense-reading-api', args=[expense.pk]),
        {'version': expense.version if version is None else version},
    )


def detail(client, expense):
    return client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']


@pytest.mark.django_db
def test_control_is_told_the_ai_did_not_read_the_note(client, openai):
    expense = unread_expense(openai)
    client.force_login(control())

    data = detail(client, expense)
    assert data['ai_status'] == FAILED and data['can']['reread'] is True
    # O aviso tem lugar próprio na tela: a falha não aparece também como alerta
    assert data['alerts'] == [] and data['alerts_count'] == 0

    row = client.get(reverse('expenses:expenses-api')).json()['expenses'][0]
    assert row['ai_unread'] is True and row['alerts_count'] == 0


@pytest.mark.django_db
def test_read_note_is_not_flagged(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())

    assert detail(client, expense)['can']['reread'] is False
    assert client.get(reverse('expenses:expenses-api')).json()['expenses'][0]['ai_unread'] is False


@pytest.mark.django_db
def test_reread_fills_the_note_once(client, openai, catalog):
    expense = unread_expense(openai)
    version = expense.version
    client.force_login(control())

    response = reread(client, expense)

    assert response.status_code == 200
    # Uma chamada só, com a foto guardada da nota
    assert openai.call_count == 1
    image = openai.call_args.kwargs['json']['input'][1]['content'][1]['image_url']
    assert image.startswith('data:image/jpeg;base64,') and base64.b64decode(image.split(',', 1)[1])
    expense.refresh_from_db()
    assert expense.cnpj == VALID_CNPJ and expense.number == '000123'
    assert expense.issue_date == date(2026, 11, 10) and expense.expense_type == catalog['types']['Alimentação']
    assert expense.items.count() == 2 and expense.reimbursed_total == Decimal('45.00')
    assert expense.version == version + 1 and expense.ai_alerts == []
    assert expense.ai_reading['status'] == OK
    assert [attempt['status'] for attempt in expense.ai_reading['failed_attempts']] == [FAILED]
    data = response.json()['expense']
    assert data['can']['reread'] is False and data['ai_status'] == OK

    # Leu: não lê de novo
    openai.reset_mock()
    again = reread(client, expense)
    assert again.status_code == 400 and again.json()['detail'] == REREAD_DONE
    assert not openai.called


@pytest.mark.django_db
def test_failed_reread_keeps_the_button_until_it_works(client, openai):
    expense = unread_expense(openai)
    version = expense.version
    client.force_login(control())

    openai.side_effect = requests.ConnectionError('fora do ar')
    response = reread(client, expense)

    assert response.status_code == 503 and response.json()['detail'] == REREAD_FAILED
    assert openai.call_count == 1
    expense.refresh_from_db()
    assert expense.version == version and expense.ai_alerts == [FAILED_ALERT]
    assert len(expense.ai_reading['failed_attempts']) == 1
    assert detail(client, expense)['can']['reread'] is True

    # Na segunda tentativa a IA volta
    openai.side_effect = None
    assert reread(client, expense).status_code == 200
    expense.refresh_from_db()
    assert expense.ai_reading['status'] == OK and len(expense.ai_reading['failed_attempts']) == 2


@pytest.mark.django_db
def test_reread_keeps_what_control_already_saved(client, openai):
    expense = unread_expense(openai)
    Expense.objects.filter(pk=expense.pk).update(number='999')
    ExpenseItem.objects.create(expense=expense, position=0, description='Almoço', quantity=1, amount=Decimal('30'))
    client.force_login(control())

    assert reread(client, expense).status_code == 200

    expense.refresh_from_db()
    assert expense.number == '999' and expense.cnpj == VALID_CNPJ
    assert [item.description for item in expense.items.all()] == ['Almoço']
    assert expense.ai_alerts == [REREAD_KEPT_ITEMS_ALERT]


@pytest.mark.django_db
def test_reread_of_a_note_already_in_the_portal_alerts_instead_of_refusing(client, openai):
    submitted(openai, employee('outro', email='outro@empresa.com'))
    expense = unread_expense(openai)
    client.force_login(control())

    assert reread(client, expense).status_code == 200

    expense.refresh_from_db()
    # A chave é única no portal: fica vazia, e a conferência é avisada
    assert expense.access_key == '' and expense.ai_alerts == [REREAD_DUPLICATE_ALERT]


@pytest.mark.django_db
def test_reread_of_a_duplicate_without_key_also_alerts(client, openai):
    submitted(openai, employee('outro', email='outro@empresa.com'), access_key=access_key(2))
    expense = unread_expense(openai)
    openai.return_value = api_response(reading_payload(access_key=None))
    client.force_login(control())

    assert reread(client, expense).status_code == 200

    expense.refresh_from_db()
    assert expense.ai_alerts == [REREAD_DUPLICATE_ALERT]


@pytest.mark.django_db
def test_reread_that_is_not_a_document_alerts(client, openai):
    expense = unread_expense(openai)
    openai.return_value = api_response(reading_payload(is_expense_document=False))
    client.force_login(control())

    assert reread(client, expense).status_code == 200

    expense.refresh_from_db()
    assert expense.ai_alerts == [REREAD_NOT_A_DOCUMENT_ALERT]


@pytest.mark.django_db
def test_only_control_asks_for_the_reading(client, openai):
    expense = unread_expense(openai)

    client.force_login(finance())
    assert reread(client, expense).status_code == 403
    assert detail(client, expense)['can']['reread'] is False
    client.force_login(expense.employee)
    assert reread(client, expense).status_code == 403
    assert not openai.called


@pytest.mark.django_db
def test_reread_only_while_with_control(client, openai):
    expense = unread_expense(openai)
    act(control(), expense.pk, 'request_correction', 'Foto cortada.', expense.version)
    client.force_login(Expense.objects.get().events.last().author)

    response = reread(client, expense)

    assert response.status_code == 400 and response.json()['detail'] == REREAD_NOT_WITH_CONTROL
    assert not openai.called


@pytest.mark.django_db
def test_reread_on_an_old_version_is_refused_before_the_ai(client, openai):
    expense = unread_expense(openai)
    client.force_login(control())

    response = reread(client, expense, version=expense.version + 5)

    assert response.status_code == 409 and not openai.called


def test_screen_has_the_unread_notice_and_the_reread_button():
    template = Path('expenses/templates/expenses/index.html').read_text(encoding='utf-8')
    assert 'id="ai-unread"' in template and 'id="reread-button"' in template
    assert 'A IA não leu esta nota' in template and 'data-reading-url=' in template
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    assert "urlFor('readingUrl'" in script and "' IA não leu'" in script
    # Um pedido por vez: o botão fica desligado enquanto a leitura não volta
    assert 'rereadButton.disabled = true' in script
