import io
import json
import re
import smtplib
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.staticfiles import finders
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.urls import reverse
from PIL import Image

from app.models import CostCenter, Sector, ServiceAccess, User
from expenses.models import Expense, ExpenseEvent, ExpenseItem, ExpensePhoto
from expenses.reading import FAILED_ALERT
from expenses.roles import ROLE_CONFLICT, access
from expenses.workflow import (
    DUPLICATE_MESSAGE, NOT_A_DOCUMENT_MESSAGE, REPEATED_PHOTO_MESSAGE, SAME_PHOTO_TWICE_MESSAGE, act,
    resubmit_photos,
)
from tests.conftest import sign_in
from tests.expenses_helpers import (  # noqa: F401
    OTHER_CNPJ, VALID_CNPJ, access_key, api_response, catalog, control, employee, finance, make_user, media_root,
    openai, photo, post_json, reading_payload, same_photo, submitted,
)


@pytest.fixture(autouse=True)
def isolated_media(media_root):
    return media_root


def action_url(expense):
    return reverse('expenses:expense-action-api', args=[expense.pk])


def form_data(expense, **changes):
    """Os dados da nota como a tela do Controle manda, com as trocas pedidas."""
    expense.refresh_from_db()
    data = {
        'cnpj': expense.cnpj,
        'access_key': expense.access_key,
        'number': expense.number,
        'issue_date': expense.issue_date.isoformat() if expense.issue_date else '',
        'total': '' if expense.total is None else str(expense.total),
        'expense_type': expense.expense_type_id or '',
        'items': [
            {
                'id': item.pk, 'description': item.description, 'quantity': str(item.quantity),
                'amount': str(item.amount), 'non_reimbursable': item.non_reimbursable,
            }
            for item in expense.items.all()
        ],
    }
    data.update(changes)
    return data


def send_action(client, expense, action, note='', data=None, version=None):
    expense.refresh_from_db()
    payload = {'action': action, 'note': note, 'version': expense.version if version is None else version}
    if data is not None:
        payload['data'] = data
    return post_json(client, action_url(expense), payload)


def page_json(client, script_id, url=None):
    content = client.get(url or reverse('expenses:expenses')).content.decode()
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>', content, re.S)
    assert match, f'{script_id} ausente'
    return json.loads(match.group(1))


# ---------- Papéis ----------

@pytest.mark.django_db
def test_each_permission_gives_one_role():
    assert access(employee()).employee
    current = access(control())
    assert current.control and not current.finance and not current.employee
    current = access(finance())
    assert current.finance and not current.control


@pytest.mark.django_db
@pytest.mark.parametrize('codenames', [
    ('submit_expense', 'review_expense'),
    ('submit_expense', 'validate_expense'),
    ('review_expense', 'validate_expense'),
    ('submit_expense', 'manage_expense_rules'),
])
def test_forbidden_combinations_block_the_user(client, codenames):
    user = make_user(*codenames)

    assert access(user).conflict and not access(user).any_role
    client.force_login(user)
    response = client.get(reverse('expenses:expenses'))
    assert response.status_code == 403
    assert 'combinação de permissões das despesas que não é permitida' in response.content.decode()
    assert client.get(reverse('expenses:expenses-api')).status_code == 403


@pytest.mark.django_db
def test_conflict_through_a_group_also_blocks():
    group = Group.objects.create(name='Financeiro')
    group.permissions.add(Permission.objects.get(codename='validate_expense'))
    user = control()
    user.groups.add(group)

    assert access(User.objects.get(pk=user.pk)).conflict


@pytest.mark.django_db
def test_rules_manager_can_be_control_or_finance():
    current = access(make_user('review_expense', 'manage_expense_rules'))
    assert current.control and current.manage and not current.conflict
    current = access(make_user('validate_expense', 'manage_expense_rules', username='fin'))
    assert current.finance and current.manage and not current.conflict


@pytest.mark.django_db
def test_superuser_is_control_and_finance_but_never_submits():
    current = access(User.objects.create_superuser(username='admin', password='senha'))

    assert current.control and current.finance and current.manage
    assert not current.employee and not current.conflict


@pytest.mark.django_db
def test_page_requires_login_and_a_role(client):
    response = client.get(reverse('expenses:expenses'))
    assert response.status_code == 302 and reverse('app:login') in response.url

    client.force_login(make_user())
    assert client.get(reverse('expenses:expenses')).status_code == 403
    # Só gerenciar as regras não dá papel no fluxo
    client.force_login(make_user('manage_expense_rules', username='gestor'))
    assert client.get(reverse('expenses:expenses')).status_code == 403


@pytest.mark.django_db
def test_each_screen_has_its_own_route(client, openai):
    user = employee()
    expense = submitted(openai, user)
    assert reverse('expenses:expense-add') == '/expenses/add/'
    assert reverse('expenses:expense', args=[expense.pk]) == f'/expenses/{expense.pk}/'

    client.force_login(user)
    for url in (reverse('expenses:expense-add'), reverse('expenses:expense', args=[expense.pk])):
        content = client.get(url).content.decode()
        assert 'id="list-view"' in content and 'id="detail-view"' in content
    # Os links entre as telas são rotas, e não âncoras no endereço
    content = client.get(reverse('expenses:expenses')).content.decode()
    assert 'href="#' not in content
    assert 'href="/expenses/add/" data-route' in content and 'data-detail-url="/expenses/0/"' in content
    # Sem a barra no fim, o Django leva para a rota com a barra
    response = client.get(f'/expenses/{expense.pk}')
    assert response.status_code == 301 and response.url == f'/expenses/{expense.pk}/'


@pytest.mark.django_db
def test_logo_reloads_the_expenses_for_the_employee(client, openai):
    user = employee()
    expense = submitted(openai, user)
    client.force_login(user)
    # Em qualquer tela, a logo do funcionário recarrega a lista de despesas, sem trocar a rota pelo JS
    for url in (reverse('expenses:expenses'), reverse('expenses:expense', args=[expense.pk])):
        content = client.get(url).content.decode()
        assert '<a href="/expenses/" id="logo-link">' in content and 'title="Atualizar as despesas"' in content

    # Quem confere ou valida volta ao menu principal pela logo
    for reviewer in (control(), finance()):
        client.force_login(reviewer)
        content = client.get(reverse('expenses:expenses')).content.decode()
        assert f'<a href="{reverse("app:home")}" id="logo-link">' in content


@pytest.mark.django_db
def test_routes_respect_who_sees_the_expense(client, openai):
    owner = employee()
    expense = submitted(openai, owner)
    url = reverse('expenses:expense', args=[expense.pk])

    client.force_login(employee(username='outro', email='outro@empresa.com'))
    assert client.get(url).status_code == 404
    assert client.get(reverse('expenses:expense', args=[expense.pk + 100])).status_code == 404

    # Quem confere vê todas as despesas, mas não tem a tela de envio
    client.force_login(control())
    assert client.get(url).status_code == 200
    assert client.get(reverse('expenses:expense-add')).status_code == 403


def test_employee_list_labels_the_value_to_reimburse():
    # A linha mostra o valor reembolsável, e o rótulo diz isso, para não passar pelo total da nota
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    employee_row = re.search(
        r"\] : \[\n\s+element\('strong', \{ text: expense\.reimbursed_total \}\),\n"
        r"\s+element\('span', \{ className: 'row-label', text: '([^']+)' \}\),", script,
    )
    assert employee_row.group(1) == 'valor a reembolsar'
    assert "'valor da nota'" not in script
    # O rótulo quebra em duas linhas, para a situação caber ao lado do título no celular
    style = Path(finders.find('expenses/css/expenses.css')).read_text(encoding='utf-8')
    assert re.search(r'\.expense-row \.row-label \{[^}]*max-width: 6em', style)


