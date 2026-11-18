from decimal import Decimal

from django import forms
from django.utils import timezone

from expenses.models import Expense, ExpenseType
from expenses.validators import clean_access_key, clean_cnpj, clean_number, valid_access_key, valid_cnpj


MAX_ITEMS = 100


class ExpenseDataForm(forms.Form):
    """Os dados da nota como a conferência os confere e edita."""
    cnpj = forms.CharField(required=False, max_length=30, label='CNPJ do emitente')
    access_key = forms.CharField(required=False, max_length=80, label='Chave de acesso')
    number = forms.CharField(required=False, max_length=40, label='Número da nota')
    issue_date = forms.DateField(required=False, input_formats=['%Y-%m-%d'], label='Data da nota')
    total = forms.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=0, label='Valor total')
    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.all(), required=False, label='Tipo',
        error_messages={'invalid_choice': 'Escolha um tipo da lista.'},
    )

    def __init__(self, *args, expense=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expense = expense

    def clean_cnpj(self):
        cnpj = clean_cnpj(self.cleaned_data['cnpj'])
        if cnpj and not valid_cnpj(cnpj):
            raise forms.ValidationError('CNPJ inválido: confira os dígitos.')
        return cnpj

    def clean_access_key(self):
        key = clean_access_key(self.cleaned_data['access_key'])
        if key and not valid_access_key(key):
            raise forms.ValidationError('Chave de acesso inválida: confira os 44 dígitos.')
        others = Expense.objects.filter(access_key=key)
        if self.expense is not None:
            others = others.exclude(pk=self.expense.pk)
        if key and others.exists():
            raise forms.ValidationError('Já existe outra nota com esta chave de acesso.')
        return key

    def clean_number(self):
        number = clean_number(self.cleaned_data['number'])
        if len(number) > 20:
            raise forms.ValidationError('O número da nota tem no máximo 20 caracteres.')
        return number

    def clean_issue_date(self):
        issue_date = self.cleaned_data['issue_date']
        if issue_date and issue_date > timezone.localdate():
            raise forms.ValidationError('A data da nota não pode ser futura.')
        return issue_date


class ExpenseItemForm(forms.Form):
    id = forms.IntegerField(required=False)
    description = forms.CharField(max_length=200, label='Descrição')
    quantity = forms.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal('0.001'), label='Quantidade')
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, label='Valor')
    non_reimbursable = forms.BooleanField(required=False)


def first_error(form):
    field, errors = next(iter(form.errors.items()))
    label = form.fields[field].label if field in form.fields else ''
    return f'{label}: {errors[0]}' if label else errors[0]
