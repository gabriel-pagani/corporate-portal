import json
import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from app.models import Contact, Dashboard, HomeLayout, Notification, Sector, ServiceAccess, Toner, User
from app.utils.services import CARD_DEFAULT_HEIGHT, CARD_MAX_HEIGHT, CARD_MIN_HEIGHT, TICKETS_URL, register_access
from journey_audit.audit import current_period
from journey_audit.models import Competency, Occurrence


def make_user(*codenames, username='colaborador'):
    user = User.objects.create_user(username=username, password='senha')
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return user


def card_order(client):
    content = client.get(reverse('app:home')).content.decode()
    return re.findall(r'data-service="([\w-]+)"', content)


def card(client, service):
    content = client.get(reverse('app:home')).content.decode()
    match = re.search(rf'data-service="{service}">(.*?)</article>', content, re.S)
    assert match, f'card {service} ausente'
    return match.group(1)


@pytest.mark.django_db
def test_cards_follow_the_sidebar_permissions(client):
    client.force_login(make_user())

    assert card_order(client) == [
        ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.TICKETS, ServiceAccess.LIBRARY,
    ]


@pytest.mark.django_db
def test_cards_show_every_service_the_user_can_open(client):
    user = make_user('view_toner', 'register_customers_suppliers', 'view_competency')
    user.dashboards.add(Dashboard.objects.create(title='Faturamento'))
    client.force_login(user)

    assert card_order(client) == [
        ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.TICKETS, ServiceAccess.LIBRARY,
        ServiceAccess.DASHBOARDS, ServiceAccess.TONERS, ServiceAccess.CUSTOMERS_VENDORS, ServiceAccess.JOURNEY_AUDIT,
    ]


@pytest.mark.django_db
def test_cards_are_ordered_by_access_count(client):
    user = make_user('view_toner')
    client.force_login(user)

    for _ in range(3):
        client.get(reverse('app:toners'))
    client.get(reverse('app:notifications'))

    assert card_order(client) == [
        ServiceAccess.TONERS, ServiceAccess.NOTIFICATIONS, ServiceAccess.CONTACTS, ServiceAccess.TICKETS,
        ServiceAccess.LIBRARY,
    ]


@pytest.mark.django_db
def test_tie_goes_to_the_most_recent_access(client):
    user = make_user()
    client.force_login(user)

    client.get(reverse('app:notifications'))
    client.get(reverse('app:contacts'))

    assert card_order(client)[:2] == [ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS]


@pytest.mark.django_db
def test_access_to_a_service_lost_hides_its_card(client):
    user = make_user()
    register_access(user, ServiceAccess.TONERS)
    client.force_login(user)

    assert ServiceAccess.TONERS not in card_order(client)


@pytest.mark.django_db
def test_page_open_counts_but_forbidden_page_and_api_do_not(client):
    user = make_user()
    client.force_login(user)

    client.get(reverse('app:contacts'))
    client.get(reverse('app:contacts'))
    assert client.get(reverse('app:toners')).status_code == 403
    client.get(reverse('app:notifications-api'))

    accesses = dict(ServiceAccess.objects.filter(user=user).values_list('service', 'count'))
    assert accesses == {ServiceAccess.CONTACTS: 2}


@pytest.mark.django_db
def test_dashboard_pages_count_as_dashboards(client):
    user = make_user()
    dashboard = Dashboard.objects.create(title='Faturamento')
    user.dashboards.add(dashboard)
    client.force_login(user)

    client.get(reverse('app:dashboards'))
    client.get(reverse('app:dashboard', args=[dashboard.id]))
    other = Dashboard.objects.create(title='Sem acesso')
    assert client.get(reverse('app:dashboard', args=[other.id])).status_code == 404

    assert ServiceAccess.objects.get(user=user, service=ServiceAccess.DASHBOARDS).count == 2


