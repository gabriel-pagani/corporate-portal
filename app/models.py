from django.db import models
from django.contrib import admin
from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group as BaseGroup
from django.core.exceptions import ValidationError
from django.urls import reverse
from .validators import valid_url
from .utils.dashboards.metabase import generate_metabase_dashboard_url


class Sector(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Setor')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'


class Dashboard(models.Model):
    STATUS = [
        ('D', 'Em Desenvolvimento'),
        ('M', 'Em Manutenção'),
        ('P', 'Em Produção'),
    ]

    title = models.CharField(max_length=150, unique=True, verbose_name='Título')
    sector = models.ForeignKey(
        Sector,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name='Setor'
    )
    metabase_code = models.PositiveSmallIntegerField(blank=True, null=True, unique=True, verbose_name='Código do Metabase')
    powerbi_url = models.CharField(blank=True, null=True, unique=True, validators=[valid_url], verbose_name='Link do Power BI')
    status = models.CharField(max_length=1, choices=STATUS, default="D", verbose_name='Situação')
    fav_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name='Favoritado Por')

    @property
    def metabase_url(self):
        if self.metabase_code:
            return generate_metabase_dashboard_url(self.metabase_code)
        return None

    def get_absolute_url(self):
        return reverse('app:dashboard', args=[self.id])

    def clean(self):
        if self.metabase_code and self.powerbi_url:
            raise ValidationError(
                'Preencha apenas o campo "Código do Metabase" ou o campo "Link do Power BI".'
            )

    def __str__(self) -> str:
        return self.title

    class Meta:
        verbose_name = 'Dashboard'
        verbose_name_plural = 'Dashboards'
        ordering = ['title']
        permissions = [
            ("view_all_dashboards", "Can view all Dashboards"),
        ]


class User(AbstractUser):
    email = models.EmailField(blank=True, null=True, verbose_name='Endereço de email')
    observations = models.TextField(blank=True, null=True, verbose_name='Observações')
    dashboards = models.ManyToManyField(Dashboard, blank=True, verbose_name='Dashboards')

    def clean(self):
        super().clean()
        if self.email:
            email = User.objects.filter(email=self.email).exclude(pk=self.pk)
            if email.exists():
                raise ValidationError({'email': 'Já existe um usuário com este e-mail.'})


class Group(BaseGroup):
    class Meta:
        proxy = True
        verbose_name = BaseGroup._meta.verbose_name
        verbose_name_plural = BaseGroup._meta.verbose_name_plural
        app_label = 'app'


class GroupDashboards(models.Model):
    group = models.OneToOneField(BaseGroup, on_delete=models.CASCADE, related_name='perfil', primary_key=True, verbose_name='Grupo')
    dashboards = models.ManyToManyField(Dashboard, blank=True, verbose_name='Dashboards')

    def __str__(self):
        return self.group.name


class Contact(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name='Usuário'
    )
    name = models.CharField(max_length=100, blank=True, verbose_name='Nome')
    number = models.CharField(max_length=100, blank=True, verbose_name='Número')
    sector = models.ForeignKey(
        Sector,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name='Setor'
    )
    machine = models.CharField(max_length=100, blank=True, verbose_name='Máquina')

    @admin.display(description='Nome')
    def get_display_name(self):
        if self.user:
            return self.user.get_full_name() or self.user.username
        return self.name or 'Sem Nome'

    def __str__(self):
        return self.get_display_name()

    class Meta:
        ordering = ['name']
        verbose_name = 'Contato'
        verbose_name_plural = 'Contatos'


class Toner(models.Model):
    name = models.CharField(max_length=100, verbose_name='Modelo')
    location = models.CharField(max_length=100, blank=True, verbose_name='Impressora / Setor')
    observations = models.CharField(max_length=255, blank=True, verbose_name='Observação')
    quantity = models.PositiveIntegerField(default=0, verbose_name='Quantidade')
    minimum_quantity = models.PositiveIntegerField(
        default=1,
        verbose_name='Quantidade Mínima',
        help_text='Quando a quantidade chegar a este valor o toner é sinalizado para compra.',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    @property
    def is_low(self):
        return self.quantity <= self.minimum_quantity

    @admin.display(boolean=True, description='Estoque OK')
    def is_stock_ok(self):
        return not self.is_low

    def __str__(self):
        return f'{self.name} ({self.location})' if self.location else self.name

    class Meta:
        ordering = ['location', 'name']
        verbose_name = 'Toner'
        verbose_name_plural = 'Toners'


class TonerMovement(models.Model):
    ENTRY = 'E'
    EXIT = 'S'
    TYPES = [
        (ENTRY, 'Entrada'),
        (EXIT, 'Saída'),
    ]

    toner = models.ForeignKey(Toner, on_delete=models.CASCADE, related_name='movements', verbose_name='Toner')
    type = models.CharField(max_length=1, choices=TYPES, verbose_name='Tipo')
    quantity = models.PositiveIntegerField(verbose_name='Quantidade')
    reason = models.CharField(max_length=255, blank=True, verbose_name='Motivo')
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name='Usuário'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data')

    def __str__(self):
        return f'{self.get_type_display()} de {self.quantity} - {self.toner}'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Movimentação de Toner'
        verbose_name_plural = 'Movimentações de Toner'
