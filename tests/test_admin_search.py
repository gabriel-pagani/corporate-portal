import pytest
from django.contrib.admin.sites import site
from app.admin import ContactAdmin, TonerAdmin
from app.models import Contact, Toner, TonerLocation


# A busca do painel roda pelo get_search_results do próprio admin, que é onde o
# acento é tratado; entrar pela URL exigiria sessão com o segundo fator conferido.
def search(admin_class, model, term):
    results, _ = admin_class(model, site).get_search_results(None, model.objects.all(), term)
    return list(results)


@pytest.mark.django_db
def test_search_without_accent_finds_accented_name():
    contact = Contact.objects.create(name='José Antônio')
    assert search(ContactAdmin, Contact, 'jose antonio') == [contact]


@pytest.mark.django_db
def test_search_with_accent_still_finds_the_same_name():
    contact = Contact.objects.create(name='José Antônio')
    assert search(ContactAdmin, Contact, 'JOSÉ') == [contact]


@pytest.mark.django_db
def test_search_reaches_the_accented_name_of_a_related_record():
    toner = Toner.objects.create(name='CF410A', location=TonerLocation.objects.create(name='Almoxarifado Térreo'))
    assert search(TonerAdmin, Toner, 'terreo') == [toner]


@pytest.mark.django_db
def test_search_that_matches_nothing_stays_empty():
    Contact.objects.create(name='José Antônio')
    assert search(ContactAdmin, Contact, 'mariana') == []
