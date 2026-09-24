from django import forms
from app.models import Contact, Toner, TonerMovement


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
            self.add_error('number', 'Informe o número do contato.')
        return cleaned_data
