from django.conf import settings
from django.db import models


class Competency(models.Model):
    start_date = models.DateField(verbose_name='Início')
    end_date = models.DateField(verbose_name='Fim')
    analysed_rows = models.PositiveIntegerField(
        default=0,
        verbose_name='Registros analisados',
        help_text='Linhas do Sumarizado que caíram dentro da competência na última análise.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='Criada por'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criada em')
    finished_at = models.DateTimeField(blank=True, null=True, verbose_name='Conferência finalizada em')
    finished_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='Finalizada por'
    )

    def __str__(self):
        return f'{self.start_date:%d/%m/%Y} a {self.end_date:%d/%m/%Y}'

    class Meta:
        ordering = ['-start_date', '-end_date']
        verbose_name = 'Competência'
        verbose_name_plural = 'Competências'
        constraints = [
            models.UniqueConstraint(
                fields=['start_date', 'end_date'],
                name='unique_competency_period',
                violation_error_message='Já existe uma competência com este período.',
            ),
        ]


class SourceReport(models.Model):
    ODD_PUNCHES = 'I'
    ABSENCES = 'A'
    SUMMARY = 'S'
    TYPES = [
        (ODD_PUNCHES, 'Batidas ímpares'),
        (ABSENCES, 'Ausências'),
        (SUMMARY, 'Sumarizado'),
    ]

    competency = models.ForeignKey(Competency, on_delete=models.CASCADE, related_name='reports', verbose_name='Competência')
    type = models.CharField(max_length=1, choices=TYPES, verbose_name='Relatório')
    file_name = models.CharField(max_length=255, verbose_name='Arquivo')
    # Só as colunas que a análise usa: o relatório é guardado para a competência
    # poder ser analisada de novo quando chegar um dos outros dois
    rows = models.JSONField(default=list, verbose_name='Linhas')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name='Enviado por'
    )
    uploaded_at = models.DateTimeField(auto_now=True, verbose_name='Enviado em')

    def __str__(self):
        return f'{self.get_type_display()} - {self.competency}'

    class Meta:
        ordering = ['competency', 'type']
        verbose_name = 'Relatório do Ahgora'
        verbose_name_plural = 'Relatórios do Ahgora'
        constraints = [
            models.UniqueConstraint(fields=['competency', 'type'], name='unique_report_per_competency'),
        ]


