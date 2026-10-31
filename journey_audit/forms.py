from django import forms

from journey_audit.models import BankHoursNote, OccurrenceTreatment, SourceReport


class JourneyReportForm(forms.Form):
    # O mesmo limite do nginx para esta rota: acima dele o upload nem chega aqui
    MAX_SIZE = 20 * 1024 * 1024

    start_date = forms.DateField(error_messages={'required': 'Informe o início da competência.'})
    end_date = forms.DateField(error_messages={'required': 'Informe o fim da competência.'})
    type = forms.ChoiceField(choices=SourceReport.TYPES)
    file = forms.FileField(error_messages={'required': 'Selecione o arquivo do relatório.'})

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > self.MAX_SIZE:
            raise forms.ValidationError('O arquivo passa de 20 MB.')
        return file

    def clean(self):
        cleaned_data = super().clean()
        start, end = cleaned_data.get('start_date'), cleaned_data.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError('O fim da competência deve ser igual ou posterior ao início.')
        return cleaned_data


class OccurrenceTreatmentForm(forms.ModelForm):
    class Meta:
        model = OccurrenceTreatment
        fields = ['treatment', 'responsible', 'note']
        error_messages = {
            'note': {'required': 'Registre uma observação antes de salvar a tratativa.'},
            'responsible': {'required': 'Informe quem realizou a conferência.'},
        }


class BankHoursNoteForm(forms.ModelForm):
    class Meta:
        model = BankHoursNote
        fields = ['employee_id', 'note']
