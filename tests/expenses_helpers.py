"""O que os testes das despesas usam em comum: usuários por papel, fotos e a resposta falsa da OpenAI."""
import io
import itertools
import json
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from app.models import User
from expenses.models import ExpenseType, NonReimbursableGroup
from expenses.validators import check_digit


# 11.222.333/0001-81: os dígitos verificadores conferem
VALID_CNPJ = '11222333000181'

OTHER_CNPJ = '11444777000161'


def access_key(serial=1):
    """Uma chave de 44 dígitos com o dígito verificador certo."""
    body = f'3526{11}{VALID_CNPJ}65001{serial:09d}1{serial:08d}'[:43].ljust(43, '0')
    digits = [int(char) for char in body]
    return body + str(check_digit(digits, range(2, 10)))


def make_user(*codenames, username='funcionario', email='funcionario@empresa.com', **kwargs):
    user = User.objects.create_user(username=username, password='senha', email=email, **kwargs)
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label='expenses', codename__in=codenames)
    )
    return User.objects.get(pk=user.pk)


def employee(username='funcionario', **kwargs):
    return make_user('submit_expense', username=username, first_name='Ana', last_name='Silva', **kwargs)


def control(username='controle', **kwargs):
    return make_user('review_expense', username=username, email=f'{username}@empresa.com', **kwargs)


def finance(username='financeiro', **kwargs):
    return make_user('validate_expense', username=username, email=f'{username}@empresa.com', **kwargs)


PHOTO_MARKS = itertools.count(1)


def photo(name='nota.jpg', size=(400, 600), color='white', fmt='JPEG', content_type='image/jpeg'):
    """
    Uma foto diferente a cada chamada (o portal recusa a foto repetida): leva
    um quadrado de cor própria no canto. Para mandar a mesma foto de novo, use
    same_photo.
    """
    mark = next(PHOTO_MARKS)
    image = Image.new('RGB', size, color)
    image.paste((mark * 37 % 256, mark * 91 % 256, mark * 53 % 256), (0, 0, 60, 60))
    image.paste((mark // 256 * 41 % 256, mark * 13 % 256, mark * 7 % 256), (60, 0, 120, 60))
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def same_photo(file, name=None):
    """Outro arquivo com os mesmos bytes da foto."""
    file.seek(0)
    content = file.read()
    # A foto de origem volta ao começo para poder ser enviada também
    file.seek(0)
    return SimpleUploadedFile(name or file.name, content, content_type=file.content_type)


def reading_payload(**overrides):
    payload = {
        'is_expense_document': True,
        'cnpj': '11.222.333/0001-81',
        'access_key': access_key(),
        'number': '000123',
        'issue_date': '2026-11-10',
        'total': 50.0,
        'expense_type': 'Alimentação',
        'items': [
            {'description': 'Refeição executiva', 'quantity': 1, 'amount': 45.0, 'non_reimbursable_group': None},
            {'description': 'Cerveja lata', 'quantity': 1, 'amount': 5.0, 'non_reimbursable_group': 'Bebida alcoólica'},
        ],
        'alerts': [],
        'instructions_in_image': False,
    }
    payload.update(overrides)
    return payload


def api_response(payload, status='completed'):
    """A resposta da Responses API com o JSON que o modelo escreveu."""
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        'status': status,
        'output': [
            {'type': 'reasoning', 'summary': []},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(payload)}]},
        ],
    }
    return response


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type='application/json')


# ---------- Fixtures (importadas pelos arquivos de teste das despesas) ----------

@pytest.fixture
def media_root(settings, tmp_path):
    # As fotos enviadas nos testes vão para uma pasta temporária, e não para o media_root de verdade
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def catalog(db):
    types = {name: ExpenseType.objects.create(name=name) for name in ('Alimentação', 'Combustível', 'Hospedagem')}
    groups = {name: NonReimbursableGroup.objects.create(name=name) for name in ('Bebida alcoólica', 'Jogos de azar')}
    return {'types': types, 'groups': groups}


@pytest.fixture
def openai(settings, monkeypatch, catalog):
    """A OpenAI falsa: responde a leitura padrão, que cada teste pode trocar em openai.return_value."""
    settings.OPENAI_API_KEY = 'sk-test'
    settings.OPENAI_MODEL = 'gpt-test'
    post = MagicMock(return_value=api_response(reading_payload()))
    monkeypatch.setattr('expenses.reading.requests.post', post)
    return post


def submitted(openai, user, photos=None, note='', **overrides):
    """Uma nota enviada pelo fluxo, com a leitura padrão mais as trocas pedidas."""
    from expenses.workflow import submit_expense

    openai.return_value = api_response(reading_payload(**overrides))
    return submit_expense(user, photos or [photo()], note)
