from datetime import timedelta
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone
from app.models import User, Notification


def unread_ids(client):
    response = client.get(reverse('app:notifications-api'))
    assert response.status_code == 200
    return [notification['id'] for notification in response.json()['notifications']]


@pytest.fixture
def user(client):
    user = User.objects.create_user(username='colaborador', password='senha')
    client.force_login(user)
    return user


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username='outro', password='senha')


@pytest.mark.django_db
def test_api_rejects_anonymous(client):
    assert client.get(reverse('app:notifications-api')).status_code == 401


@pytest.mark.django_db
def test_without_recipients_goes_to_everyone(client, user):
    notification = Notification.objects.create(title='Manutenção', message='Sistema fora do ar às 18h')
    assert unread_ids(client) == [notification.id]


@pytest.mark.django_db
def test_targets_only_selected_users_and_groups(client, user, other_user):
    group = Group.objects.create(name='Financeiro')
    user.groups.add(group)

    to_user = Notification.objects.create(title='Para você', message='-')
    to_user.users.add(user)
    to_group = Notification.objects.create(title='Para o grupo', message='-')
    to_group.groups.add(group)
    to_other = Notification.objects.create(title='Para outro', message='-')
    to_other.users.add(other_user)

    assert sorted(unread_ids(client)) == sorted([to_user.id, to_group.id])


@pytest.mark.django_db
def test_respects_period_and_active_flag(client, user):
    now = timezone.now()
    Notification.objects.create(title='Futura', message='-', start_at=now + timedelta(hours=1))
    Notification.objects.create(title='Expirada', message='-', start_at=now - timedelta(days=2), end_at=now - timedelta(days=1))
    Notification.objects.create(title='Inativa', message='-', is_active=False)
    current = Notification.objects.create(title='Vigente', message='-', end_at=now + timedelta(days=1))

    assert unread_ids(client) == [current.id]


@pytest.mark.django_db
def test_mark_as_read_hides_only_for_that_user(client, user, other_user):
    notification = Notification.objects.create(title='Aviso', message='-')

    response = client.post(reverse('app:notification-read-api', args=[notification.id]))
    assert response.status_code == 200
    assert unread_ids(client) == []

    client.force_login(other_user)
    assert unread_ids(client) == [notification.id]


@pytest.mark.django_db
def test_cannot_mark_notification_of_someone_else(client, user, other_user):
    notification = Notification.objects.create(title='Privada', message='-')
    notification.users.add(other_user)

    response = client.post(reverse('app:notification-read-api', args=[notification.id]))
    assert response.status_code == 404
    assert not notification.read_by.exists()


@pytest.mark.django_db
def test_pages_include_notifications_only_when_logged_in(client, user):
    assert b'id="notifications"' in client.get(reverse('app:home')).content

    client.logout()
    assert b'id="notifications"' not in client.get(reverse('app:login')).content
