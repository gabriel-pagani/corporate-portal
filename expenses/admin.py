import json

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from reversion.admin import VersionAdmin

from app.admin import UnaccentSearchAdmin
from expenses.models import (
    Expense, ExpenseEvent, ExpenseItem, ExpensePhoto, ExpenseRules, ExpenseType, NonReimbursableGroup,
)
from expenses.roles import access


class RulesManagerAdmin(VersionAdmin):
    """
    O que a IA consulta: só o gestor (manage_expense_rules) mexe, e o reversion
    guarda quem mudou o quê. Quem envia notas não chega aqui, nem com a
    permissão: a combinação deixa o usuário em conflito.
    """

    def has_view_permission(self, request, obj=None):
        return access(request.user).manage

    def has_add_permission(self, request):
        return access(request.user).manage

    def has_change_permission(self, request, obj=None):
        return access(request.user).manage

    def has_delete_permission(self, request, obj=None):
        return access(request.user).manage


@admin.register(ExpenseType)
class ExpenseTypeAdmin(RulesManagerAdmin, UnaccentSearchAdmin):
    list_display = ('name',)
    search_fields = ('name__unaccent',)


@admin.register(NonReimbursableGroup)
class NonReimbursableGroupAdmin(RulesManagerAdmin, UnaccentSearchAdmin):
    list_display = ('name',)
    search_fields = ('name__unaccent',)


# O texto é um só: a lista abre direto nele, e ele não é excluído
@admin.register(ExpenseRules)
class ExpenseRulesAdmin(RulesManagerAdmin):
    fields = ('text', 'updated_at')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not ExpenseRules.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            return super().changelist_view(request, extra_context)
        rules = ExpenseRules.objects.order_by('pk').first()
        if rules is None:
            return redirect(reverse('admin:expenses_expenserules_add'))
        return redirect(reverse('admin:expenses_expenserules_change', args=[rules.pk]))


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ExpenseItemInline(ReadOnlyInline):
    model = ExpenseItem
    fields = ('position', 'description', 'quantity', 'amount', 'non_reimbursable', 'ai_group')
    readonly_fields = fields


class ExpensePhotoInline(ReadOnlyInline):
    model = ExpensePhoto
    fields = ('get_link', 'round', 'position', 'uploaded_at', 'replaced_at', 'sha256')
    readonly_fields = fields

    @admin.display(description='Foto')
    def get_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">Abrir</a>', reverse('expenses:photo', args=[obj.pk]))


class ExpenseEventInline(ReadOnlyInline):
    model = ExpenseEvent
    fields = ('sequence', 'action', 'status_after', 'author_name', 'author_role', 'note', 'created_at')
    readonly_fields = fields
    ordering = ('sequence',)


def pretty_json(value):
    return format_html('<pre style="white-space: pre-wrap">{}</pre>', json.dumps(value, ensure_ascii=False, indent=2))


# A auditoria das notas: tudo só para leitura. A nota muda pelo fluxo do
# portal, que grava o histórico; editar aqui passaria por fora dele.
@admin.register(Expense)
class ExpenseAdmin(UnaccentSearchAdmin):
    list_display = (
        'id', 'employee', 'status', 'expense_type', 'number', 'issue_date', 'total', 'reimbursed_total', 'created_at',
    )
    list_filter = ('status', 'expense_type', 'created_at')
    search_fields = (
        'number', 'cnpj', 'access_key', 'employee__username', 'employee__first_name__unaccent',
        'employee__last_name__unaccent',
    )
    date_hierarchy = 'created_at'
    inlines = (ExpenseItemInline, ExpensePhotoInline, ExpenseEventInline)
    fields = (
        'employee', 'sector', 'cost_center', 'status', 'cnpj', 'access_key', 'number', 'issue_date', 'total',
        'expense_type', 'reimbursed_total', 'employee_note', 'last_note', 'get_alerts', 'get_reading', 'version',
        'created_at', 'updated_at',
    )
    readonly_fields = fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('employee', 'expense_type')

    @admin.display(description='Alertas da IA')
    def get_alerts(self, obj):
        if not obj.ai_alerts:
            return '-'
        return format_html('<ul>{}</ul>', format_html_join('', '<li>{}</li>', ((alert,) for alert in obj.ai_alerts)))

    @admin.display(description='Leitura da IA')
    def get_reading(self, obj):
        return pretty_json(obj.ai_reading) if obj.ai_reading else '-'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExpenseEvent)
class ExpenseEventAdmin(UnaccentSearchAdmin):
    list_display = ('created_at', 'expense', 'sequence', 'action', 'status_after', 'author_name', 'author_role')
    list_filter = ('action', 'author_role', 'status_after', 'created_at')
    search_fields = ('=expense__id', 'author_name__unaccent', 'note__unaccent')
    date_hierarchy = 'created_at'
    list_per_page = 50
    fields = (
        'expense', 'sequence', 'action', 'status_before', 'status_after', 'author', 'author_name', 'author_role',
        'note', 'created_at', 'get_snapshot',
    )
    readonly_fields = fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('expense')

    @admin.display(description='Estado da nota')
    def get_snapshot(self, obj):
        return pretty_json(obj.snapshot)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
