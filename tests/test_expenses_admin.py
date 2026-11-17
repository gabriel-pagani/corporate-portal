import re

import pytest
from django.contrib.auth.models import Group, Permission
from django.db.migrations.loader import MigrationLoader
from django.forms import modelform_factory
from django.urls import reverse
from reversion.models import Version

from app.admin import PortalGroupForm
from app.models import ServiceAccess, User
from expenses.models import ExpenseRules, ExpenseType, NonReimbursableGroup
from expenses.roles import ROLE_CONFLICT, SUBMIT_MANAGE_CONFLICT
from expenses.workflow import act
from tests.conftest import sign_in
from tests.expenses_helpers import (  # noqa: F401
    catalog, control, employee, finance, make_user, media_root, openai, submitted,
)


@pytest.fixture(autouse=True)
def isolated_media(media_root):
    return media_root


def permission(codename):
    return Permission.objects.get(content_type__app_label='expenses', codename=codename)


def user_change_data(user, **changes):
    data = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email or '',
        'is_active': 'on',
        'date_joined_0': '2026-01-01',
        'date_joined_1': '08:00:00',
        'groups': [],
        'user_permissions': [],
        'dashboards': [],
    }
    data.update(changes)
    return data


# ---------- Regras da IA (gestor) ----------

@pytest.mark.django_db
def test_rules_manager_keeps_the_lists_and_the_text_with_history(client):
    manager = make_user('review_expense', 'manage_expense_rules', username='gestor', is_staff=True)
    sign_in(client, manager)

    response = client.post(reverse('admin:expenses_expensetype_add'), {'name': 'Combustível'})
    assert response.status_code == 302
    response = client.post(reverse('admin:expenses_nonreimbursablegroup_add'), {'name': 'Bebida alcoólica'})
    assert response.status_code == 302
    response = client.post(reverse('admin:expenses_expenserules_add'), {'text': 'A nota deve conter o CNPJ da empresa.'})
    assert response.status_code == 302

    assert ExpenseRules.current_text() == 'A nota deve conter o CNPJ da empresa.'
    # O reversion guarda quem mudou o quê
    for obj in (ExpenseType.objects.get(), NonReimbursableGroup.objects.get(), ExpenseRules.objects.get()):
        version = Version.objects.get_for_object(obj).get()
        assert version.revision.user == manager


@pytest.mark.django_db
def test_without_the_permission_the_rules_are_out_of_reach(client):
    staff = make_user('review_expense', username='staff', is_staff=True)
    sign_in(client, staff)

    for name in ('expensetype', 'nonreimbursablegroup', 'expenserules'):
        assert client.get(reverse(f'admin:expenses_{name}_changelist')).status_code == 403
        assert client.post(reverse(f'admin:expenses_{name}_add'), {'name': 'X', 'text': 'X'}).status_code == 403
    assert not ExpenseType.objects.exists() and not ExpenseRules.objects.exists()


@pytest.mark.django_db
def test_superuser_manages_the_rules(client):
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))

    assert client.post(reverse('admin:expenses_nonreimbursablegroup_add'), {'name': 'Jogos de azar'}).status_code == 302
    assert NonReimbursableGroup.objects.filter(name='Jogos de azar').exists()


@pytest.mark.django_db
def test_rules_text_is_a_single_record(client):
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))

    response = client.get(reverse('admin:expenses_expenserules_changelist'))
    assert response.status_code == 302 and response.url == reverse('admin:expenses_expenserules_add')

    rules = ExpenseRules.objects.create(text='Uma regra.')
    response = client.get(reverse('admin:expenses_expenserules_changelist'))
    assert response.url == reverse('admin:expenses_expenserules_change', args=[rules.pk])
    assert client.get(reverse('admin:expenses_expenserules_add')).status_code == 403
    assert client.post(reverse('admin:expenses_expenserules_delete', args=[rules.pk]), {'post': 'yes'}).status_code == 403


@pytest.mark.django_db
def test_type_in_use_cannot_be_deleted(client, openai, catalog):
    expense = submitted(openai, employee())
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))

    client.post(reverse('admin:expenses_expensetype_delete', args=[expense.expense_type_id]), {'post': 'yes'})

    assert ExpenseType.objects.filter(pk=expense.expense_type_id).exists()


# ---------- Auditoria no admin ----------

@pytest.mark.django_db
def test_notes_and_history_are_read_only_in_the_admin(client, openai):
    expense = submitted(openai, employee())
    act(control(), expense.pk, 'approve', '', 1)
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))

    content = client.get(reverse('admin:expenses_expense_change', args=[expense.pk])).content.decode()
    assert 'Aprovada pelo Controle' in content and 'Leitura da IA' in content
    assert 'name="number"' not in content

    event = expense.events.last()
    content = client.get(reverse('admin:expenses_expenseevent_change', args=[event.pk])).content.decode()
    assert 'Estado da nota' in content and '000123' in content

    assert client.get(reverse('admin:expenses_expense_add')).status_code == 403
    assert client.post(reverse('admin:expenses_expenseevent_delete', args=[event.pk]), {'post': 'yes'}).status_code == 403
    changelist = client.get(reverse('admin:expenses_expenseevent_changelist'), {'created_at__year': event.created_at.year})
    assert changelist.status_code == 200


