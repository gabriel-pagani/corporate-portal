import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ExpenseType(models.Model):
    """O tipo da despesa (Alimentação, Combustível, Hospedagem...): a IA escolhe um desta lista para cada nota."""
    name = models.CharField(
        max_length=60,
        unique=True,
        error_messages={'unique': 'Este tipo já está cadastrado.'},
        verbose_name='Nome',
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Tipo de Despesa'
        verbose_name_plural = 'Tipos de Despesa'


class NonReimbursableGroup(models.Model):
    """
    Grupo de item que não entra no valor reembolsado ("bebida alcoólica",
    "jogos de azar"). A IA marca os itens da nota que se encaixam, como sinal
    para quem confere, que tem a última palavra.
    """
    name = models.CharField(
        max_length=60,
        unique=True,
        error_messages={'unique': 'Este grupo já está cadastrado.'},
        verbose_name='Grupo',
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Item Não Reembolsável'
        verbose_name_plural = 'Itens Não Reembolsáveis'


class ExpenseRules(models.Model):
    """
    O texto único que complementa o prompt da IA ("a nota deve conter o CNPJ da
    empresa"). O que a IA encontrar na nota coberto por estas regras vira um
    alerta na conferência.
    """
    text = models.TextField(
        blank=True,
        verbose_name='Regras complementares',
        help_text='Uma regra por linha. A IA confere cada nota por elas e gera um alerta na conferência quando encontrar algo que elas cobrem.',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    @classmethod
    def current_text(cls):
        rules = cls.objects.order_by('pk').first()
        return rules.text.strip() if rules else ''

    def __str__(self):
        return 'Regras complementares'

    class Meta:
        verbose_name = 'Regras Complementares'
        verbose_name_plural = 'Regras Complementares'


class Expense(models.Model):
    AWAITING_REVIEW = 'C'
    AWAITING_CORRECTION = 'S'
    AWAITING_EXPLANATION = 'E'
    AWAITING_VALIDATION = 'V'
    APPROVED = 'A'
    REJECTED = 'R'
    STATUS = [
        (AWAITING_REVIEW, 'Aguardando conferência'),
        (AWAITING_CORRECTION, 'Aguardando correção'),
        (AWAITING_EXPLANATION, 'Aguardando explicação'),
        (AWAITING_VALIDATION, 'Aguardando validação'),
        (APPROVED, 'Aprovada'),
        (REJECTED, 'Rejeitada'),
    ]
    # Na conferência: a primeira conferência e a explicação pedida na validação
    WITH_CONTROL = (AWAITING_REVIEW, AWAITING_EXPLANATION)
    WITH_FINANCE = (AWAITING_VALIDATION,)
    CLOSED = (APPROVED, REJECTED)

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='expenses', verbose_name='Funcionário',
    )
    # Como estavam no cadastro do funcionário no envio: mudar o setor depois
    # não muda a nota
    sector = models.ForeignKey(
        'app.Sector', on_delete=models.PROTECT, blank=True, null=True, related_name='+', verbose_name='Setor',
    )
    cost_center = models.ForeignKey(
        'app.CostCenter', on_delete=models.PROTECT, blank=True, null=True, related_name='+',
        verbose_name='Centro de custo',
    )
    status = models.CharField(max_length=1, choices=STATUS, default=AWAITING_REVIEW, verbose_name='Situação')
    # Só os 14 caracteres; desde 2026 o CNPJ pode ter letras
    cnpj = models.CharField(max_length=14, blank=True, verbose_name='CNPJ do emitente')
    # Os 44 dígitos. Única quando preenchida: a mesma nota não entra duas vezes
    access_key = models.CharField(max_length=44, blank=True, verbose_name='Chave de acesso')
    number = models.CharField(max_length=20, blank=True, verbose_name='Número da nota')
    issue_date = models.DateField(blank=True, null=True, verbose_name='Data da nota')
    total = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True, verbose_name='Valor total')
    expense_type = models.ForeignKey(
        ExpenseType, on_delete=models.PROTECT, blank=True, null=True, related_name='expenses', verbose_name='Tipo',
    )
    # A soma dos itens fora da marcação de não reembolsável, refeita no servidor a cada alteração
    reimbursed_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Valor reembolsado',
    )
    employee_note = models.TextField(blank=True, verbose_name='Observação do funcionário')
    # A análise da IA como chegou, com as listas e as regras que ela recebeu.
    # Ninguém muda isto depois do envio, nem no reenvio das fotos.
    ai_reading = models.JSONField(blank=True, null=True, verbose_name='Leitura da IA')
    ai_alerts = models.JSONField(default=list, blank=True, verbose_name='Alertas da IA')
    # A observação da última ação: o motivo da rejeição, a correção pedida...
    last_note = models.TextField(blank=True, verbose_name='Observação da última ação')
    # Sobe a cada ação: quem age sobre uma versão velha da nota é recusado
    version = models.PositiveIntegerField(default=1, verbose_name='Versão')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Enviada em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizada em')

    def untouched(self):
        """Ninguém tratou a despesa ainda: só existe o envio no histórico."""
        return self.status == self.AWAITING_REVIEW and all(
            event.action == ExpenseEvent.SUBMIT for event in self.events.all()
        )

    def __str__(self):
        return f'Nota #{self.pk}'

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Nota'
        verbose_name_plural = 'Notas'
        constraints = [
            models.UniqueConstraint(
                fields=['access_key'],
                condition=~models.Q(access_key=''),
                name='unique_expense_access_key',
                violation_error_message='Já existe uma nota com esta chave de acesso.',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at'], name='expense_status_idx'),
        ]
        permissions = [
            ('submit_expense', 'Can submit expenses'),
            ('review_expense', 'Can review expenses'),
            ('validate_expense', 'Can validate expenses'),
            ('manage_expense_rules', 'Can manage expense rules'),
        ]


class ExpenseItem(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='items', verbose_name='Nota')
    position = models.PositiveSmallIntegerField(default=0, verbose_name='Posição')
    description = models.CharField(max_length=200, verbose_name='Descrição')
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1, verbose_name='Quantidade')
    # O valor da linha inteira, e não o unitário
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Valor')
    non_reimbursable = models.BooleanField(default=False, verbose_name='Não reembolsável')
    # O grupo não reembolsável que a IA apontou: fica como sinal mesmo que a conferência desmarque
    ai_group = models.CharField(max_length=60, blank=True, verbose_name='Grupo apontado pela IA')

    def __str__(self):
        return self.description

    class Meta:
        ordering = ['position', 'id']
        verbose_name = 'Item da Nota'
        verbose_name_plural = 'Itens da Nota'


