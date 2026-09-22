from django import forms
from app.models import Toner, TonerMovement


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(
        widget=forms.PasswordInput()
    )


class TonerForm(forms.ModelForm):
    class Meta:
        model = Toner
        fields = ['name', 'location', 'observations', 'minimum_quantity']


class TonerMovementForm(forms.ModelForm):
    quantity = forms.IntegerField(min_value=1)

    class Meta:
        model = TonerMovement
        fields = ['type', 'quantity', 'reason']
