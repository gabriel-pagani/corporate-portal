from django.contrib import admin
from reversion.admin import VersionAdmin
import reversion
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group as BaseGroup
from .models import User, Group, Sector, Dashboard, GroupDashboards, Contact


# Users Admin
@admin.register(User)
class UserAdmin(VersionAdmin, BaseUserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'email', 'last_login', 'date_joined', 'is_staff', 'is_superuser', 'is_active',)
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
    autocomplete_fields = ('sector',)