def photo_upload_to(instance, filename):
    # Nome sorteado, como na biblioteca: o caminho no disco não diz nada da nota
    return f'expenses/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.jpg'


class ExpensePhoto(models.Model):
    """
    Uma foto da nota. O reenvio não apaga as anteriores: elas ficam marcadas
    como substituídas e continuam abrindo nos registros antigos do histórico.
    """
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name='photos', verbose_name='Nota')
    file = models.FileField(upload_to=photo_upload_to, max_length=255, verbose_name='Arquivo')
    # Do arquivo guardado: confere que a foto do histórico é a mesma de quando foi enviada
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA-256')
    # Do arquivo como o funcionário enviou: a mesma foto não entra de novo no portal
    source_sha256 = models.CharField(
        max_length=64, blank=True, db_index=True, verbose_name='SHA-256 do arquivo enviado',
    )
    # 1 no envio, 2 no primeiro reenvio e assim por diante
    round = models.PositiveSmallIntegerField(default=1, verbose_name='Rodada de envio')
    position = models.PositiveSmallIntegerField(default=0, verbose_name='Posição')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='Enviada em')
    replaced_at = models.DateTimeField(blank=True, null=True, verbose_name='Substituída em')

    def __str__(self):
        return f'Foto {self.position + 1} da {self.expense}'

    class Meta:
        ordering = ['round', 'position', 'id']
        verbose_name = 'Foto da Nota'
        verbose_name_plural = 'Fotos da Nota'


class ImmutableRecord(Exception):
    """O registro do histórico não muda nem sai depois de criado."""


class ExpenseEvent(models.Model):
    """
    Um registro do histórico: a ação de uma etapa e o estado completo da nota
    logo depois dela (formulário, itens, fotos, observações e leitura da IA).

    É só criado. O save de um registro que já existe e o delete levantam erro, e
    um gatilho no banco recusa UPDATE e DELETE na tabela (migration 0001).
    """
    SUBMIT = 'submit'
    RESUBMIT = 'resubmit'
    REQUEST_CORRECTION = 'request_correction'
    REQUEST_EXPLANATION = 'request_explanation'
    APPROVE_REVIEW = 'approve_review'
    EXPLAIN = 'explain'
    APPROVE_VALIDATION = 'approve_validation'
    REJECT = 'reject'
    ACTIONS = [
        (SUBMIT, 'Nota enviada'),
        (RESUBMIT, 'Fotos reenviadas'),
        (REQUEST_CORRECTION, 'Correção solicitada'),
        (APPROVE_REVIEW, 'Conferida'),
        (EXPLAIN, 'Explicação enviada'),
        (REQUEST_EXPLANATION, 'Explicação solicitada'),
        (APPROVE_VALIDATION, 'Aprovada'),
        (REJECT, 'Rejeitada'),
    ]

    EMPLOYEE = 'employee'
    CONTROL = 'control'
    FINANCE = 'finance'
    ROLES = [
        (EMPLOYEE, 'Funcionário'),
        (CONTROL, 'Conferência'),
        (FINANCE, 'Validação'),
    ]

    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name='events', verbose_name='Nota')
    sequence = models.PositiveIntegerField(verbose_name='Etapa')
    action = models.CharField(max_length=30, choices=ACTIONS, verbose_name='Ação')
    status_before = models.CharField(
        max_length=1, choices=Expense.STATUS, blank=True, verbose_name='Situação anterior',
    )
    status_after = models.CharField(max_length=1, choices=Expense.STATUS, verbose_name='Situação')
    # Quem age fica protegido: usuário com histórico é desativado, não excluído.
    # O nome e o papel ficam gravados como eram na hora.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='Autor',
    )
    author_name = models.CharField(max_length=150, verbose_name='Nome do autor')
    author_role = models.CharField(max_length=10, choices=ROLES, verbose_name='Papel')
    note = models.TextField(blank=True, verbose_name='Observação')
    snapshot = models.JSONField(verbose_name='Estado da nota')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='Data')

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecord('O histórico da nota não pode ser alterado.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecord('O histórico da nota não pode ser apagado.')

    def __str__(self):
        return f'{self.expense} - etapa {self.sequence}: {self.get_action_display()}'

    class Meta:
        ordering = ['expense', 'sequence']
        verbose_name = 'Histórico da Nota'
        verbose_name_plural = 'Histórico das Notas'
        constraints = [
            models.UniqueConstraint(fields=['expense', 'sequence'], name='unique_expense_event_sequence'),
        ]
        indexes = [
            models.Index(fields=['created_at'], name='expense_event_created_idx'),
        ]
