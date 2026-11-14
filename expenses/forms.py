from decimal import Decimal

from django import forms
from django.utils import timezone

from app.models import CostCenter
from expenses.models import IgnoredWord
from expenses.receipts import clean_cnpj


class IgnoredWordForm(forms.ModelForm):
    # O tipo também é procurado por escrito dentro da descrição do item: com uma
    # ou duas letras ele tiraria quase tudo do reembolso
    MIN_LENGTH = 3

    class Meta:
        model = IgnoredWord
        fields = ['word']
        error_messages = {'word': {'required': 'Informe o tipo de item.'}}

    def clean_word(self):
        # Guardada em minúsculas e sem espaços sobrando: "Cerveja" e "cerveja " são a mesma
        word = ' '.join(self.cleaned_data['word'].split()).lower()
        if len(word) < self.MIN_LENGTH:
            raise forms.ValidationError(f'O tipo precisa de pelo menos {self.MIN_LENGTH} letras.')
        return word


class ExpenseHeaderForm(forms.Form):
    """O cabeçalho da nota. Nada é obrigatório: o funcionário não é barrado pelo que a nota não traz."""
    merchant = forms.CharField(max_length=150, required=False)
    cnpj = forms.CharField(max_length=30, required=False)
    issue_date = forms.DateField(required=False, error_messages={'invalid': 'Informe uma data válida para a nota.'})

    def clean_cnpj(self):
        cnpj = clean_cnpj(self.cleaned_data['cnpj'])
        if cnpj and len(cnpj) != 14:
            raise forms.ValidationError('CNPJ incompleto: confira os 14 caracteres ou deixe o campo em branco.')
        return cnpj

    def clean_issue_date(self):
        issue_date = self.cleaned_data['issue_date']
        if issue_date and issue_date > timezone.localdate():
            raise forms.ValidationError('A data da nota não pode estar no futuro.')
        return issue_date


class ExpenseItemForm(forms.Form):
    # Com o id o item é alterado; sem ele, criado
    id = forms.IntegerField(required=False)
    description = forms.CharField(max_length=200, error_messages={
        'required': 'Informe a descrição de todos os itens.',
        'max_length': 'A descrição do item passa de 200 caracteres.',
    })
    quantity = forms.DecimalField(
        max_digits=10, decimal_places=3, min_value=Decimal('0.001'), required=False,
        error_messages={'invalid': 'Informe uma quantidade válida.', 'min_value': 'Informe uma quantidade válida.'},
    )
    amount = forms.DecimalField(max_digits=9, decimal_places=2, min_value=0, error_messages={
        'required': 'Informe o valor de todos os itens.',
        'invalid': 'Informe um valor válido para o item.',
        'min_value': 'O valor do item não pode ser negativo.',
    })
    # Só o aprovador decide isto; do funcionário o campo nem é lido
    ignored = forms.BooleanField(required=False)

    def clean_quantity(self):
        return self.cleaned_data['quantity'] or Decimal(1)


class ReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=[('approve', 'Aprovar'), ('reject', 'Rejeitar'), ('correction', 'Pedir correção')],
        error_messages={'required': 'Informe a ação.', 'invalid_choice': 'Ação inválida.'},
    )
    note = forms.CharField(max_length=2000, required=False, error_messages={
        'max_length': 'A observação passa de 2000 caracteres.',
    })
    photo_checked = forms.BooleanField(required=False)
    # O inativo só é aceito se já era o da despesa; quem confere é o review_expense
    cost_center = forms.ModelChoiceField(
        queryset=CostCenter.objects.all(), required=False,
        error_messages={'invalid_choice': 'Escolha um centro de custo válido.'},
    )