def test_employee_list_abbreviates_the_long_statuses():
    # A situação abreviada cabe ao lado do título e do valor no celular
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    short = dict(re.findall(r"(\w): '([^']+)'", re.search(r'const shortStatus = \{(.*?)\};', script).group(1)))
    assert short == {'C': 'Ag. conferência', 'S': 'Ag. correção', 'E': 'Ag. explicação', 'V': 'Ag. validação'}
    # Cada abreviação corresponde à situação que existe, e as curtas ficam por inteiro
    labels = dict(Expense.STATUS)
    assert all(labels[code].replace('Aguardando', 'Ag.') == text for code, text in short.items())
    assert set(labels) - set(short) == {Expense.APPROVED, Expense.REJECTED}
    # Só na lista do funcionário, com o nome inteiro na dica do selo
    assert 'statusBadge(expense.status, shortStatus[expense.status], expense.status_display)' in script


@pytest.mark.django_db
def test_reviewer_details_are_titled_as_the_expense_data(client):
    client.force_login(control())
    content = client.get(reverse('expenses:expenses')).content.decode()
    card = re.search(r'<div class="card" id="detail-meta-card">(.*?)<dl', content, re.S).group(1)
    assert '<h3>Dados da despesa</h3>' in card
    # Uma linha sutil entre os dados e a observação do funcionário
    style = Path(finders.find('expenses/css/expenses.css')).read_text(encoding='utf-8')
    assert re.search(r'\n\.employee-note \{[^}]*border-top: 1px solid #f0f0f0', style)


def test_reviewer_details_leave_the_reimbursed_value_to_the_items():
    # O valor reembolsado já aparece na seção dos itens; os dados de quem enviou não o repetem
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    details = re.search(r'function renderMeta\(expense\) \{(.*?)\n    \}\n', script, re.S).group(1)
    assert 'Valor reembolsado' not in details and "'Setor'" not in details
    # Quem enviou, o centro de custo e, depois, quando
    positions = [details.index(f"'{label}'") for label in ('Funcionário', 'Centro de custo', 'Enviada em')]
    assert positions == sorted(positions)


def test_employee_summary_leaves_out_the_note_total():
    # O funcionário vê o que vai receber; o total da nota poderia passar por esse valor
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    summary = re.search(r'function renderEmployeeSummary\(expense\) \{(.*?)\n    \}\n', script, re.S).group(1)
    assert 'Valor total da nota' not in summary
    for label in ('Valor a reembolsar (previsto)', 'Valor reembolsado', 'Tipo', 'Número', 'Data',
                  'Emitente', 'Enviada em', 'Sua observação'):
        assert f"'{label}'" in summary
    # Dentro dos dados da nota, o número e a data dispensam o "da nota"
    assert 'Número da nota' not in summary and 'Data da nota' not in summary
    assert 'CNPJ do emitente' not in summary


@pytest.mark.django_db
def test_list_names_the_expenses_and_keeps_the_note_inside(client):
    client.force_login(employee())
    content = client.get(reverse('expenses:expenses')).content.decode()
    # A lista do funcionário começa nos filtros, sem título
    assert 'Nenhuma despesa por aqui.' in content and 'id="status-chips"' in content
    assert 'Minhas despesas' not in content
    # Dentro da despesa, o documento continua sendo a nota
    assert 'Enviar nota' in content and 'Fotos da nota' in content and 'Dados da nota' in content
    # No formulário dos dados da nota, o número e a data dispensam o "da nota"
    assert '<label for="field-number">Número</label>' in content
    assert '<label for="field-issue-date">Data</label>' in content
    assert '<label for="field-cnpj">Emitente</label>' in content
    assert 'Minhas notas' not in content

    client.force_login(control())
    content = client.get(reverse('expenses:expenses')).content.decode()
    assert 'Todas as despesas' in content and 'Todas as notas' not in content


@pytest.mark.django_db
def test_page_counts_the_access_and_tells_the_role(client, catalog):
    user = control()
    client.force_login(user)

    assert page_json(client, 'expenses-access') == {'employee': False, 'control': True, 'finance': False}
    assert [item['name'] for item in page_json(client, 'expenses-types')] == ['Alimentação', 'Combustível', 'Hospedagem']
    assert ServiceAccess.objects.get(user=user, service=ServiceAccess.EXPENSES).count == 2


@pytest.mark.django_db
def test_employee_page_has_the_mobile_photo_inputs(client):
    client.force_login(employee())

    content = client.get(reverse('expenses:expenses')).content.decode()
    assert 'capture="environment"' in content
    assert 'accept="image/jpeg,image/png,image/webp"' in content
    assert page_json(client, 'expenses-limits')['max_photos'] == 3
    assert page_json(client, 'expenses-limits')['max_size'] == 20 * 1024 * 1024


# ---------- Envio ----------

@pytest.mark.django_db
def test_employee_submits_and_the_ai_fills_the_form(client, openai, catalog):
    sector = Sector.objects.create(name='Comercial')
    cost_center = CostCenter.objects.create(code='100', name='Vendas')
    user = employee(sector=sector, cost_center=cost_center)
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()], 'note': 'Almoço com cliente'})

    assert response.status_code == 201
    expense = Expense.objects.get()
    assert expense.status == Expense.AWAITING_REVIEW
    assert expense.employee == user and expense.sector == sector and expense.cost_center == cost_center
    assert expense.cnpj == VALID_CNPJ and expense.access_key == access_key() and expense.number == '000123'
    assert expense.total == Decimal('50.00') and expense.expense_type == catalog['types']['Alimentação']
    assert expense.employee_note == 'Almoço com cliente'
    # A cerveja foi marcada pela IA: o valor reembolsado é só a refeição
    assert expense.reimbursed_total == Decimal('45.00')
    assert [item.ai_group for item in expense.items.all()] == ['', 'Bebida alcoólica']
    assert expense.ai_reading['status'] == 'ok'

    event = expense.events.get()
    assert (event.sequence, event.action, event.status_before, event.status_after) == (
        1, ExpenseEvent.SUBMIT, '', Expense.AWAITING_REVIEW,
    )
    assert event.author == user and event.author_role == ExpenseEvent.EMPLOYEE and event.note == 'Almoço com cliente'
    assert event.snapshot['ai_reading'] == expense.ai_reading
    assert response.json()['expense']['id'] == expense.pk


@pytest.mark.django_db
def test_photos_are_stored_as_normalized_jpeg(openai):
    user = employee()
    expense = submitted(openai, user, photos=[photo('foto.png', size=(4000, 2000), fmt='PNG', content_type='image/png')])

    stored = expense.photos.get()
    with stored.file.open('rb') as file:
        image = Image.open(io.BytesIO(file.read()))
        assert image.format == 'JPEG'
        assert max(image.size) == 3000
    # A IA recebeu uma cópia menor
    sent = openai.call_args[1]['json']['input'][1]['content'][1]['image_url']
    assert sent.startswith('data:image/jpeg;base64,')
    assert stored.round == 1 and stored.replaced_at is None and len(stored.sha256) == 64