@pytest.mark.django_db
def test_tickets_link_counts_and_redirects_to_the_help_desk(client):
    user = make_user()
    client.force_login(user)

    response = client.get(reverse('app:tickets'))

    assert response.status_code == 302
    assert response.url == TICKETS_URL
    assert ServiceAccess.objects.get(user=user, service=ServiceAccess.TICKETS).count == 1
    assert reverse('app:tickets') in client.get(reverse('app:home')).content.decode()


@pytest.mark.django_db
def test_tickets_link_requires_login(client):
    response = client.get(reverse('app:tickets'))
    assert response.status_code == 302
    assert reverse('app:login') in response.url


@pytest.mark.django_db
def test_journey_audit_page_counts(client):
    user = make_user('view_competency')
    client.force_login(user)

    client.get(reverse('journey_audit:audit'))

    assert ServiceAccess.objects.get(user=user, service=ServiceAccess.JOURNEY_AUDIT).count == 1


@pytest.mark.django_db
def test_notifications_card_shows_only_what_was_sent_to_the_user(client):
    user = make_user()
    other = make_user(username='outro')
    read = Notification.objects.create(title='Aviso antigo', message='-', start_at=timezone.now() - timedelta(days=1))
    read.read_by.add(user)
    Notification.objects.create(title='Manutenção hoje', message='Sistema fora do ar às 18h', level=Notification.URGENT)
    private = Notification.objects.create(title='Só para outro', message='-')
    private.users.add(other)
    client.force_login(user)

    content = card(client, ServiceAccess.NOTIFICATIONS)

    assert 'Manutenção hoje' in content
    assert 'Aviso antigo' in content
    assert 'Só para outro' not in content
    assert re.search(r'id="home-unread-count">1<', content)
    assert content.index('Manutenção hoje') < content.index('Aviso antigo')


@pytest.mark.django_db
def test_dashboards_card_lists_only_accessible_favorites(client):
    user = make_user()
    favorite = Dashboard.objects.create(title='Faturamento')
    hidden = Dashboard.objects.create(title='Folha de Pagamento')
    user.dashboards.add(favorite)
    favorite.fav_by.add(user)
    hidden.fav_by.add(user)
    client.force_login(user)

    content = card(client, ServiceAccess.DASHBOARDS)

    assert reverse('app:dashboard', args=[favorite.id]) in content
    assert 'Folha de Pagamento' not in content
    assert '1 dashboard disponível' in content


@pytest.mark.django_db
def test_toners_card_lists_low_stock(client):
    Toner.objects.create(name='HP 85A', quantity=1, minimum_quantity=2)
    Toner.objects.create(name='Brother TN-1060', quantity=10, minimum_quantity=2)
    client.force_login(make_user('view_toner'))

    content = card(client, ServiceAccess.TONERS)

    assert 'HP 85A' in content
    assert 'Brother TN-1060' not in content
    assert '1/2' in content


@pytest.mark.django_db
def test_journey_audit_card_shows_the_current_competency(client):
    start, end = current_period()
    competency = Competency.objects.create(start_date=start, end_date=end)
    Occurrence.objects.create(
        competency=competency, day=start, employee_id='1', employee_name='Fulano', location='Matriz',
        type=Occurrence.ABSENCE, evidence='-',
    )
    Occurrence.objects.create(
        competency=competency, day=start, employee_id='1', employee_name='Fulano', location='Matriz',
        type=Occurrence.OVERTIME, evidence='-',
    )
    client.force_login(make_user('view_competency'))

    content = card(client, ServiceAccess.JOURNEY_AUDIT)

    assert f'{start:%d/%m/%Y} a {end:%d/%m/%Y}' in content
    assert re.search(r'summary-value">1</span>\s*<span class="summary-label">pendente de tratativa', content)
    assert re.search(r'summary-value">2</span>\s*<span class="summary-label">ocorrências', content)


