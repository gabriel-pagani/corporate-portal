from django.contrib import admin
from reversion.admin import VersionAdmin
import reversion
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group as BaseGroup
from .models import (
    User, Group, Sector, Dashboard, GroupDashboards, Contact, Toner, TonerLocation, TonerMovement,
    Notification,
)


# Users Admin
@admin.register(User)
class UserAdmin(VersionAdmin, BaseUserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'email', 'last_login', 'is_staff', 'is_superuser', 'is_active',)
    search_fields = ('username', 'email', 'first_name', 'last_name', 'observations',)
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'groups',)
    filter_horizontal = ('groups', 'user_permissions', 'dashboards',)
    model = User
    ordering = ('username',)
    fieldsets = (
        (None, {
            'fields': ('username', 'password',)
        }),
        ('Informações pessoais', {
            'fields': ('first_name', 'last_name', 'email',)
        }),
        ('Permissões', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'dashboards',)
        }),
        ('Datas importantes', {
            'fields': ('last_login', 'date_joined',)
        }),
        ('Observações', {
            'fields': ('observations',)
        }),
    )
    add_fieldsets = (
        (None, {
            'fields': ('username', 'password1', 'password2',),
        }),
    )


# Groups Admin
reversion.register(BaseGroup)
reversion.register(Group)
reversion.register(GroupDashboards)
admin.site.unregister(BaseGroup)
class GroupDashboardsInline(admin.StackedInline):
    model = GroupDashboards
    can_delete = False
    verbose_name_plural = 'Dashboards'
    filter_horizontal = ('dashboards',)
    fields = ('dashboards',)

@admin.register(Group)
class GroupAdmin(VersionAdmin, BaseGroupAdmin):
    inlines = (GroupDashboardsInline,)


@admin.register(Sector)
class SectorAdmin(VersionAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Contact)
class ContactAdmin(VersionAdmin):
    list_display = ('get_display_name', 'number', 'sector', 'machine',)
    search_fields = ('name', 'user__username', 'user__first_name', 'user__last_name', 'number', 'sector__name', 'machine',)
    list_filter = ('sector',)
    autocomplete_fields = ('sector', 'user')


@admin.register(Dashboard)
class DashboardAdmin(VersionAdmin):
    list_display = ('title', 'sector', 'status')
    search_fields = ('title', 'sector__name')
    filter_horizontal = ('fav_by',)
    list_filter = ('status', 'sector',)
    ordering = ('title',)
    autocomplete_fields = ('sector',)


# A quantidade só muda por movimentação, para o histórico sempre fechar com o estoque
class TonerMovementInline(admin.TabularInline):
    model = TonerMovement
    extra = 0
    can_delete = False
    fields = ('created_at', 'type', 'quantity', 'reason', 'user',)
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TonerLocation)
class TonerLocationAdmin(VersionAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Toner)
class TonerAdmin(VersionAdmin):
    list_display = ('name', 'location', 'observations', 'quantity', 'minimum_quantity', 'is_stock_ok',)
    search_fields = ('name', 'location__name', 'observations',)
    list_filter = ('location',)
    readonly_fields = ('quantity', 'updated_at',)
    autocomplete_fields = ('location',)
    inlines = (TonerMovementInline,)

    def get_readonly_fields(self, request, obj=None):
        # O nome identifica o toner no histórico, então só muda enquanto não houver movimentação
        if obj and obj.movements.exists():
            return self.readonly_fields + ('name',)
        return self.readonly_fields


@admin.register(TonerMovement)
class TonerMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'toner', 'type', 'quantity', 'reason', 'user',)
    search_fields = ('toner__name', 'toner__location__name', 'reason', 'user__username',)
    list_filter = ('type', 'toner__location',)
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(VersionAdmin):
    list_display = ('title', 'level', 'get_recipients', 'start_at', 'end_at', 'is_active', 'get_read_count',)
    search_fields = ('title', 'message',)
    list_filter = ('level', 'is_active',)
    date_hierarchy = 'start_at'
    filter_horizontal = ('users', 'groups',)
    readonly_fields = ('get_read_by', 'created_at',)
    fieldsets = (
        (None, {
            'fields': ('title', 'message', 'level', 'is_active',)
        }),
        ('Destinatários', {
            'fields': ('users', 'groups',)
        }),
        ('Período de exibição', {
            'fields': ('start_at', 'end_at',)
        }),
        ('Leitura', {
            'fields': ('get_read_by', 'created_at',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('users', 'groups', 'read_by')

    @admin.display(description='Destinatários')
    def get_recipients(self, obj):
        recipients = [user.username for user in obj.users.all()] + [group.name for group in obj.groups.all()]
        return ', '.join(recipients) or 'Todos'

    @admin.display(description='Lida Por')
    def get_read_count(self, obj):
        return len(obj.read_by.all())

    @admin.display(description='Lida Por')
    def get_read_by(self, obj):
        users = [user.get_full_name() or user.username for user in obj.read_by.all()]
        return ', '.join(sorted(users)) or '-'
