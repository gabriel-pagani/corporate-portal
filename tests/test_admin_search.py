import pytest
from django.contrib.admin.sites import site
from app.admin import DashboardAdmin, SectorAdmin
from app.models import Dashboard, Sector


# A busca do painel roda pelo get_search_results do próprio admin, que é onde o
# acento é tratado; entrar pela URL exigiria sessão com o segundo fator conferido.
def search(admin_class, model, term):
    results, _ = admin_class(model, site).get_search_results(None, model.objects.all(), term)
    return list(results)


@pytest.mark.django_db
def test_search_without_accent_finds_accented_name():
    sector = Sector.objects.create(name='Logística Pátio')
    assert search(SectorAdmin, Sector, 'logistica patio') == [sector]


@pytest.mark.django_db
def test_search_with_accent_still_finds_the_same_name():
    sector = Sector.objects.create(name='Logística Pátio')
    assert search(SectorAdmin, Sector, 'LOGÍSTICA') == [sector]


@pytest.mark.django_db
def test_search_reaches_the_accented_name_of_a_related_record():
    dashboard = Dashboard.objects.create(title='Vendas', sector=Sector.objects.create(name='Almoxarifado Térreo'))
    assert search(DashboardAdmin, Dashboard, 'terreo') == [dashboard]


@pytest.mark.django_db
def test_search_that_matches_nothing_stays_empty():
    Sector.objects.create(name='Logística Pátio')
    assert search(SectorAdmin, Sector, 'mariana') == []
