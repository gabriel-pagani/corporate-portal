from django.urls import path
from journey_audit.views import (
    audit_view, bank_hours_note_api, competencies_api, competency_api, competency_finish_api, indicators_api,
    recurrence_api, reports_api, treatments_api,
)

app_name = 'journey_audit'

urlpatterns = [
    path('journey-audit/', audit_view, name='audit'),

    # API
    path('api/journey-audit/competencies/', competencies_api, name='competencies-api'),
    path('api/journey-audit/competencies/<int:competency_id>/', competency_api, name='competency-api'),
    path(
        'api/journey-audit/competencies/<int:competency_id>/finish/',
        competency_finish_api,
        name='competency-finish-api',
    ),
    path(
        'api/journey-audit/competencies/<int:competency_id>/indicators/',
        indicators_api,
        name='competency-indicators-api',
    ),
    path(
        'api/journey-audit/competencies/<int:competency_id>/bank-hours-notes/',
        bank_hours_note_api,
        name='bank-hours-note-api',
    ),
    path('api/journey-audit/reports/', reports_api, name='reports-api'),
    path('api/journey-audit/occurrences/<int:occurrence_id>/treatments/', treatments_api, name='treatments-api'),
    path('api/journey-audit/recurrence/', recurrence_api, name='recurrence-api'),
    path('api/journey-audit/indicators/', indicators_api, name='indicators-api'),
]
