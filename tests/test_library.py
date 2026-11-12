import json
import re

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from app.models import LibraryDocument, LibraryFolder, ServiceAccess, User
from app.utils.library import MAX_FILE_SIZE, TEXT_PREVIEW_BYTES


DOCUMENT_PERMISSIONS = ('add_librarydocument', 'change_librarydocument', 'delete_librarydocument')

FOLDER_PERMISSIONS = ('add_libraryfolder', 'change_libraryfolder', 'delete_libraryfolder')


# Os arquivos enviados nos testes vão para uma pasta temporária, e não para o
# media_root de verdade
@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def make_user(*codenames, username='colaborador'):
    user = User.objects.create_user(username=username, password='senha')
    user.user_permissions.set(Permission.objects.filter(content_type__app_label='app', codename__in=codenames))
    return user


def make_document(folder, title='Manual', content=b'conteudo', name='manual.pdf', **kwargs):
    document = LibraryDocument(folder=folder, title=title, file_name=name, file_size=len(content), **kwargs)
    document.file.save(name, ContentFile(content), save=False)
    document.save()
    return document


def page_data(client, script_id):
    content = client.get(reverse('app:library')).content.decode()
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>', content, re.S)
    assert match, f'{script_id} ausente'
    return json.loads(match.group(1))


def visible_titles(client):
    return sorted(document['title'] for document in page_data(client, 'library-documents'))


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type='application/json')


@pytest.fixture
def folder(db):
    return LibraryFolder.objects.create(name='Procedimentos')


@pytest.fixture
def manager(client):
    user = make_user(*DOCUMENT_PERMISSIONS, *FOLDER_PERMISSIONS, username='gestor')
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_page_requires_login(client):
    response = client.get(reverse('app:library'))
    assert response.status_code == 302
    assert reverse('app:login') in response.url


@pytest.mark.django_db
def test_page_and_menu_are_open_to_everyone_even_without_documents(client):
    client.force_login(make_user())

    assert client.get(reverse('app:library')).status_code == 200
    home = client.get(reverse('app:home')).content.decode()
    assert f'href="{reverse("app:library")}"' in home
    assert f'data-service="{ServiceAccess.LIBRARY}"' in home


@pytest.mark.django_db
def test_page_counts_the_access(client):
    user = make_user()
    client.force_login(user)

    client.get(reverse('app:library'))

    assert ServiceAccess.objects.get(user=user, service=ServiceAccess.LIBRARY).count == 1


@pytest.mark.django_db
def test_documents_follow_the_recipients_like_the_notifications(client, folder):
    user = make_user()
    other = make_user(username='outro')
    group = Group.objects.create(name='Financeiro')
    user.groups.add(group)

    make_document(folder, title='Para todos')
    make_document(folder, title='Para você').users.add(user)
    make_document(folder, title='Para o grupo').groups.add(group)
    make_document(folder, title='Para outro').users.add(other)
    other_group = make_document(folder, title='Para outro grupo')
    other_group.groups.add(Group.objects.create(name='Diretoria'))
    client.force_login(user)

    assert visible_titles(client) == ['Para o grupo', 'Para todos', 'Para você']


@pytest.mark.django_db
def test_recipients_and_downloads_stay_with_who_manages(client, folder):
    make_document(folder, title='Para todos')
    client.force_login(make_user())

    document = page_data(client, 'library-documents')[0]

    assert 'recipients' not in document
    assert 'downloads' not in document
    assert page_data(client, 'library-recipients') == {'users': [], 'groups': []}


@pytest.mark.django_db
def test_folders_without_released_documents_are_hidden(client, folder):
    empty = LibraryFolder.objects.create(name='Vazia')
    private = LibraryFolder.objects.create(name='Diretoria')
    make_document(folder, title='Para todos')
    make_document(private, title='Restrito').users.add(make_user(username='outro'))
    client.force_login(make_user())

    folders = [item['name'] for item in page_data(client, 'library-folders')]

    assert folders == ['Procedimentos']
    assert empty.name not in folders


@pytest.mark.django_db
def test_managers_see_every_folder_and_document(client, manager, folder):
    LibraryFolder.objects.create(name='Vazia')
    make_document(folder, title='Restrito').users.add(make_user(username='outro'))

    assert visible_titles(client) == ['Restrito']
    assert [item['name'] for item in page_data(client, 'library-folders')] == ['Procedimentos', 'Vazia']
    document = page_data(client, 'library-documents')[0]
    assert document['recipients'] == ['outro']