@pytest.mark.django_db
def test_submission_limits(client, openai, monkeypatch):
    client.force_login(employee())
    url = reverse('expenses:expenses-api')

    response = client.post(url, {'note': 'sem foto'})
    assert response.status_code == 400 and 'ao menos uma foto' in response.json()['detail']

    response = client.post(url, {'photos': [photo(), photo(), photo(), photo()]})
    assert response.status_code == 400 and 'no máximo 3 fotos' in response.json()['detail']

    pdf = SimpleUploadedFile('nota.pdf', b'%PDF-1.4 nota', content_type='application/pdf')
    response = client.post(url, {'photos': [pdf]})
    assert response.status_code == 400 and 'JPEG, PNG ou WEBP' in response.json()['detail']

    monkeypatch.setattr('expenses.photos.MAX_PHOTO_SIZE', 100)
    response = client.post(url, {'photos': [photo()]})
    assert response.status_code == 400 and 'Cada foto pode ter até' in response.json()['detail']

    assert not Expense.objects.exists()
    openai.assert_not_called()


@pytest.mark.django_db
def test_twenty_megabytes_is_the_limit_per_photo():
    from expenses.photos import MAX_PHOTO_SIZE, MAX_PHOTOS

    assert MAX_PHOTO_SIZE == 20 * 1024 * 1024 and MAX_PHOTOS == 3


@pytest.mark.django_db
def test_failed_ai_still_sends_the_note_to_control(client, openai):
    import requests

    openai.side_effect = requests.Timeout('demorou')
    client.force_login(employee())

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 201
    expense = Expense.objects.get()
    # A IA não devolve a nota ao funcionário: o formulário segue vazio para o Controle
    assert expense.status == Expense.AWAITING_REVIEW
    assert expense.cnpj == '' and expense.total is None and not expense.items.exists()
    assert expense.ai_alerts == [FAILED_ALERT]


@pytest.mark.django_db
def test_access_key_already_sent_is_refused(client, openai):
    user = employee()
    first = submitted(openai, user)
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == DUPLICATE_MESSAGE
    assert list(Expense.objects.all()) == [first]
    assert ExpensePhoto.objects.count() == 1


@pytest.mark.django_db
def test_photo_that_is_not_an_invoice_or_receipt_is_refused(client, openai, media_root):
    openai.return_value = api_response(reading_payload(is_expense_document=False))
    user = employee()
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == NOT_A_DOCUMENT_MESSAGE
    # Nada fica gravado: nem a despesa, nem as fotos, nem o histórico, nem o e-mail
    assert not Expense.objects.exists() and not ExpensePhoto.objects.exists()
    assert not ExpenseEvent.objects.exists() and mail.outbox == []
    assert not [path for path in Path(media_root).rglob('*') if path.is_file()]


@pytest.mark.django_db
def test_without_the_ai_the_photo_is_not_judged_and_the_expense_goes_in(client, openai, settings):
    # Sem a análise ninguém disse que não é documento: a conferência vê as fotos
    settings.OPENAI_API_KEY = ''
    user = employee()
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 201 and Expense.objects.count() == 1


@pytest.mark.django_db
def test_photo_already_sent_is_refused_without_asking_the_ai(client, openai):
    user = employee()
    sent = photo()
    first = submitted(openai, user, photos=[sent], access_key=None)
    openai.reset_mock()
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [same_photo(sent, 'outro-nome.jpg')]})

    assert response.status_code == 400 and response.json()['detail'] == REPEATED_PHOTO_MESSAGE
    assert not openai.called
    assert list(Expense.objects.all()) == [first] and ExpensePhoto.objects.count() == 1


@pytest.mark.django_db
def test_photo_sent_by_another_employee_is_also_refused(client, openai):
    sent = photo()
    submitted(openai, employee(), photos=[sent], access_key=None)
    other = employee('outro', email='outro@empresa.com')
    client.force_login(other)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo(), same_photo(sent)]})

    assert response.status_code == 400 and response.json()['detail'] == REPEATED_PHOTO_MESSAGE
    assert not Expense.objects.filter(employee=other).exists()


@pytest.mark.django_db
def test_same_image_in_another_file_is_refused(client, openai):
    # Mesmos pixels, arquivo diferente (outro formato): a imagem regravada é a mesma
    image = Image.new('RGB', (400, 600), 'white')
    image.paste((10, 200, 30), (0, 0, 80, 80))
    files = []
    for fmt, content_type in (('PNG', 'image/png'), ('WEBP', 'image/webp')):
        buffer = io.BytesIO()
        image.save(buffer, fmt, **({'lossless': True} if fmt == 'WEBP' else {}))
        files.append(SimpleUploadedFile(f'nota.{fmt.lower()}', buffer.getvalue(), content_type=content_type))
    user = employee()
    submitted(openai, user, photos=[files[0]], access_key=None)
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [files[1]]})

    assert response.status_code == 400 and response.json()['detail'] == REPEATED_PHOTO_MESSAGE


@pytest.mark.django_db
def test_same_photo_twice_in_one_submission_is_refused(client, openai):
    client.force_login(employee())
    chosen = photo()

    response = client.post(reverse('expenses:expenses-api'), {'photos': [chosen, same_photo(chosen)]})

    assert response.status_code == 400 and response.json()['detail'] == SAME_PHOTO_TWICE_MESSAGE
    assert not openai.called and not Expense.objects.exists()


@pytest.mark.django_db
def test_photo_of_a_discarded_expense_can_be_sent_again(client, openai):
    user = employee()
    sent = photo()
    expense = submitted(openai, user, photos=[sent])
    client.force_login(user)
    assert client.delete(reverse('expenses:expense-api', args=[expense.pk])).status_code == 200

    response = client.post(reverse('expenses:expenses-api'), {'photos': [same_photo(sent)]})

    assert response.status_code == 201


