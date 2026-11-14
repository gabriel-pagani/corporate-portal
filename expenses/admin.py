from django.contrib import admin

from app.admin import UnaccentSearchAdmin
from expenses.models import IgnoredWordEvent


class WordFilter(admin.SimpleListFilter):
    """Os tipos que já passaram pelo histórico, inclusive os removidos: tudo de "bebida alcoólica" num clique."""
    title = 'tipo de item'
    parameter_name = 'word'

    def lookups(self, request, model_admin):
        words = IgnoredWordEvent.objects.order_by('word').values_list('word', flat=True).distinct()
        return [(word, word) for word in words]

    def queryset(self, request, queryset):
        return queryset.filter(word=self.value()) if self.value() else queryset


class UserNameFilter(admin.SimpleListFilter):
    """Pelo nome gravado na hora: continua valendo para o usuário que foi excluído depois."""
    title = 'usuário'
    parameter_name = 'user_name'

    def lookups(self, request, model_admin):
        names = IgnoredWordEvent.objects.order_by('user_name').values_list('user_name', flat=True).distinct()
        return [(name, name) for name in names]

    def queryset(self, request, queryset):
        return queryset.filter(user_name=self.value()) if self.value() else queryset


# A auditoria dos tipos não reembolsáveis: quem removeu "bebida alcoólica"
# responde pelas notas que passaram depois. Ninguém inclui, altera nem apaga
# registro por aqui, nem o superusuário; eles nascem só da tela de Configurações.
@admin.register(IgnoredWordEvent)
class IgnoredWordEventAdmin(UnaccentSearchAdmin):
    list_display = ('created_at', 'user_name', 'action', 'word')
    list_filter = ('action', WordFilter, UserNameFilter, 'created_at')
    search_fields = ('word__unaccent', 'user_name__unaccent')
    date_hierarchy = 'created_at'
    fields = ('created_at', 'user_name', 'user', 'action', 'word')
    readonly_fields = fields
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
