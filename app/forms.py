from django import forms
from django.utils import timezone
from app.models import Contact, Notification, Toner, TonerMovement


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

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('user') and not cleaned_data.get('name', '').strip():
            self.add_error('name', 'Informe um nome ou selecione um usuário.')
        if not cleaned_data.get('number', '').strip():
            self.add_error('number', 'Informe o ramal.')
        return cleaned_data


class NotificationForm(forms.ModelForm):
    start_at = forms.DateTimeField(
        label='Exibir a partir de',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
    )
    end_at = forms.DateTimeField(
        label='Exibir até', required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
    )

    class Meta:
        model = Notification
        fields = ['title', 'message', 'level', 'users', 'groups', 'start_at', 'end_at', 'is_active']

    def __init__(self, *args, **kwargs):
        if not args and 'initial' not in kwargs:
            kwargs['initial'] = {'start_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
        super().__init__(*args, **kwargs)