@pytest.mark.django_db
def test_resubmit_keeps_photos_of_the_same_expense_but_refuses_others(openai):
    user = employee()
    kept, other = photo(), photo()
    submitted(openai, employee('outro', email='outro@empresa.com'), photos=[other], access_key=None, number='900')
    expense = submitted(openai, user, photos=[kept])
    act(control(), expense.pk, 'request_correction', 'Falta o verso.', expense.version)

    with pytest.raises(ValidationError) as error:
        resubmit_photos(user, expense.pk, [same_photo(other)])
    assert error.value.messages == [REPEATED_PHOTO_MESSAGE]

    # A correção pediu só o verso: a foto que já era desta despesa volta junto
    resubmit_photos(user, expense.pk, [same_photo(kept), photo()])
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW
    assert expense.photos.filter(replaced_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_access_key_of_a_rejected_note_is_also_refused(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'reject', 'Nota de outra empresa', expense.version)
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == DUPLICATE_MESSAGE


@pytest.mark.django_db
def test_notes_without_access_key_collide_only_on_the_same_cnpj_number_and_date(openai):
    user = employee()
    submitted(openai, user, access_key=None)
    submitted(openai, user, access_key=None, number='000124')
    submitted(openai, user, access_key=None, issue_date='2026-11-11')
    submitted(openai, user, access_key=None, cnpj=OTHER_CNPJ)

    assert Expense.objects.filter(access_key='').count() == 4


@pytest.mark.django_db
def test_same_cnpj_number_and_date_is_refused_when_the_ai_misses_the_key(client, openai):
    # Outra foto da mesma nota: a IA não leu a chave desta vez, e o número veio sem os zeros
    user = employee()
    first = submitted(openai, user)
    openai.return_value = api_response(reading_payload(access_key=None, number='123'))
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == DUPLICATE_MESSAGE
    assert list(Expense.objects.all()) == [first]


@pytest.mark.django_db
def test_same_cnpj_number_and_date_counts_against_what_control_corrected(client, openai):
    user = employee()
    first = submitted(openai, user, access_key=None, number=None)
    act(control(), first.pk, 'approve', '', first.version, data=form_data(first, number='555'))
    openai.return_value = api_response(reading_payload(access_key=None, number='555'))
    client.force_login(user)

    response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == DUPLICATE_MESSAGE


@pytest.mark.django_db
def test_different_access_keys_are_different_notes_even_with_the_same_number(openai):
    # Mesmo CNPJ, número e data, outra série: as chaves dizem que são notas diferentes
    user = employee()
    submitted(openai, user)
    submitted(openai, user, access_key=access_key(2))

    assert Expense.objects.count() == 2


@pytest.mark.django_db
def test_resubmitted_photos_that_are_not_an_invoice_or_receipt_are_refused(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'request_correction', 'Foto cortada.', expense.version)
    openai.return_value = api_response(reading_payload(is_expense_document=False))
    client.force_login(user)

    response = client.post(reverse('expenses:expense-photos-api', args=[expense.pk]), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == NOT_A_DOCUMENT_MESSAGE
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_CORRECTION and expense.photos.count() == 1


@pytest.mark.django_db
def test_resubmitted_photos_of_another_expense_note_are_refused(client, openai):
    user = employee()
    submitted(openai, user, access_key=None, number='900')
    expense = submitted(openai, user, access_key=access_key(2))
    act(control(), expense.pk, 'request_correction', 'Foto cortada.', expense.version)
    openai.return_value = api_response(reading_payload(access_key=None, number='900'))
    client.force_login(user)

    response = client.post(reverse('expenses:expense-photos-api', args=[expense.pk]), {'photos': [photo()]})

    assert response.status_code == 400 and response.json()['detail'] == DUPLICATE_MESSAGE


@pytest.mark.django_db
def test_resubmit_is_refused_before_the_ai_when_the_expense_is_not_waiting(client, openai):
    user = employee()
    expense = submitted(openai, user)
    openai.reset_mock()
    client.force_login(user)

    response = client.post(reverse('expenses:expense-photos-api', args=[expense.pk]), {'photos': [photo()]})

    assert response.status_code == 400 and not openai.called


@pytest.mark.django_db
def test_only_the_employee_submits(client, openai):
    for user in (control(), finance(), User.objects.create_superuser(username='admin', password='senha')):
        if user.is_superuser:
            sign_in(client, user)
        else:
            client.force_login(user)
        response = client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})
        assert response.status_code == 403
    assert not Expense.objects.exists()


# ---------- Quem vê o quê ----------

@pytest.mark.django_db
def test_employee_sees_only_his_notes(client, openai):
    ana = employee()
    bruno = employee(username='bruno', email='bruno@empresa.com')
    mine = submitted(openai, ana, access_key=access_key(1))
    other = submitted(openai, bruno, access_key=access_key(2))
    client.force_login(ana)

    listed = client.get(reverse('expenses:expenses-api')).json()
    assert [item['id'] for item in listed['expenses']] == [mine.pk]
    assert 'employee' not in listed['expenses'][0]
    assert client.get(reverse('expenses:expense-api', args=[other.pk])).status_code == 404
    other_photo = other.photos.get()
    assert client.get(reverse('expenses:photo', args=[other_photo.pk])).status_code == 404
    assert client.get(reverse('expenses:photo', args=[mine.photos.get().pk])).status_code == 200


@pytest.mark.django_db
def test_employee_does_not_see_the_ai_alerts(client, openai):
    user = employee()
    expense = submitted(openai, user, alerts=['Falta o CNPJ da empresa.'])
    client.force_login(user)

    data = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']
    assert 'alerts' not in data
    assert data['can'] == {'edit': False, 'act': False, 'resubmit': False, 'discard': True, 'reread': False}


@pytest.mark.django_db
def test_control_and_finance_see_every_note(client, openai):
    first = submitted(openai, employee(), access_key=access_key(1))
    second = submitted(openai, employee(username='bruno', email='b@empresa.com'), access_key=access_key(2))

    for user in (control(), finance()):
        client.force_login(user)
        listed = client.get(reverse('expenses:expenses-api'), {'scope': 'all'}).json()
        assert {item['id'] for item in listed['expenses']} == {first.pk, second.pk}
        assert listed['expenses'][0]['employee']


@pytest.mark.django_db
def test_reviewer_list_shows_the_employee_the_cost_center_and_the_date(client, openai):
    sales = CostCenter.objects.create(code='100', name='Vendas')
    user = employee(cost_center=sales)
    expense = submitted(openai, user)
    # O funcionário mudou de centro de custo depois do envio: a lista mostra o do envio
    user.cost_center = CostCenter.objects.create(code='200', name='Obras')
    user.save()

    client.force_login(control())
    row = client.get(reverse('expenses:expenses-api'), {'scope': 'all'}).json()['expenses'][0]
    assert row['id'] == expense.pk and row['employee'] == 'Ana Silva' and row['cost_center'] == str(sales)
    detail = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']
    assert detail['cost_center'] == str(sales)

    client.force_login(user)
    assert 'cost_center' not in client.get(reverse('expenses:expenses-api')).json()['expenses'][0]

    # Na linha: quem enviou, o centro de custo e a data; o tipo e o número ficam na despesa
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    meta = re.search(r'const meta = reviewer \? \[(.*?)\]', script, re.S).group(1)
    assert [line.strip() for line in meta.strip().splitlines()] == [
        'expense.employee,', 'expense.cost_center,', '`Enviada em ${expense.created_at}`,',
    ]


@pytest.mark.django_db
def test_queue_shows_what_waits_for_each_role(client, openai):
    user = employee()
    waiting_review = submitted(openai, user, access_key=access_key(1))
    waiting_validation = submitted(openai, user, access_key=access_key(2))
    act(control(), waiting_validation.pk, 'approve', '', waiting_validation.version)

    client.force_login(User.objects.get(username='controle'))
    queue = client.get(reverse('expenses:expenses-api'), {'scope': 'queue'}).json()
    assert [item['id'] for item in queue['expenses']] == [waiting_review.pk] and queue['queue_count'] == 1

    client.force_login(finance())
    queue = client.get(reverse('expenses:expenses-api'), {'scope': 'queue'}).json()
    assert [item['id'] for item in queue['expenses']] == [waiting_validation.pk]


@pytest.mark.django_db
def test_list_filters_by_status_and_search(client, openai):
    user = employee()
    # Números que não aparecem no CNPJ: a busca também procura nele
    first = submitted(openai, user, access_key=access_key(1), number='987')
    submitted(openai, user, access_key=access_key(2), number='654')
    act(control(), first.pk, 'reject', 'Fora da política', first.version)
    client.force_login(User.objects.get(username='controle'))
    url = reverse('expenses:expenses-api')

    assert [item['id'] for item in client.get(url, {'status': 'R'}).json()['expenses']] == [first.pk]
    assert [item['number'] for item in client.get(url, {'q': '654'}).json()['expenses']] == ['654']
    assert len(client.get(url, {'q': '11.222.333'}).json()['expenses']) == 2
    assert len(client.get(url, {'q': 'Ana'}).json()['expenses']) == 2


# ---------- Conferência do Controle ----------