# ---------- Papéis no cadastro ----------

@pytest.mark.django_db
@pytest.mark.parametrize('codenames, message', [
    (('submit_expense', 'review_expense'), ROLE_CONFLICT),
    (('review_expense', 'validate_expense'), ROLE_CONFLICT),
    (('submit_expense', 'manage_expense_rules'), SUBMIT_MANAGE_CONFLICT),
])
def test_user_admin_refuses_forbidden_combinations(client, codenames, message):
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))
    user = User.objects.create_user(username='colaborador', password='senha')

    response = client.post(reverse('admin:app_user_change', args=[user.pk]), user_change_data(
        user, user_permissions=[permission(codename).pk for codename in codenames],
    ))

    assert response.status_code == 200 and message in response.content.decode()
    assert not user.user_permissions.exists()


@pytest.mark.django_db
def test_user_admin_refuses_a_second_role_through_a_group(client):
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))
    group = Group.objects.create(name='Financeiro')
    group.permissions.add(permission('validate_expense'))
    user = User.objects.create_user(username='colaborador', password='senha')

    response = client.post(reverse('admin:app_user_change', args=[user.pk]), user_change_data(
        user, user_permissions=[permission('review_expense').pk], groups=[group.pk],
    ))

    assert response.status_code == 200 and ROLE_CONFLICT in response.content.decode()


@pytest.mark.django_db
def test_user_admin_accepts_one_role_and_the_manager(client):
    sign_in(client, User.objects.create_superuser(username='admin', password='senha'))
    user = User.objects.create_user(username='colaborador', password='senha')

    response = client.post(reverse('admin:app_user_change', args=[user.pk]), user_change_data(
        user, user_permissions=[permission('review_expense').pk, permission('manage_expense_rules').pk],
    ))

    assert response.status_code == 302
    assert set(user.user_permissions.values_list('codename', flat=True)) == {'review_expense', 'manage_expense_rules'}


@pytest.mark.django_db
def test_group_permissions_cannot_give_a_member_two_roles():
    group = Group.objects.create(name='Controle')
    member = employee()
    member.groups.add(group)
    form_class = modelform_factory(Group, form=PortalGroupForm, fields=['name', 'permissions'])

    form = form_class(data={'name': 'Controle', 'permissions': [permission('review_expense').pk]}, instance=group)
    assert not form.is_valid()
    assert ROLE_CONFLICT in form.non_field_errors()[0] and 'funcionario' in form.non_field_errors()[0]

    form = form_class(data={'name': 'Controle', 'permissions': [permission('view_expense').pk]}, instance=group)
    assert form.is_valid()


# ---------- Home ----------

def card_order(client):
    content = client.get(reverse('app:home')).content.decode()
    return re.findall(r'data-service="([\w-]+)"', content)


@pytest.mark.django_db
def test_expenses_card_and_menu_follow_the_roles(client):
    client.force_login(make_user(username='sem-papel'))
    assert ServiceAccess.EXPENSES not in card_order(client)

    for user in (employee(), control(), finance()):
        client.force_login(user)
        content = client.get(reverse('app:home')).content.decode()
        assert ServiceAccess.EXPENSES in card_order(client)
        assert f'href="{reverse("expenses:expenses")}"' in content


@pytest.mark.django_db
def test_expenses_card_shows_the_employee_notes(client, openai):
    user = employee()
    expense = submitted(openai, user)
    act(control(), expense.pk, 'request_correction', 'Refaça.', 1)
    client.force_login(user)

    content = client.get(reverse('app:home')).content.decode()
    card = re.search(r'data-service="expenses">(.*?)</article>', content, re.S).group(1)
    assert f'?nota={expense.pk}' in card and 'Aguardando correção' in card


@pytest.mark.django_db
def test_expenses_card_shows_the_queues(client, openai):
    expense = submitted(openai, employee())
    client.force_login(control())

    content = client.get(reverse('app:home')).content.decode()
    card = re.search(r'data-service="expenses">(.*?)</article>', content, re.S).group(1)
    assert re.search(r'summary-value">1</span>\s*<span class="summary-label">aguardando conferência', card)
    assert 'aguardando validação' not in card
    assert expense.pk


# ---------- Migrations ----------

def test_expenses_tables_are_created_after_the_old_app_is_removed():
    # A app/0020 apaga as tabelas expenses_* e as linhas do app expenses no
    # django_migrations: num banco novo, ela tem de rodar antes da expenses/0001
    plan = MigrationLoader(None, ignore_no_migrations=True).graph.forwards_plan(('expenses', '0001_initial'))

    assert ('app', '0020_remove_expenses') in plan
    assert plan.index(('app', '0020_remove_expenses')) < plan.index(('expenses', '0001_initial'))