@pytest.mark.django_db
def test_contacts_card_embeds_the_list_for_the_search(client):
    Contact.objects.create(name='Recepção', number='2000', sector=Sector.objects.create(name='Administrativo'))
    client.force_login(make_user())

    content = client.get(reverse('app:home')).content.decode()

    assert 'id="home-contacts"' in content
    assert '"number": "2000"' in content
    assert 'machine' not in content


def hidden_cards(client):
    content = client.get(reverse('app:home')).content.decode()
    return re.findall(r'class="service-card service-[\w-]+ is-hidden"[^>]*data-service="([\w-]+)"', content)


def save_layout(client, payload):
    return client.post(reverse('app:home-layout-api'), payload, content_type='application/json')


@pytest.mark.django_db
def test_layout_api_requires_login(client):
    assert save_layout(client, {'order': [], 'hidden': []}).status_code == 401


@pytest.mark.django_db
def test_saved_layout_orders_and_hides_cards(client):
    user = make_user()
    register_access(user, ServiceAccess.CONTACTS)
    client.force_login(user)

    response = save_layout(client, {
        'order': [ServiceAccess.TICKETS, ServiceAccess.NOTIFICATIONS, ServiceAccess.CONTACTS, ServiceAccess.LIBRARY],
        'hidden': [ServiceAccess.NOTIFICATIONS],
    })

    assert response.status_code == 200
    assert card_order(client) == [
        ServiceAccess.TICKETS, ServiceAccess.NOTIFICATIONS, ServiceAccess.CONTACTS, ServiceAccess.LIBRARY,
    ]
    assert hidden_cards(client) == [ServiceAccess.NOTIFICATIONS]


@pytest.mark.django_db
def test_service_gained_after_the_layout_goes_to_the_end(client):
    user = make_user()
    client.force_login(user)
    save_layout(client, {
        'order': [ServiceAccess.TICKETS, ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.LIBRARY],
        'hidden': [],
    })

    user.user_permissions.add(Permission.objects.get(codename='view_toner'))
    user = User.objects.get(pk=user.pk)
    client.force_login(user)

    assert card_order(client) == [
        ServiceAccess.TICKETS, ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.LIBRARY,
        ServiceAccess.TONERS,
    ]
    assert hidden_cards(client) == []


@pytest.mark.django_db
def test_layout_never_shows_a_service_without_permission(client):
    client.force_login(make_user())
    save_layout(client, {'order': [ServiceAccess.TONERS, ServiceAccess.CONTACTS], 'hidden': []})

    assert ServiceAccess.TONERS not in card_order(client)


@pytest.mark.django_db
@pytest.mark.parametrize('payload', [
    {'order': ['inexistente'], 'hidden': []},
    {'order': [ServiceAccess.CONTACTS, ServiceAccess.CONTACTS], 'hidden': []},
    {'order': 'contacts', 'hidden': []},
    {'order': [ServiceAccess.CONTACTS], 'hidden': [1]},
])
def test_layout_api_rejects_invalid_lists(client, payload):
    user = make_user()
    client.force_login(user)

    assert save_layout(client, payload).status_code == 400
    assert not HomeLayout.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_reset_goes_back_to_the_access_order(client):
    user = make_user()
    register_access(user, ServiceAccess.TICKETS)
    client.force_login(user)
    save_layout(client, {'order': [ServiceAccess.CONTACTS], 'hidden': [ServiceAccess.TICKETS]})

    response = client.delete(reverse('app:home-layout-api'))

    assert response.status_code == 200
    assert response.json()['order'] == [
        ServiceAccess.TICKETS, ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.LIBRARY,
    ]
    assert card_order(client) == response.json()['order']
    assert hidden_cards(client) == []


@pytest.mark.django_db
def test_all_cards_hidden_shows_the_empty_message(client):
    client.force_login(make_user())
    save_layout(client, {
        'order': [],
        'hidden': [ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.TICKETS, ServiceAccess.LIBRARY],
    })

    content = client.get(reverse('app:home')).content.decode()

    assert re.search(r'id="quick-access-empty">', content)