@pytest.mark.django_db
def test_control_edits_any_field_and_the_items(client, openai, catalog):
    expense = submitted(openai, employee())
    meal, beer = expense.items.all()
    client.force_login(control())

    data = form_data(
        expense,
        cnpj='11.444.777/0001-61', number='999', issue_date='2026-11-01', total='60.00',
        expense_type=catalog['types']['Hospedagem'].pk,
        items=[
            {'id': meal.pk, 'description': 'Refeição', 'quantity': '2', 'amount': '50.00', 'non_reimbursable': False},
            {'id': None, 'description': 'Taxa de serviço', 'quantity': '1', 'amount': '5.00', 'non_reimbursable': False},
        ],
    )
    response = send_action(client, expense, 'request_correction', 'Envie a foto do verso.', data)

    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.cnpj == OTHER_CNPJ and expense.number == '999' and expense.total == Decimal('60.00')
    assert expense.expense_type == catalog['types']['Hospedagem']
    items = list(expense.items.all())
    assert [(item.description, item.amount) for item in items] == [('Refeição', Decimal('50.00')), ('Taxa de serviço', Decimal('5.00'))]
    assert items[0].pk == meal.pk and not ExpenseItem.objects.filter(pk=beer.pk).exists()
    assert expense.reimbursed_total == Decimal('55.00')


@pytest.mark.django_db
def test_non_reimbursable_items_stay_out_of_the_value(client, openai):
    expense = submitted(openai, employee())
    meal, beer = expense.items.all()
    client.force_login(control())

    # O Controle tem a última palavra: desmarca a cerveja e marca a refeição
    data = form_data(expense)
    data['items'][0]['non_reimbursable'] = True
    data['items'][1]['non_reimbursable'] = False
    send_action(client, expense, 'approve', '', data)

    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_VALIDATION
    assert expense.reimbursed_total == Decimal('5.00')
    # O sinal da IA continua no item
    assert ExpenseItem.objects.get(pk=beer.pk).ai_group == 'Bebida alcoólica'


@pytest.mark.django_db
@pytest.mark.parametrize('changes, field, message', [
    ({'cnpj': '11222333000182'}, 'cnpj', 'CNPJ inválido'),
    ({'access_key': '1234'}, 'access_key', 'Chave de acesso inválida'),
    ({'issue_date': '2999-01-01'}, 'issue_date', 'não pode ser futura'),
    ({'total': '-1'}, 'total', ''),
    ({'expense_type': 999999}, 'expense_type', 'Escolha um tipo da lista.'),
])
def test_invalid_edits_are_refused(client, openai, changes, field, message):
    expense = submitted(openai, employee())
    client.force_login(control())

    response = send_action(client, expense, 'request_correction', 'Corrija', form_data(expense, **changes))

    assert response.status_code == 400
    assert field in response.json()['errors'] and message in response.json()['detail']
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW and expense.version == 1


@pytest.mark.django_db
def test_invalid_item_is_refused(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())
    data = form_data(expense)
    data['items'][1]['amount'] = 'abc'

    response = send_action(client, expense, 'approve', '', data)

    assert response.status_code == 400 and response.json()['detail'].startswith('Item 2: Valor')


@pytest.mark.django_db
def test_control_cannot_reuse_an_access_key(client, openai):
    user = employee()
    submitted(openai, user, access_key=access_key(1))
    second = submitted(openai, user, access_key=access_key(2))
    client.force_login(control())

    response = send_action(client, second, 'approve', '', form_data(second, access_key=access_key(1)))

    assert response.status_code == 400 and 'Já existe outra nota' in response.json()['detail']


@pytest.mark.django_db
@pytest.mark.parametrize('action', ['request_correction', 'reject'])
def test_correction_and_rejection_need_a_note(client, openai, action):
    expense = submitted(openai, employee())
    client.force_login(control())

    response = send_action(client, expense, action, '   ')

    assert response.status_code == 400 and 'observação' in response.json()['detail']
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW


@pytest.mark.django_db
def test_control_requests_a_correction(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())

    response = send_action(client, expense, 'request_correction', 'A foto está cortada.')

    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_CORRECTION and expense.last_note == 'A foto está cortada.'
    event = expense.events.last()
    assert event.action == ExpenseEvent.REQUEST_CORRECTION and event.author_role == ExpenseEvent.CONTROL


@pytest.mark.django_db
@pytest.mark.parametrize('field, label', [
    ('number', 'número da nota'),
    ('issue_date', 'data'),
    ('total', 'valor total'),
    ('cnpj', 'CNPJ do emitente'),
    ('expense_type', 'tipo'),
])
def test_approval_needs_the_required_fields(client, openai, field, label):
    expense = submitted(openai, employee())
    client.force_login(control())

    response = send_action(client, expense, 'approve', '', form_data(expense, **{field: ''}))

    assert response.status_code == 400 and label in response.json()['detail']
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW


@pytest.mark.django_db
def test_access_key_is_not_required_to_approve(client, openai):
    expense = submitted(openai, employee(), access_key=None)
    client.force_login(control())

    assert send_action(client, expense, 'approve', '', form_data(expense)).status_code == 200


@pytest.mark.django_db
def test_approval_needs_a_reimbursed_value(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())
    data = form_data(expense)
    for item in data['items']:
        item['non_reimbursable'] = True

    response = send_action(client, expense, 'approve', '', data)
    assert response.status_code == 400 and 'valor reembolsado maior que zero' in response.json()['detail']

    response = send_action(client, expense, 'approve', '', form_data(expense, items=[]))
    assert response.status_code == 400 and 'valor reembolsado maior que zero' in response.json()['detail']


@pytest.mark.django_db
def test_stale_version_is_refused(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())

    response = send_action(client, expense, 'approve', '', form_data(expense), version=expense.version + 5)

    assert response.status_code == 409
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW


@pytest.mark.django_db
def test_each_stage_only_accepts_its_role(client, openai):
    expense = submitted(openai, employee())
    client.force_login(finance())
    assert send_action(client, expense, 'approve').status_code == 403

    act(control(), expense.pk, 'approve', '', expense.version)
    client.force_login(User.objects.get(username='controle'))
    assert send_action(client, expense, 'approve').status_code == 403

    client.force_login(User.objects.get(username='funcionario'))
    assert send_action(client, expense, 'approve').status_code == 403


# ---------- Validação do Financeiro ----------