@pytest.mark.django_db
def test_author_sees_the_document_they_sent(client, folder):
    author = make_user('add_librarydocument', username='autor')
    make_document(folder, title='Restrito', created_by=author).users.add(make_user(username='outro'))
    client.force_login(author)

    assert visible_titles(client) == ['Restrito']


@pytest.mark.django_db
def test_download_sends_the_original_name_and_counts(client, folder):
    document = make_document(folder, content=b'%PDF-teste', name='Manual de Integração.pdf')
    client.force_login(make_user())

    response = client.get(reverse('app:library-download', args=[document.id]))

    assert response.status_code == 200
    assert b''.join(response.streaming_content) == b'%PDF-teste'
    assert 'attachment' in response['Content-Disposition']
    assert 'Manual%20de%20Integra%C3%A7%C3%A3o.pdf' in response['Content-Disposition']
    document.refresh_from_db()
    assert document.downloads == 1


@pytest.mark.django_db
def test_download_refuses_documents_not_released(client, folder):
    document = make_document(folder)
    document.users.add(make_user(username='outro'))
    client.force_login(make_user())

    assert client.get(reverse('app:library-download', args=[document.id])).status_code == 404


@pytest.mark.django_db
def test_download_requires_login(client, folder):
    document = make_document(folder)
    response = client.get(reverse('app:library-download', args=[document.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_management_actions_follow_the_permissions(client, folder):
    client.force_login(make_user())
    document = make_document(folder)
    upload = SimpleUploadedFile('novo.pdf', b'x')

    assert post_json(client, reverse('app:library-folders-api'), {'name': 'Nova'}).status_code == 403
    assert post_json(client, reverse('app:library-folder-api', args=[folder.id]), {'name': 'Outra'}).status_code == 403
    assert client.delete(reverse('app:library-folder-api', args=[folder.id])).status_code == 403
    assert client.post(reverse('app:library-documents-api'), {
        'title': 'Novo', 'folder': folder.id, 'file': upload,
    }).status_code == 403
    assert client.post(reverse('app:library-document-api', args=[document.id]), {
        'title': 'Outro', 'folder': folder.id,
    }).status_code == 403
    assert client.delete(reverse('app:library-document-api', args=[document.id])).status_code == 403

    content = client.get(reverse('app:library')).content.decode()
    assert 'id="open-folder-modal"' not in content
    assert 'id="open-document-modal"' not in content
    assert '<dialog id="document-modal"' not in content


@pytest.mark.django_db
def test_api_rejects_anonymous(client, folder):
    assert post_json(client, reverse('app:library-folders-api'), {'name': 'Nova'}).status_code == 401


@pytest.mark.django_db
def test_create_rename_and_delete_folder(client, manager):
    response = post_json(client, reverse('app:library-folders-api'), {'name': '  Recursos Humanos '})
    assert response.status_code == 201
    folder = LibraryFolder.objects.get(id=response.json()['folder']['id'])
    assert folder.name == 'Recursos Humanos'

    response = post_json(client, reverse('app:library-folder-api', args=[folder.id]), {'name': 'RH'})
    assert response.status_code == 200
    folder.refresh_from_db()
    assert folder.name == 'RH'

    assert client.delete(reverse('app:library-folder-api', args=[folder.id])).status_code == 200
    assert not LibraryFolder.objects.exists()


@pytest.mark.django_db
def test_folder_names_do_not_repeat_ignoring_case(client, manager, folder):
    response = post_json(client, reverse('app:library-folders-api'), {'name': 'PROCEDIMENTOS'})

    assert response.status_code == 400
    assert response.json()['detail'] == 'Já existe uma pasta com este nome.'


@pytest.mark.django_db
def test_folder_with_documents_is_not_deleted(client, manager, folder):
    make_document(folder)

    response = client.delete(reverse('app:library-folder-api', args=[folder.id]))

    assert response.status_code == 400
    assert 'Mova ou exclua os documentos' in response.json()['detail']
    assert LibraryFolder.objects.filter(id=folder.id).exists()


@pytest.mark.django_db
def test_create_document_with_recipients(client, manager, folder, media_root):
    user = make_user(username='destinatario')
    group = Group.objects.create(name='Financeiro')

    response = client.post(reverse('app:library-documents-api'), {
        'title': 'Política de Viagens',
        'description': 'Regras de reembolso',
        'folder': folder.id,
        'file': SimpleUploadedFile('Política.pdf', b'%PDF-politica'),
        'users': [user.id],
        'groups': [group.id],
    })

    assert response.status_code == 201
    document = LibraryDocument.objects.get()
    assert document.file_name == 'Política.pdf'
    assert document.file_size == len(b'%PDF-politica')
    assert document.created_by == manager
    assert list(document.users.all()) == [user]
    assert list(document.groups.all()) == [group]
    # O nome no disco é sorteado: o original só volta no download
    assert 'Política' not in document.file.name
    assert (media_root / document.file.name).read_bytes() == b'%PDF-politica'
    assert response.json()['document']['recipients'] == ['destinatario', 'Financeiro']


@pytest.mark.django_db
def test_document_requires_a_file_and_a_folder(client, manager, folder):
    response = client.post(reverse('app:library-documents-api'), {'title': 'Sem arquivo', 'folder': folder.id})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Selecione o arquivo do documento.'

    response = client.post(reverse('app:library-documents-api'), {
        'title': 'Sem pasta', 'file': SimpleUploadedFile('a.pdf', b'x'),
    })
    assert response.status_code == 400
    assert response.json()['detail'] == 'Escolha a pasta do documento.'


@pytest.mark.django_db
def test_document_refuses_large_files(client, manager, folder):
    response = client.post(reverse('app:library-documents-api'), {
        'title': 'Grande', 'folder': folder.id,
        'file': SimpleUploadedFile('grande.pdf', b'0' * (MAX_FILE_SIZE + 1)),
    })

    assert response.status_code == 400
    assert response.json()['detail'] == 'O arquivo passa de 50 MB.'
    assert not LibraryDocument.objects.exists()


@pytest.mark.django_db
def test_document_refuses_files_outside_the_allowed_types(client, manager, folder):
    response = client.post(reverse('app:library-documents-api'), {
        'title': 'Programa', 'folder': folder.id, 'file': SimpleUploadedFile('instalar.bat', b'echo'),
    })

    assert response.status_code == 400
    assert response.json()['detail'] == 'Este tipo de arquivo não é aceito na biblioteca.'


@pytest.mark.django_db
def test_document_accepts_executables(client, manager, folder):
    response = client.post(reverse('app:library-documents-api'), {
        'title': 'Instalador', 'folder': folder.id, 'file': SimpleUploadedFile('Instalar.EXE', b'MZ'),
    })

    assert response.status_code == 201
    assert LibraryDocument.objects.get().file_name == 'Instalar.EXE'
    document = response.json()['document']
    assert document['extension'] == 'exe'
    assert document['icon'] == 'fa-gears'
    # O executável só sai pelo download: o navegador nunca o abre dentro do portal
    assert document['preview'] is None
    assert document['preview_url'] is None
    assert '.exe' in client.get(reverse('app:library')).content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize('name, kind', [
    ('foto.PNG', 'image'), ('manual.pdf', 'pdf'), ('dados.csv', 'text'), ('planilha.xlsx', None), ('video.mp4', None),
])
def test_documents_say_which_preview_they_have(client, folder, name, kind):
    document = make_document(folder, name=name)
    client.force_login(make_user())

    data = page_data(client, 'library-documents')[0]

    assert data['preview'] == kind
    if kind:
        assert data['preview_url'].startswith(reverse('app:library-preview', args=[document.id]) + '?v=')
    else:
        assert data['preview_url'] is None


@pytest.mark.django_db
def test_preview_shows_the_file_inline_without_counting_a_download(client, folder):
    document = make_document(folder, content=b'%PDF-teste', name='Manual.pdf')
    client.force_login(make_user())

    response = client.get(reverse('app:library-preview', args=[document.id]))

    assert response.status_code == 200
    assert b''.join(response.streaming_content) == b'%PDF-teste'
    assert response['Content-Type'] == 'application/pdf'
    assert response['Content-Disposition'].startswith('inline')
    assert response['X-Content-Type-Options'] == 'nosniff'
    assert 'private' in response['Cache-Control']
    document.refresh_from_db()
    assert document.downloads == 0


@pytest.mark.django_db
def test_only_the_preview_can_be_framed_and_only_by_the_portal(client, folder):
    document = make_document(folder, name='manual.pdf')
    client.force_login(make_user())

    preview = client.get(reverse('app:library-preview', args=[document.id]))
    page = client.get(reverse('app:library'))

    assert "frame-ancestors 'self'" in preview['Content-Security-Policy']
    assert preview['X-Frame-Options'] == 'SAMEORIGIN'
    assert "frame-ancestors 'none'" in page['Content-Security-Policy']
    assert re.search(r"frame-src [^;]*'self'", page['Content-Security-Policy'])


@pytest.mark.django_db
def test_preview_type_comes_from_the_extension_not_from_the_content(client, folder):
    document = make_document(folder, content=b'<script>alert(1)</script>', name='foto.png')
    client.force_login(make_user())

    response = client.get(reverse('app:library-preview', args=[document.id]))

    assert response['Content-Type'] == 'image/png'


@pytest.mark.django_db
def test_text_preview_sends_only_the_beginning_as_plain_text(client, folder):
    document = make_document(folder, content='ação;'.encode() * 2000, name='dados.csv')
    client.force_login(make_user())

    response = client.get(reverse('app:library-preview', args=[document.id]))

    assert response['Content-Type'] == 'text/plain; charset=utf-8'
    assert response.content.decode().startswith('ação;ação;')
    assert len(response.content) <= TEXT_PREVIEW_BYTES


@pytest.mark.django_db
def test_text_preview_reads_files_saved_by_windows(client, folder):
    document = make_document(folder, content='Descrição;Preço'.encode('cp1252'), name='dados.csv')
    client.force_login(make_user())

    response = client.get(reverse('app:library-preview', args=[document.id]))

    assert response.content.decode() == 'Descrição;Preço'


@pytest.mark.django_db
@pytest.mark.parametrize('name', ['instalar.exe', 'contrato.docx', 'pacote.zip', 'video.mp4'])
def test_preview_refuses_files_the_browser_should_not_open(client, folder, name):
    document = make_document(folder, name=name)
    client.force_login(make_user())

    assert client.get(reverse('app:library-preview', args=[document.id])).status_code == 404


@pytest.mark.django_db
def test_preview_refuses_documents_not_released(client, folder):
    document = make_document(folder, name='manual.pdf')
    document.users.add(make_user(username='outro'))
    client.force_login(make_user())

    assert client.get(reverse('app:library-preview', args=[document.id])).status_code == 404


@pytest.mark.django_db
def test_preview_requires_login(client, folder):
    document = make_document(folder, name='manual.pdf')
    response = client.get(reverse('app:library-preview', args=[document.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_editing_without_a_new_file_keeps_the_current_one(client, manager, folder):
    other_folder = LibraryFolder.objects.create(name='Segurança')
    document = make_document(folder, content=b'original', name='manual.pdf')
    document.users.add(make_user(username='outro'))
    stored = document.file.name

    response = client.post(reverse('app:library-document-api', args=[document.id]), {
        'title': 'Manual Atualizado', 'folder': other_folder.id, 'description': '',
    })

    assert response.status_code == 200
    document.refresh_from_db()
    assert document.title == 'Manual Atualizado'
    assert document.folder == other_folder
    assert document.file.name == stored
    assert document.file_name == 'manual.pdf'
    # Sem destinatários marcados o documento passa a valer para todos
    assert not document.users.exists()


@pytest.mark.django_db
def test_replacing_the_file_deletes_the_old_one(client, manager, folder, media_root, django_capture_on_commit_callbacks):
    document = make_document(folder, content=b'antigo', name='antigo.pdf')
    old = media_root / document.file.name

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse('app:library-document-api', args=[document.id]), {
            'title': document.title, 'folder': folder.id, 'file': SimpleUploadedFile('novo.docx', b'novo'),
        })

    assert response.status_code == 200
    document.refresh_from_db()
    assert document.file_name == 'novo.docx'
    assert document.file_size == 4
    assert (media_root / document.file.name).read_bytes() == b'novo'
    assert not old.exists()


@pytest.mark.django_db
def test_deleting_the_document_deletes_the_file(client, manager, folder, media_root, django_capture_on_commit_callbacks):
    document = make_document(folder)
    stored = media_root / document.file.name

    with django_capture_on_commit_callbacks(execute=True):
        response = client.delete(reverse('app:library-document-api', args=[document.id]))

    assert response.status_code == 200
    assert not LibraryDocument.objects.exists()
    assert not stored.exists()


@pytest.mark.django_db
def test_home_card_lists_only_released_documents(client, folder):
    user = make_user()
    make_document(folder, title='Código de Conduta')
    make_document(folder, title='Restrito').users.add(make_user(username='outro'))
    client.force_login(user)

    content = client.get(reverse('app:home')).content.decode()
    card = re.search(rf'data-service="{ServiceAccess.LIBRARY}">(.*?)</article>', content, re.S).group(1)

    assert 'Código de Conduta' in card
    assert 'Restrito' not in card
    assert '1 documento disponível' in card


@pytest.mark.django_db
def test_home_card_without_documents_says_so(client):
    client.force_login(make_user())

    content = client.get(reverse('app:home')).content.decode()
    card = re.search(rf'data-service="{ServiceAccess.LIBRARY}">(.*?)</article>', content, re.S).group(1)

    assert 'Nenhum documento foi liberado para você ainda.' in card
    assert '0 documentos disponíveis' in card
