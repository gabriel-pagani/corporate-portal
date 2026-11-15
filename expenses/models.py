import uuid

from django.conf import settings
from django.db import models
from django.db.models.fields.json import KeyTransform
from django.utils import timezone


class IgnoredWord(models.Model):
    """Tipo de item que não é reembolsado ("bebida alcoólica", "cigarro"): o modelo avalia cada item da nota por eles."""
    word = models.CharField(
        max_length=60,
        unique=True,
        error_messages={'unique': 'Este tipo já está cadastrado.'},
        verbose_name='Tipo de item',
    )

    def __str__(self):
        return self.word

    class Meta:
        ordering = ['word']
        verbose_name = 'Item Não Reembolsável'
        verbose_name_plural = 'Itens Não Reembolsáveis'


class IgnoredWordEvent(models.Model):
    """
    A auditoria dos tipos não reembolsáveis: quem incluiu ou removeu cada um, e
    quando. Quem tira "bebida alcoólica" responde pelas notas que passarem
    depois. Só é criado, nunca alterado nem apagado.
    """
    ADDED = 'A'
    REMOVED = 'R'
    ACTIONS = [(ADDED, 'Incluído'), (REMOVED, 'Removido')]

    word = models.CharField(max_length=60, verbose_name='Tipo de item')
    action = models.CharField(max_length=1, choices=ACTIONS, verbose_name='Ação')
    # O usuário pode ser excluído depois: o nome fica gravado como era na hora
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+', verbose_name='Usuário',
    )
    user_name = models.CharField(max_length=150, verbose_name='Nome do usuário')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data')

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Histórico de Item Não Reembolsável'
        verbose_name_plural = 'Histórico de Itens Não Reembolsáveis'


class GuideSeen(models.Model):
    """Quem já viu o guia da tela de despesas: ele abre sozinho só na primeira visita, em qualquer aparelho."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name='+', verbose_name='Usuário',
    )
    seen_at = models.DateTimeField(auto_now_add=True, verbose_name='Visto em')

    class Meta:
        verbose_name = 'Guia Visto'
        verbose_name_plural = 'Guias Vistos'


class Expense(models.Model):
    # O rascunho é a despesa entre a leitura das fotos e o envio: só o dono a vê
    DRAFT = 'D'
    SENT = 'E'
    CORRECTION = 'C'
    APPROVED = 'A'
    REJECTED = 'R'
    REIMBURSED = 'P'
    STATUS = [
        (DRAFT, 'Rascunho'),
        (SENT, 'Enviada'),
        (CORRECTION, 'Correção solicitada'),
        (APPROVED, 'Aprovada'),
        (REJECTED, 'Rejeitada'),
        (REIMBURSED, 'Reembolsada'),
    ]
    # Os status em que o funcionário ainda mexe na despesa
    EDITABLE = (DRAFT, CORRECTION)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='expenses', verbose_name='Funcionário',
    )
    cost_center = models.ForeignKey(
        'app.CostCenter',
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='expenses',
        verbose_name='Centro de custo',
    )
    status = models.CharField(max_length=1, choices=STATUS, default=DRAFT, verbose_name='Situação')
    merchant = models.CharField(max_length=150, blank=True, verbose_name='Estabelecimento')
    # Só os dígitos
    cnpj = models.CharField(max_length=14, blank=True, verbose_name='CNPJ')
    issue_date = models.DateField(blank=True, null=True, verbose_name='Data da nota')
    # Os dois totais são somados no servidor a partir dos itens, a cada alteração
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Total da nota')
    reimbursable_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Total reembolsável',
    )
    # O que a IA leu nas fotos, como chegou: nada do que o funcionário edita
    # muda isto. Sem leitura (a IA falhou ou demorou) fica vazio.
    ai_reading = models.JSONField(blank=True, null=True, verbose_name='Leitura original')
    # Os motivos da verificação obrigatória, que só o aprovador vê. Com algum
    # motivo, a aprovação exige a conferência da foto.
    verification_reasons = models.JSONField(default=list, blank=True, verbose_name='Motivos de verificação')
    photo_checked = models.BooleanField(default=False, verbose_name='Foto conferida pelo aprovador')
    sent_at = models.DateTimeField(blank=True, null=True, verbose_name='Enviada em')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criada em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizada em')

    def __str__(self):
        return f'Despesa {self.pk} - {self.user}'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Despesa'
        verbose_name_plural = 'Despesas'
        indexes = [
            # A lista das encerradas na tela de aprovações, já na ordem dela: a
            # consulta para na página pedida em vez de ordenar o histórico inteiro
            models.Index(
                fields=['-updated_at', '-id'], condition=models.Q(status__in=['R', 'P']), name='expense_closed_idx',
            ),
            # A fila das pendentes e as contagens do card da home
            models.Index(
                fields=['sent_at'], condition=models.Q(status__in=['E', 'C', 'A']), name='expense_pending_idx',
            ),
            # A conferência da nota repetida, a cada leitura e envio: pelo que foi
            # enviado e pelo que a IA leu
            models.Index(fields=['cnpj', 'issue_date'], name='expense_cnpj_date_idx'),
            models.Index(KeyTransform('cnpj', 'ai_reading'), name='expense_read_cnpj_idx'),
            models.Index(KeyTransform('access_key', 'ai_reading'), name='expense_read_access_key_idx'),
        ]
        permissions = [
            ('access_expenses', 'Can access expense reimbursement'),
            ('approve_expense', 'Can approve expenses'),
            ('reimburse_expense', 'Can mark expenses as reimbursed'),
            ('manage_expense_settings', 'Can manage expense settings'),
        ]


class ExpenseItem(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='items', verbose_name='Despesa')
    description = models.CharField(max_length=200, verbose_name='Descrição')
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1, verbose_name='Quantidade')
    # O valor da linha inteira, e não o unitário
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Valor')
    # Veio da leitura como rasurado ou ilegível. O funcionário não muda isto.
    unreadable = models.BooleanField(default=False, verbose_name='Ilegível na nota')
    # Fora do total reembolsável: tipo não reembolsável, item ilegível ou decisão do aprovador
    ignored = models.BooleanField(default=False, verbose_name='Fora do reembolso')

    def __str__(self):
        return self.description

    class Meta:
        ordering = ['id']
        verbose_name = 'Item da Despesa'
        verbose_name_plural = 'Itens da Despesa'


def photo_upload_to(instance, filename):
    # Nome sorteado, como na biblioteca: o caminho no disco não diz nada da despesa
    return f'expenses/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.jpg'


class ExpensePhoto(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='photos', verbose_name='Despesa')
    file = models.FileField(upload_to=photo_upload_to, max_length=255, verbose_name='Arquivo')
    # Do arquivo como foi enviado, antes da redução: é o que acusa a mesma foto
    # mandada de novo
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA-256 do envio')

    class Meta:
        ordering = ['id']
        verbose_name = 'Foto da Despesa'
        verbose_name_plural = 'Fotos da Despesa'


class ExpenseEvent(models.Model):
    """O histórico da despesa: cada mudança de status, com quem fez e por quê."""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='events', verbose_name='Despesa')
    status = models.CharField(max_length=1, choices=Expense.STATUS, verbose_name='Situação')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='Usuário',
    )
    note = models.TextField(blank=True, verbose_name='Observação')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data')

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'Histórico da Despesa'
        verbose_name_plural = 'Históricos da Despesa'
