import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from app.models import User


@pytest.mark.django_db
def test_every_signed_in_page_has_the_portal_confirmation(client):
    client.force_login(User.objects.create_user(username='colaborador', password='senha'))

    content = client.get(reverse('app:home')).content.decode()
    assert 'global/js/confirm.js' in content and 'global/css/confirm.css' in content


def test_apps_do_not_use_the_browser_dialogs():
    # As ações se confirmam na janela do portal (confirmar()), nunca no confirm(), alert() ou prompt() do navegador
    dialog = re.compile(r'(?<![\w.])(?:window\.)?(?:confirm|alert|prompt)\(')
    base = Path(settings.BASE_DIR)
    scripts = [
        path for folder in ('app', 'expenses', 'journey_audit', 'static')
        for path in (base / folder).rglob('*.js') if '.min.' not in path.name
    ]
    assert scripts
    offenders = [
        f'{path.relative_to(base)}:{number}'
        for path in scripts
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if not line.lstrip().startswith('//') and dialog.search(line)
    ]
    assert offenders == []
