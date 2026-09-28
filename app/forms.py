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
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex: Recepção'}),
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
