"""
A Biblioteca: os documentos que os administradores liberam, em pastas.

A liberação segue a das notificações: o documento vai para os usuários e os
grupos escolhidos, e sem nenhum dos dois vale para todos. Quem edita ou exclui
documentos vê todos eles, já que precisa alcançá-los para isso, e o autor
sempre vê o que enviou.
"""
import os

from django.contrib.auth.models import Group
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone

from app.models import LibraryDocument, LibraryFolder, User
from app.utils.notifications.delivery import author_name


# O mesmo limite do nginx para as rotas de envio: acima dele o upload nem chega
# ao django
MAX_FILE_SIZE = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = (
    'pdf', 'doc', 'docx', 'odt', 'rtf', 'txt', 'md',
    'xls', 'xlsx', 'xlsm', 'ods', 'csv',
    'ppt', 'pptx', 'odp',
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'zip', 'rar', '7z',
    'msg', 'eml', 'xml', 'json',
    'dwg', 'dxf', 'mp4',
)

MANAGE_DOCUMENT_PERMISSIONS = ('app.change_librarydocument', 'app.delete_librarydocument')

# Quem cria ou move documentos, ou cuida das pastas, precisa ver todas elas,
# inclusive as vazias
SEE_ALL_FOLDERS_PERMISSIONS = (
    'app.add_librarydocument', 'app.change_librarydocument',
    'app.add_libraryfolder', 'app.change_libraryfolder', 'app.delete_libraryfolder',
)


def manages_documents(user):
    return any(user.has_perm(perm) for perm in MANAGE_DOCUMENT_PERMISSIONS)


def library_permissions(user):
    return {
        'add_folder': user.has_perm('app.add_libraryfolder'),
        'change_folder': user.has_perm('app.change_libraryfolder'),
        'delete_folder': user.has_perm('app.delete_libraryfolder'),
        'add_document': user.has_perm('app.add_librarydocument'),
        'change_document': user.has_perm('app.change_librarydocument'),
        'delete_document': user.has_perm('app.delete_librarydocument'),
    }


def visible_documents(user):
    documents = LibraryDocument.objects.select_related('folder', 'created_by')
    if manages_documents(user):
        return documents

    through_users = LibraryDocument.users.through
    through_groups = LibraryDocument.groups.through

    # Sem usuários nem grupos o documento vale para todos
    for_everyone = ~Exists(through_users.objects.filter(librarydocument=OuterRef('pk'))) & ~Exists(
        through_groups.objects.filter(librarydocument=OuterRef('pk'))
    )
    for_user = Exists(through_users.objects.filter(librarydocument=OuterRef('pk'), user=user))
    for_groups = Exists(through_groups.objects.filter(librarydocument=OuterRef('pk'), group__user=user))

    return documents.filter(for_everyone | for_user | for_groups | Q(created_by=user))


def visible_folders(user, documents):
    """As pastas da tela: todas para quem as organiza, e as que têm algo liberado para os demais."""
    if any(user.has_perm(perm) for perm in SEE_ALL_FOLDERS_PERMISSIONS):
        return LibraryFolder.objects.all()
    # Mostrar uma pasta vazia contaria a quem não recebeu nada que ela existe
    return LibraryFolder.objects.filter(id__in={document.folder_id for document in documents})


FILE_ICONS = {
    'fa-file-pdf': ('pdf',),
    'fa-file-word': ('doc', 'docx', 'odt', 'rtf'),
    'fa-file-excel': ('xls', 'xlsx', 'xlsm', 'ods'),
    'fa-file-csv': ('csv',),
    'fa-file-powerpoint': ('ppt', 'pptx', 'odp'),
    'fa-file-image': ('png', 'jpg', 'jpeg', 'gif', 'webp'),
    'fa-file-zipper': ('zip', 'rar', '7z'),
    'fa-file-lines': ('txt', 'md'),
    'fa-envelope': ('msg', 'eml'),
    'fa-file-code': ('xml', 'json'),
    'fa-compass-drafting': ('dwg', 'dxf'),
    'fa-file-video': ('mp4',),
}

ICON_BY_EXTENSION = {extension: icon for icon, extensions in FILE_ICONS.items() for extension in extensions}


def file_extension(name):
    return os.path.splitext(name)[1].lstrip('.').lower()


def file_icon(name):
    return ICON_BY_EXTENSION.get(file_extension(name), 'fa-file')


def serialize_folder(folder):
    return {'id': folder.id, 'name': folder.name}


def shows_details(user, document):
    # Os destinatários e os downloads são de quem cuida do documento
    return manages_documents(user) or (document.created_by_id is not None and document.created_by_id == user.id)


def serialize_document(document, user):
    data = {
        'id': document.id,
        'title': document.title,
        'description': document.description,
        'folder_id': document.folder_id,
        'folder': document.folder.name,
        'file_name': document.file_name,
        'extension': file_extension(document.file_name),
        'icon': file_icon(document.file_name),
        'size': document.file_size,
        'author': author_name(document.created_by),
        'updated_at': timezone.localtime(document.updated_at).strftime('%d/%m/%Y'),
        'download_url': reverse('app:library-download', args=[document.id]),
    }
    if shows_details(user, document):
        users = list(document.users.all())
        groups = list(document.groups.all())
        data.update({
            'user_ids': [recipient.id for recipient in users],
            'group_ids': [group.id for group in groups],
            'recipients': [author_name(recipient) for recipient in users] + [group.name for group in groups],
            'downloads': document.downloads,
        })
    return data


def recipient_choices():
    users = sorted(
        ({'id': user.id, 'name': author_name(user)} for user in User.objects.filter(is_active=True)),
        key=lambda user: user['name'].lower(),
    )
    groups = [{'id': group.id, 'name': group.name} for group in Group.objects.order_by('name')]
    return {'users': users, 'groups': groups}
