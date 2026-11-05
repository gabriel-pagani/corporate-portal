import os
from django import forms
from django.db.models import Q
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import UploadedFile
from app.models import Contact, LibraryDocument, LibraryFolder, Toner, TonerMovement, User
from app.utils.library import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, file_extension


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(
        widget=forms.PasswordInput()
    )


class TonerForm(forms.ModelForm):
    class Meta:
        model = Toner
        fields = ['name', 'location', 'observations', 'minimum_quantity']


# O nome identifica o toner no histórico, então é definido apenas no cadastro
class TonerUpdateForm(forms.ModelForm):
    class Meta:
        model = Toner
        fields = ['location', 'observations', 'minimum_quantity']


class TonerMovementForm(forms.ModelForm):
    quantity = forms.IntegerField(min_value=1)

    class Meta:
        model = TonerMovement
        fields = ['type', 'quantity', 'reason']


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['user', 'name', 'number', 'sector', 'machine']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex: Fulano'}),
            'number': forms.TextInput(attrs={'placeholder': 'Ex: 1234'}),
            'machine': forms.TextInput(attrs={'placeholder': 'Ex: PC-01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].empty_label = 'Selecione um usuário'
        self.fields['sector'].empty_label = 'Selecione um setor'

    def clean(self):
        cleaned_data = super().clean()
        values = (
            cleaned_data.get('user'),
            cleaned_data.get('name', '').strip(),
            cleaned_data.get('number', '').strip(),
            cleaned_data.get('sector'),
            cleaned_data.get('machine', '').strip(),
        )
        if not any(values):
            raise forms.ValidationError('Preencha pelo menos um campo do contato.')
        return cleaned_data


class LibraryFolderForm(forms.ModelForm):
    class Meta:
        model = LibraryFolder
        fields = ['name']
        error_messages = {
            'name': {'required': 'Informe o nome da pasta.'},
        }

    def clean_name(self):
        name = self.cleaned_data['name']
        # "RH" e "rh" seriam duas pastas que ninguém distingue na lista
        if LibraryFolder.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Já existe uma pasta com este nome.')
        return name


class LibraryDocumentForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(queryset=User.objects.filter(is_active=True), required=False)
    groups = forms.ModelMultipleChoiceField(queryset=Group.objects.all(), required=False)

    class Meta:
        model = LibraryDocument
        fields = ['title', 'description', 'folder', 'file', 'users', 'groups']
        error_messages = {
            'title': {'required': 'Informe o título do documento.'},
            'folder': {'required': 'Escolha a pasta do documento.', 'invalid_choice': 'Escolha uma pasta válida.'},
            'file': {'required': 'Selecione o arquivo do documento.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Na edição o arquivo é opcional: sem um novo, fica o que já estava
        self.fields['file'].required = not self.instance.pk
        # Um usuário desativado que já recebeu o documento não sai da lista ao editar
        if self.instance.pk:
            self.fields['users'].queryset = User.objects.filter(
                Q(is_active=True) | Q(library_documents=self.instance)
            ).distinct()

    def clean_file(self):
        file = self.cleaned_data.get('file')
        # Sem envio novo vem o arquivo que já estava salvo, e esse já foi conferido
        if not isinstance(file, UploadedFile):
            return file
        if file.size > MAX_FILE_SIZE:
            raise forms.ValidationError('O arquivo passa de 50 MB.')
        if file_extension(file.name) not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError('Este tipo de arquivo não é aceito na biblioteca.')
        return file

    def save(self, commit=True):
        document = super().save(commit=False)
        file = self.cleaned_data.get('file')
        if isinstance(file, UploadedFile):
            document.file_name = os.path.basename(file.name)[:255]
            document.file_size = file.size
        if commit:
            document.save()
            self.save_m2m()
        return document
