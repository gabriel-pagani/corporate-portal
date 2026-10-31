from django.contrib import admin

from app.admin import UnaccentSearchAdmin
from journey_audit.models import Competency, Occurrence, OccurrenceTreatment, SourceReport


class SourceReportInline(admin.TabularInline):
    model = SourceReport
    extra = 0
    can_delete = False
    fields = ('type', 'file_name', 'uploaded_by', 'uploaded_at',)
    readonly_fields = fields

    # As linhas do relatório pesam e não aparecem aqui
    def get_queryset(self, request):
        return super().get_queryset(request).defer('rows')

    def has_add_permission(self, request, obj=None):
        return False


# Competências e ocorrências nascem da importação dos relatórios na tela da
# auditoria; editadas aqui, deixariam de bater com eles
@admin.register(Competency)
class CompetencyAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'analysed_rows', 'created_by', 'created_at', 'finished_at', 'finished_by',)
    list_select_related = ('created_by', 'finished_by',)
    date_hierarchy = 'start_date'
    inlines = (SourceReportInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OccurrenceTreatmentInline(admin.TabularInline):
    model = OccurrenceTreatment
    extra = 0
    can_delete = False
    fields = ('created_at', 'treatment', 'note', 'responsible', 'user',)
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Occurrence)
class OccurrenceAdmin(UnaccentSearchAdmin):
    list_display = ('day', 'employee_name', 'employee_id', 'location', 'type', 'treatment', 'in_reports', 'competency',)
    list_select_related = ('competency',)
    search_fields = ('employee_name__unaccent', 'employee_id', 'location__unaccent',)
    list_filter = ('type', 'treatment', 'in_reports', 'competency',)
    date_hierarchy = 'day'
    inlines = (OccurrenceTreatmentInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # Apagar a ocorrência levaria junto o histórico das tratativas
    def has_delete_permission(self, request, obj=None):
        return False