def card_heights(client):
    content = client.get(reverse('app:home')).content.decode()
    return {
        service: int(height)
        for height, service in re.findall(r'data-height="(\d+)" data-default-height="\d+" data-service="([\w-]+)"', content)
    }


@pytest.mark.django_db
def test_cards_start_with_the_same_default_height(client):
    client.force_login(make_user())

    heights = card_heights(client)

    assert set(heights.values()) == {CARD_DEFAULT_HEIGHT}
    assert len(heights) == 4


@pytest.mark.django_db
def test_saved_heights_are_rendered(client):
    client.force_login(make_user())
    response = save_layout(client, {
        'order': [ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.TICKETS],
        'hidden': [],
        'sizes': {ServiceAccess.CONTACTS: 520},
    })

    assert response.status_code == 200
    heights = card_heights(client)
    assert heights[ServiceAccess.CONTACTS] == 520
    assert heights[ServiceAccess.TICKETS] == CARD_DEFAULT_HEIGHT


@pytest.mark.django_db
@pytest.mark.parametrize('sizes', [
    {ServiceAccess.CONTACTS: CARD_MIN_HEIGHT - 1},
    {ServiceAccess.CONTACTS: CARD_MAX_HEIGHT + 1},
    {ServiceAccess.CONTACTS: '300'},
    {ServiceAccess.CONTACTS: 300.5},
    {ServiceAccess.CONTACTS: True},
    {'inexistente': 300},
    [300],
])
def test_layout_api_rejects_invalid_heights(client, sizes):
    user = make_user()
    client.force_login(user)

    response = save_layout(client, {'order': [ServiceAccess.CONTACTS], 'hidden': [], 'sizes': sizes})

    assert response.status_code == 400
    assert not HomeLayout.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_reset_also_drops_the_heights(client):
    client.force_login(make_user())
    save_layout(client, {'order': [ServiceAccess.CONTACTS], 'hidden': [], 'sizes': {ServiceAccess.CONTACTS: 600}})

    client.delete(reverse('app:home-layout-api'))

    assert card_heights(client)[ServiceAccess.CONTACTS] != 600


@pytest.mark.django_db
def test_journey_audit_card_breaks_the_occurrences_down_by_type(client):
    start, end = current_period()
    competency = Competency.objects.create(start_date=start, end_date=end)
    for employee, kind in [('1', Occurrence.ABSENCE), ('2', Occurrence.ABSENCE), ('1', Occurrence.OVERTIME)]:
        Occurrence.objects.create(
            competency=competency, day=start, employee_id=employee, employee_name='Fulano', location='Matriz',
            type=kind, evidence='-',
        )
    client.force_login(make_user('view_competency'))

    content = card(client, ServiceAccess.JOURNEY_AUDIT)

    assert re.search(r'Falta a confirmar</strong></span>\s*<span[^>]*>2 pendentes</span>\s*<span[^>]*>2</span>', content)
    assert re.search(r'Horas extras</strong></span>\s*<span[^>]*>1</span>', content)
    assert content.index('Falta a confirmar') < content.index('Horas extras')


@pytest.mark.django_db
def test_customize_mode_can_be_cancelled_and_restores_without_the_server(client):
    user = make_user()
    register_access(user, ServiceAccess.TICKETS)
    client.force_login(user)

    content = client.get(reverse('app:home')).content.decode()

    assert 'id="quick-access-cancel"' in content
    assert 'Esc ou Cancelar desfaz as alterações' in content
    # O "Restaurar padrão" monta a ordem dos acessos com o que veio na página
    order = re.search(r'<script id="home-default-order" type="application/json">(.*?)</script>', content).group(1)
    assert json.loads(order) == [
        ServiceAccess.TICKETS, ServiceAccess.CONTACTS, ServiceAccess.NOTIFICATIONS, ServiceAccess.LIBRARY,
    ]