class Occurrence(models.Model):
    ODD_PUNCHES = 'I'
    ABSENCE = 'F'
    MISSING_BREAK = 'M'
    SHORT_BREAK = 'J'
    OVERTIME = 'E'
    LONG_OVERTIME = 'H'
    NEGATIVE_BALANCE = 'S'
    LEAVE = 'A'
    TYPES = [
        (ODD_PUNCHES, 'Batidas ímpares'),
        (ABSENCE, 'Falta a confirmar'),
        (MISSING_BREAK, 'Intervalo sem marcações suficientes'),
        (SHORT_BREAK, 'Intrajornada inferior a 1h'),
        (OVERTIME, 'Horas extras'),
        (LONG_OVERTIME, 'Horas extras acima de 2h'),
        (NEGATIVE_BALANCE, 'Saldo negativo de jornada'),
        (LEAVE, 'Afastamento informado'),
    ]

    ADJUSTED = 'A'
    ADJUSTMENT_REFUSED = 'R'
    ABSENCE_CONFIRMED = 'F'
    JUSTIFIED_CERTIFICATE = 'T'
    JUSTIFIED_DECLARATION = 'D'
    JUSTIFIED_OTHER = 'O'
    SUSPENSION = 'S'
    BREAK_RECORDED = 'L'
    NOT_NEEDED = 'C'
    NOT_APPLICABLE = 'N'
    TREATMENTS = [
        (ADJUSTED, 'Ajuste realizado'),
        (ADJUSTMENT_REFUSED, 'Ajuste recusado — ajuste mensal já utilizado'),
        (ABSENCE_CONFIRMED, 'Falta confirmada'),
        (JUSTIFIED_CERTIFICATE, 'Justificada — atestado'),
        (JUSTIFIED_DECLARATION, 'Justificada — declaração'),
        (JUSTIFIED_OTHER, 'Justificada — outro motivo'),
        (SUSPENSION, 'Suspensão'),
        (BREAK_RECORDED, 'Intervalo lançado'),
        (NOT_NEEDED, 'Não necessário após conferência'),
        (NOT_APPLICABLE, 'Não procede'),
    ]

    # Só estes tipos pedem conferência do RH; os demais são alertas informativos.
    # A tratativa em branco é a ocorrência ainda pendente.
    TREATMENTS_BY_TYPE = {
        ODD_PUNCHES: (ADJUSTED, ADJUSTMENT_REFUSED, NOT_APPLICABLE),
        ABSENCE: (
            ABSENCE_CONFIRMED, JUSTIFIED_CERTIFICATE, JUSTIFIED_DECLARATION, JUSTIFIED_OTHER,
            SUSPENSION, NOT_APPLICABLE,
        ),
        MISSING_BREAK: (BREAK_RECORDED, NOT_NEEDED),
    }

    competency = models.ForeignKey(Competency, on_delete=models.CASCADE, related_name='occurrences', verbose_name='Competência')
    day = models.DateField(verbose_name='Data')
    employee_id = models.CharField(max_length=30, verbose_name='Matrícula')
    employee_name = models.CharField(max_length=150, verbose_name='Colaborador')
    location = models.CharField(max_length=150, verbose_name='Localização')
    scale = models.CharField(max_length=255, blank=True, verbose_name='Escala')
    type = models.CharField(max_length=1, choices=TYPES, verbose_name='Ocorrência')
    evidence = models.TextField(verbose_name='Evidência')
    minutes = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='Minutos',
        help_text='O tempo que a ocorrência mede: as horas extras do dia ou o que faltou para 1h de intervalo.',
    )
    in_reports = models.BooleanField(
        default=True,
        verbose_name='Presente nos relatórios',
        help_text='Desmarcada quando a ocorrência deixa de aparecer num relatório importado depois. '
                  'Ela sai da conferência, mas continua contando na recorrência e no ajuste mensal.',
    )
    treatment = models.CharField(max_length=1, choices=TREATMENTS, blank=True, verbose_name='Tratativa')
    note = models.TextField(blank=True, verbose_name='Observação')
    responsible = models.CharField(max_length=150, blank=True, verbose_name='Responsável')
    treated_at = models.DateTimeField(blank=True, null=True, verbose_name='Tratada em')

    @property
    def is_actionable(self):
        return self.type in self.TREATMENTS_BY_TYPE

    def __str__(self):
        return f'{self.get_type_display()} - {self.employee_name} ({self.day:%d/%m/%Y})'

    class Meta:
        ordering = ['day', 'employee_name', 'employee_id', 'type']
        verbose_name = 'Ocorrência de Jornada'
        verbose_name_plural = 'Ocorrências de Jornada'
        constraints = [
            models.UniqueConstraint(
                fields=['competency', 'day', 'employee_id', 'type'],
                name='unique_occurrence_per_competency',
            ),
        ]


class OccurrenceTreatment(models.Model):
    occurrence = models.ForeignKey(Occurrence, on_delete=models.CASCADE, related_name='treatments', verbose_name='Ocorrência')
    treatment = models.CharField(max_length=1, choices=Occurrence.TREATMENTS, blank=True, verbose_name='Tratativa')
    note = models.TextField(verbose_name='Observação')
    responsible = models.CharField(max_length=150, verbose_name='Responsável')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name='Usuário'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data')

    def __str__(self):
        return f'{self.get_treatment_display() or "Pendente"} - {self.occurrence}'

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Tratativa de Ocorrência'
        verbose_name_plural = 'Tratativas de Ocorrência'
