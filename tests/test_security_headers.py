import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_login_page_carries_the_security_headers(client):
    response = client.get(reverse('app:login'))

    assert 'camera=()' in response['Permissions-Policy']

    csp = response['Content-Security-Policy']
    # O script só sai daqui e do CDN; o resto do mundo não executa nada nesta página.
    assert "script-src 'self' https://cdnjs.cloudflare.com" in csp
    assert "frame-ancestors 'none'" in csp