@pytest.mark.django_db
def test_finance_sees_the_form_read_only(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', expense.version)
    client.force_login(finance())

    data = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']
    assert data['can'] == {'edit': False, 'act': True, 'resubmit': False, 'discard': False, 'reread': False}

    # O que o Financeiro mandar de dados é ignorado
    response = send_action(client, expense, 'request_correction', 'Confirme o valor.', form_data(expense, number='1'))
    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.number == '000123'


@pytest.mark.django_db
def test_finance_correction_goes_back_to_control_never_to_the_employee(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', expense.version)
    client.force_login(finance())

    assert send_action(client, expense, 'request_correction', '').status_code == 400
    response = send_action(client, expense, 'request_correction', 'Por que o valor é maior que a média?')

    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_EXPLANATION
    assert expense.events.last().action == ExpenseEvent.REQUEST_EXPLANATION


@pytest.mark.django_db
def test_control_must_explain_before_sending_back_to_finance(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', expense.version)
    expense.refresh_from_db()
    act(finance(), expense.pk, 'request_correction', 'Explique o valor.', expense.version)
    client.force_login(User.objects.get(username='controle'))

    response = send_action(client, expense, 'approve', '', form_data(expense))
    assert response.status_code == 400 and 'explicação' in response.json()['detail']

    response = send_action(client, expense, 'approve', 'Reunião com 3 clientes.', form_data(expense))
    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_VALIDATION
    assert expense.events.last().action == ExpenseEvent.EXPLAIN


@pytest.mark.django_db
def test_control_can_send_a_returned_note_to_the_employee(openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)
    act(finance(), expense.pk, 'request_correction', 'A foto não mostra a data.', 2)

    act(User.objects.get(username='controle'), expense.pk, 'request_correction', 'Envie a foto com a data.', 3)

    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_CORRECTION


@pytest.mark.django_db
def test_finance_approval_triggers_the_rm_launch(client, openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', expense.version)
    client.force_login(finance())

    with patch('expenses.workflow.rm.launch_in_rm') as launch:
        with django_capture_on_commit_callbacks(execute=True):
            response = send_action(client, expense, 'approve')

    assert response.status_code == 200
    expense.refresh_from_db()
    assert expense.status == Expense.APPROVED
    launch.assert_called_once()
    assert launch.call_args[0][0].pk == expense.pk


@pytest.mark.django_db
def test_rm_launch_is_not_triggered_before_the_finance_approval(client, openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())
    client.force_login(control())

    with patch('expenses.workflow.rm.launch_in_rm') as launch:
        with django_capture_on_commit_callbacks(execute=True):
            send_action(client, expense, 'approve', '', form_data(expense))

    launch.assert_not_called()


@pytest.mark.django_db
def test_rm_extension_point_does_nothing_yet():
    from expenses.rm import launch_in_rm

    assert launch_in_rm(object()) is None


@pytest.mark.django_db
def test_finance_rejects_and_the_note_is_closed(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', expense.version)
    client.force_login(finance())

    assert send_action(client, expense, 'reject', 'Despesa pessoal.').status_code == 200
    expense.refresh_from_db()
    assert expense.status == Expense.REJECTED and expense.last_note == 'Despesa pessoal.'

    # Encerrada de vez: ninguém age mais sobre ela
    for user in (finance(username='fin2'), User.objects.get(username='controle')):
        client.force_login(user)
        response = send_action(client, expense, 'approve')
        assert response.status_code in (400, 403)
    expense.refresh_from_db()
    assert expense.status == Expense.REJECTED


@pytest.mark.django_db
def test_superuser_plays_control_and_finance_on_the_same_note(client, openai):
    expense = submitted(openai, employee())
    admin = User.objects.create_superuser(username='admin', password='senha')
    sign_in(client, admin)

    assert send_action(client, expense, 'approve', '', form_data(expense)).status_code == 200
    assert send_action(client, expense, 'approve').status_code == 200

    expense.refresh_from_db()
    assert expense.status == Expense.APPROVED
    assert [event.author_role for event in expense.events.all()] == [
        ExpenseEvent.EMPLOYEE, ExpenseEvent.CONTROL, ExpenseEvent.FINANCE,
    ]


@pytest.mark.django_db
def test_unknown_action_is_refused(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())

    assert send_action(client, expense, 'pay').status_code == 400


# ---------- Reenvio ----------

@pytest.mark.django_db
def test_resubmission_swaps_only_the_photos(client, openai, catalog):
    user = employee()
    expense = submitted(openai, user)
    old_photo = expense.photos.get()
    act(control(), expense.pk, 'request_correction', 'A foto está cortada.', 1,
        data=form_data(expense, number='777', expense_type=catalog['types']['Combustível'].pk))
    openai.reset_mock()
    client.force_login(user)

    response = client.post(
        reverse('expenses:expense-photos-api', args=[expense.pk]),
        {'photos': [photo(color='gray'), photo(color='black')], 'note': 'Fotos novas.'},
    )

    assert response.status_code == 200
    # A IA olha as fotos novas, mas o que o Controle editou fica como está
    openai.assert_called_once()
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW
    assert expense.number == '777' and expense.expense_type == catalog['types']['Combustível']
    current = list(expense.photos.filter(replaced_at__isnull=True))
    assert [photo_.round for photo_ in current] == [2, 2]
    old_photo.refresh_from_db()
    assert old_photo.replaced_at is not None
    event = expense.events.last()
    assert event.action == ExpenseEvent.RESUBMIT and event.note == 'Fotos novas.'
    assert [item['id'] for item in event.snapshot['photos']] == [item.pk for item in current]


@pytest.mark.django_db
def test_replaced_photos_stay_accessible(client, openai):
    user = employee()
    expense = submitted(openai, user)
    old_photo = expense.photos.get()
    act(control(), expense.pk, 'request_correction', 'Refaça.', 1)
    resubmit_photos(user, expense.pk, [photo(color='gray')])

    client.force_login(User.objects.get(username='controle'))
    assert client.get(reverse('expenses:photo', args=[old_photo.pk])).status_code == 200
    client.force_login(user)
    response = client.get(reverse('expenses:photo', args=[old_photo.pk]))
    assert response.status_code == 200 and response['Content-Type'] == 'image/jpeg'


@pytest.mark.django_db
def test_resubmission_only_while_awaiting_correction(client, openai):
    user = employee()
    expense = submitted(openai, user)
    client.force_login(user)
    url = reverse('expenses:expense-photos-api', args=[expense.pk])

    response = client.post(url, {'photos': [photo()]})
    assert response.status_code == 400 and 'aguarda correção' in response.json()['detail']

    act(control(), expense.pk, 'reject', 'Nota de terceiro.', 1)
    assert client.post(url, {'photos': [photo()]}).status_code == 400
    assert expense.photos.count() == 1


@pytest.mark.django_db
def test_only_the_owner_resubmits(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'request_correction', 'Refaça.', 1)
    client.force_login(employee(username='bruno', email='b@empresa.com'))

    response = client.post(reverse('expenses:expense-photos-api', args=[expense.pk]), {'photos': [photo()]})

    assert response.status_code == 404


@pytest.mark.django_db
def test_round_trips_as_many_times_as_needed(openai):
    user = employee()
    reviewer, validator = control(), finance()
    expense = submitted(openai, user)

    act(reviewer, expense.pk, 'request_correction', 'Foto 1 ruim.', 1)
    resubmit_photos(user, expense.pk, [photo()])
    act(reviewer, expense.pk, 'request_correction', 'Foto 2 ruim.', 3)
    resubmit_photos(user, expense.pk, [photo()])
    act(reviewer, expense.pk, 'approve', '', 5)
    act(validator, expense.pk, 'request_correction', 'Explique.', 6)
    act(reviewer, expense.pk, 'approve', 'Explicado.', 7)
    act(validator, expense.pk, 'approve', '', 8)

    expense.refresh_from_db()
    assert expense.status == Expense.APPROVED and expense.version == 9
    assert [event.sequence for event in expense.events.all()] == list(range(1, 10))
    assert expense.photos.count() == 3 and expense.photos.filter(replaced_at__isnull=True).count() == 1


# ---------- E-mails ----------

@pytest.mark.django_db
def test_employee_gets_an_email_on_every_status_change(client, openai, django_capture_on_commit_callbacks):
    user = employee()
    client.force_login(user)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse('expenses:expenses-api'), {'photos': [photo()]})
    expense = Expense.objects.get()

    with django_capture_on_commit_callbacks(execute=True):
        act(control(), expense.pk, 'approve', '', 1)
    with django_capture_on_commit_callbacks(execute=True):
        act(finance(), expense.pk, 'approve', '', 2)

    assert [message.to for message in mail.outbox] == [[user.email]] * 3
    assert [message.subject for message in mail.outbox] == [
        f'Despesa #{expense.pk}: Aguardando conferência',
        f'Despesa #{expense.pk}: Aguardando validação',
        f'Despesa #{expense.pk}: Aprovada',
    ]
    # O link do e-mail abre a rota da despesa
    assert f'Acompanhe a despesa no portal: http://testserver/expenses/{expense.pk}/' in mail.outbox[0].body
    assert 'A sua despesa foi aprovada.' in mail.outbox[2].body
    assert 'Valor reembolsado: R$ 45,00' in mail.outbox[2].body


@pytest.mark.django_db
def test_rejection_email_brings_the_reason(openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())

    with django_capture_on_commit_callbacks(execute=True):
        act(control(), expense.pk, 'reject', 'Despesa fora da política de viagens.', 1)

    message = mail.outbox[-1]
    assert message.subject == f'Despesa #{expense.pk}: Rejeitada'
    assert 'Motivo da rejeição:\nDespesa fora da política de viagens.' in message.body


@pytest.mark.django_db
def test_correction_email_brings_what_to_fix(openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())

    with django_capture_on_commit_callbacks(execute=True):
        act(control(), expense.pk, 'request_correction', 'A foto está cortada.', 1)

    assert 'Correção pedida:\nA foto está cortada.' in mail.outbox[-1].body


@pytest.mark.django_db
def test_notes_between_control_and_finance_stay_out_of_the_email(openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)

    with django_capture_on_commit_callbacks(execute=True):
        act(finance(), expense.pk, 'request_correction', 'Assunto interno do Financeiro.', 2)

    message = mail.outbox[-1]
    assert message.subject == f'Despesa #{expense.pk}: Aguardando explicação'
    assert 'Assunto interno do Financeiro.' not in message.body


@pytest.mark.django_db
def test_control_and_finance_get_no_email(openai, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        expense = submitted(openai, employee())
        act(control(), expense.pk, 'approve', '', 1)
        act(finance(), expense.pk, 'approve', '', 2)

    recipients = {address for message in mail.outbox for address in message.to}
    assert recipients == {'funcionario@empresa.com'}


@pytest.mark.django_db
def test_employee_without_email_gets_nothing_and_the_flow_goes_on(openai, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        expense = submitted(openai, employee(email=''))

    assert mail.outbox == [] and expense.status == Expense.AWAITING_REVIEW


@pytest.mark.django_db
def test_mail_server_failure_does_not_undo_the_action(openai, django_capture_on_commit_callbacks):
    expense = submitted(openai, employee())

    with patch('expenses.emails.send_mail', side_effect=smtplib.SMTPException('fora')):
        with django_capture_on_commit_callbacks(execute=True):
            act(control(), expense.pk, 'approve', '', 1)

    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_VALIDATION


# ---------- O que o funcionário vê ----------

@pytest.mark.django_db
def test_rejection_reason_shows_on_the_note(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'reject', 'Nota de outra empresa.', 1)
    client.force_login(user)

    data = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']

    assert data['status_display'] == 'Rejeitada' and data['last_note'] == 'Nota de outra empresa.'
    assert data['timeline'][-1]['note'] == 'Nota de outra empresa.'


@pytest.mark.django_db
def test_employee_timeline_hides_the_notes_between_control_and_finance(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'approve', 'Conferido sem ressalvas.', 1)
    act(finance(), expense.pk, 'request_correction', 'Assunto interno.', 2)
    client.force_login(user)

    data = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']

    assert [event['note'] for event in data['timeline']] == ['', '', '']
    assert data['last_note'] == ''
    assert 'author_name' not in data['timeline'][0]


@pytest.mark.django_db
def test_control_sees_the_alerts_and_the_last_note(client, openai):
    expense = submitted(openai, employee(), alerts=['A nota não traz o CNPJ da empresa.'])
    act(control(), expense.pk, 'approve', '', 1)
    act(finance(), expense.pk, 'request_correction', 'Explique.', 2)
    client.force_login(User.objects.get(username='controle'))

    data = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']

    assert data['alerts'] == ['A nota não traz o CNPJ da empresa.']
    # O setor saiu da tela; o centro de custo fica
    assert 'sector' not in data and 'cost_center' in data
    assert data['explanation_required'] is True and data['can']['edit'] is True
    assert data['timeline'][-1]['note'] == 'Explique.'


@pytest.mark.django_db
def test_timeline_names_the_user_and_the_stage_but_not_the_role(client, openai):
    user, reviewer, validator = employee(), control(), finance()
    expense = submitted(openai, user)
    act(reviewer, expense.pk, 'approve', '', 1)
    act(validator, expense.pk, 'request_correction', 'Explique.', 2)
    act(reviewer, expense.pk, 'approve', 'Explicado.', 3)
    act(validator, expense.pk, 'approve', '', 4)

    client.force_login(reviewer)
    timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
    # "Conferida", e não "Aprovada": a aprovação só vem na validação
    assert [(event['action_display'], event['author_name']) for event in timeline] == [
        ('Nota enviada', 'Ana Silva'), ('Conferida', 'controle'), ('Explicação solicitada', 'financeiro'),
        ('Explicação enviada', 'controle'), ('Aprovada', 'financeiro'),
    ]
    assert all('role_display' not in event for event in timeline)

    client.force_login(user)
    timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
    assert all('role_display' not in event and 'author_name' not in event for event in timeline)


@pytest.mark.django_db
def test_timeline_leaves_out_the_status_of_each_step(client, openai):
    # O título da etapa já diz o que aconteceu: a situação ao lado do nome sobra
    user, reviewer = employee(), control()
    expense = submitted(openai, user)
    act(reviewer, expense.pk, 'request_correction', 'Foto cortada.', 1)

    for viewer in (user, reviewer):
        client.force_login(viewer)
        timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
        assert len(timeline) == 2 and all('status_display' not in event for event in timeline)

    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    assert "text: [event.created_at, event.author_name].filter(Boolean).join(' · ')" in script


@pytest.mark.django_db
def test_timeline_shows_the_current_name_of_the_author(client, openai):
    reviewer = control()
    expense = submitted(openai, employee())
    act(reviewer, expense.pk, 'request_correction', 'Foto cortada.', 1)

    # O nome foi salvo no cadastro depois da ação
    reviewer.first_name, reviewer.last_name = 'Adm', 'Silva'
    reviewer.save()
    client.force_login(reviewer)

    timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
    assert [event['author_name'] for event in timeline] == ['Ana Silva', 'Adm Silva']
    # O registro guarda o nome de quando a ação aconteceu, para a auditoria
    assert expense.events.last().author_name == 'controle'

    # Sem nome no cadastro, fica o username
    reviewer.first_name = reviewer.last_name = ''
    reviewer.save()
    timeline = client.get(reverse('expenses:expense-api', args=[expense.pk])).json()['expense']['timeline']
    assert timeline[-1]['author_name'] == 'controle'


@pytest.mark.django_db
def test_screens_and_emails_do_not_name_the_sectors(client, openai, django_capture_on_commit_callbacks):
    # Os setores que conferem e validam podem mudar: a tela e os e-mails falam só das etapas
    sectors = re.compile('Controle|Financeiro')
    user, reviewer, validator = employee(), control(), finance()
    with django_capture_on_commit_callbacks(execute=True):
        expense = submitted(openai, user)
        returned = submitted(openai, user, access_key=access_key(2))
    for step in (
        lambda: act(reviewer, expense.pk, 'approve', '', 1),
        lambda: act(validator, expense.pk, 'request_correction', 'Explique.', 2),
        lambda: act(reviewer, expense.pk, 'approve', 'Explicado.', 3),
        lambda: act(validator, expense.pk, 'approve', '', 4),
        lambda: act(reviewer, returned.pk, 'request_correction', 'Foto cortada.', 1),
        lambda: resubmit_photos(user, returned.pk, [photo()]),
        lambda: act(reviewer, returned.pk, 'reject', 'Nota de outra empresa.', 3),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            step()

    assert len(mail.outbox) == 9
    assert not [message.body for message in mail.outbox if sectors.search(message.body)]
    labels = [label for _, label in ExpenseEvent.ACTIONS + ExpenseEvent.ROLES]
    assert not [label for label in labels if sectors.search(label)]

    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    assert not sectors.search(script)
    for viewer in (user, reviewer):
        client.force_login(viewer)
        assert not sectors.search(client.get(reverse('expenses:expenses')).content.decode())


@pytest.mark.django_db
def test_messages_of_the_wrong_stage_do_not_name_the_sectors(openai):
    expense, reviewer = submitted(openai, employee()), control()
    with pytest.raises(PermissionDenied, match='Esta despesa está na conferência.'):
        act(finance(), expense.pk, 'approve', '', 1)
    act(reviewer, expense.pk, 'approve', '', 1)
    with pytest.raises(PermissionDenied, match='Esta despesa está na validação.'):
        act(reviewer, expense.pk, 'approve', '', 2)
    assert ROLE_CONFLICT == 'Cada usuário pode ter um só papel nas despesas: enviar notas, conferir ou validar.'


# ---------- Exclusão ----------

@pytest.mark.django_db
def test_notes_with_history_cannot_be_deleted(openai):
    expense = submitted(openai, employee())

    with pytest.raises(ProtectedError):
        expense.delete()


def expense_url(expense):
    return reverse('expenses:expense-api', args=[expense.pk])


@pytest.mark.django_db
def test_employee_discards_an_untouched_expense(client, openai, media_root, django_capture_on_commit_callbacks):
    user = employee()
    expense = submitted(openai, user, access_key=access_key(5))
    files = [media_root / photo_.file.name for photo_ in expense.photos.all()]
    assert files and all(path.exists() for path in files)
    mail.outbox = []
    client.force_login(user)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.delete(expense_url(expense))

    assert response.status_code == 200 and response.json()['detail'] == 'Despesa excluída.'
    # Sai tudo: a despesa, os itens, as fotos (os arquivos também) e o registro do envio
    assert not Expense.objects.exists() and not ExpenseItem.objects.exists()
    assert not ExpensePhoto.objects.exists() and not ExpenseEvent.objects.exists()
    assert not any(path.exists() for path in files)
    # Foi o próprio funcionário quem excluiu: nenhum e-mail
    assert mail.outbox == []
    # A chave de acesso fica livre para a mesma nota ser enviada de novo
    assert submitted(openai, user, access_key=access_key(5)).access_key == access_key(5)


@pytest.mark.django_db
def test_discard_is_offered_only_while_nobody_handled_the_expense(client, openai):
    user, reviewer = employee(), control()
    expense = submitted(openai, user)
    client.force_login(user)
    assert client.get(expense_url(expense)).json()['expense']['can']['discard'] is True

    # Pedida a correção e reenviadas as fotos, ela volta a aguardar conferência, mas já foi tratada
    act(reviewer, expense.pk, 'request_correction', 'Foto cortada.', 1)
    assert client.get(expense_url(expense)).json()['expense']['can']['discard'] is False
    resubmit_photos(user, expense.pk, [photo()])
    expense.refresh_from_db()
    assert expense.status == Expense.AWAITING_REVIEW
    assert client.get(expense_url(expense)).json()['expense']['can']['discard'] is False

    response = client.delete(expense_url(expense))
    assert response.status_code == 409
    assert response.json()['detail'] == 'Esta despesa já foi tratada e não pode mais ser excluída.'
    assert Expense.objects.filter(pk=expense.pk).exists() and expense.events.count() == 3


@pytest.mark.django_db
def test_discard_is_refused_once_the_review_acted(client, openai):
    # Quem confere agiu entre a abertura da tela e o toque em Excluir
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'approve', '', 1)
    client.force_login(user)

    assert client.delete(expense_url(expense)).status_code == 409
    assert Expense.objects.get(pk=expense.pk).status == Expense.AWAITING_VALIDATION


@pytest.mark.django_db
def test_only_the_owner_discards(client, openai):
    expense = submitted(openai, employee())

    client.force_login(employee(username='outro', email='outro@empresa.com'))
    assert client.delete(expense_url(expense)).status_code == 404
    client.force_login(control())
    assert client.delete(expense_url(expense)).status_code == 403
    assert client.get(expense_url(expense)).json()['expense']['can']['discard'] is False
    assert Expense.objects.filter(pk=expense.pk).exists()


@pytest.mark.django_db
def test_discard_button_sits_after_the_history_for_the_employee(client):
    client.force_login(employee())
    content = client.get(reverse('expenses:expenses')).content.decode()
    # Embaixo do histórico, dentro da tela da despesa, e não na barra presa ao rodapé
    timeline, discard, detail_end = (
        content.index('id="timeline"'), content.index('id="discard-box"'), content.index('id="mobile-bar"'),
    )
    assert timeline < discard < detail_end
    assert 'Excluir despesa' in content

    client.force_login(control())
    assert 'id="discard-box"' not in client.get(reverse('expenses:expenses')).content.decode()


# ---------- Celular ----------

@pytest.mark.django_db
def test_employee_filters_by_several_statuses_and_gets_the_counts(client, openai):
    user = employee()
    waiting = submitted(openai, user, access_key=access_key(1))
    correction = submitted(openai, user, access_key=access_key(2))
    validation = submitted(openai, user, access_key=access_key(3))
    reviewer = control()
    act(reviewer, correction.pk, 'request_correction', 'Refaça a foto.', 1)
    act(reviewer, validation.pk, 'approve', '', 1)
    submitted(openai, employee(username='bruno', email='b@empresa.com'), access_key=access_key(4))
    client.force_login(user)
    url = reverse('expenses:expenses-api')

    # "Em andamento" junta o que está na conferência e na validação
    in_progress = client.get(url, {'status': 'C,E,V'}).json()
    assert {item['id'] for item in in_progress['expenses']} == {waiting.pk, validation.pk}
    assert [item['id'] for item in client.get(url, {'status': 'S'}).json()['expenses']] == [correction.pk]
    # Situação desconhecida é ignorada
    assert len(client.get(url, {'status': 'X,'}).json()['expenses']) == 3
    # Os números dos filtros contam só as notas dele
    assert in_progress['counts'] == {'C': 1, 'S': 1, 'V': 1}


@pytest.mark.django_db
def test_reviewers_get_no_employee_counts(client, openai):
    submitted(openai, employee())
    client.force_login(control())

    assert 'counts' not in client.get(reverse('expenses:expenses-api')).json()


@pytest.mark.django_db
def test_employee_page_is_built_for_the_phone(client):
    client.force_login(employee())

    content = client.get(reverse('expenses:expenses')).content.decode()
    # Os filtros em botões, o Enviar nota no rodapé e o progresso do envio
    for element_id in ('status-chips', 'mobile-bar', 'submit-progress', 'resubmit-progress', 'status-banner', 'employee-summary'):
        assert f'id="{element_id}"' in content
    assert 'id="status-filter"' not in content and 'id="search-input"' not in content


@pytest.mark.django_db
def test_reviewer_page_keeps_the_search_and_has_no_phone_bar(client):
    client.force_login(control())

    content = client.get(reverse('expenses:expenses')).content.decode()
    assert 'id="status-filter"' in content and 'id="search-input"' in content
    assert 'id="status-chips"' not in content and 'id="mobile-bar"' not in content


def test_resubmit_screen_says_the_photos_are_being_analysed():
    # O reenvio agora espera a IA: a tela avisa que pode demorar
    script = Path(finders.find('expenses/js/expenses.js')).read_text(encoding='utf-8')
    assert "progressView('resubmit', 'Fotos enviadas. Analisando as fotos" in script
