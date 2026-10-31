from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from app.views import form_errors_response, json_permission_required, parse_json_body
from journey_audit.audit import (
    catalog, competencies_queryset, competency_payload, current_period, import_report, indicators,
    odd_punches_recurrence, register_treatment, serialize_bank_hours_note, serialize_competency,
    serialize_competency_summary, serialize_occurrence, serialize_treatment,
)
from journey_audit.forms import BankHoursNoteForm, JourneyReportForm, OccurrenceTreatmentForm
from journey_audit.models import BankHoursNote, Competency, Occurrence


@login_required
@permission_required('journey_audit.view_competency', raise_exception=True)
def audit_view(request):
    user = request.user
    start, end = current_period()
    competency = Competency.objects.select_related('finished_by').filter(start_date=start, end_date=end).first()

    return render(request, 'journey_audit/index.html', {
        'competencies': [serialize_competency_summary(item) for item in competencies_queryset()],
        'competency': competency_payload(competency) if competency else None,
        'period': {'start_date': start.isoformat(), 'end_date': end.isoformat()},
        'catalog': catalog(),
        'permissions': {
            'change': user.has_perm('journey_audit.change_competency'),
            'delete': user.has_perm('journey_audit.delete_competency'),
        },
        'responsible': user.get_full_name() or user.username,
    })


@require_http_methods(['GET'])
@json_permission_required('journey_audit.view_competency')
def competencies_api(request):
    return JsonResponse({
        'competencies': [serialize_competency_summary(item) for item in competencies_queryset()],
    })


@require_http_methods(['GET', 'DELETE'])
def competency_api(request, competency_id):
    if request.method == 'DELETE':
        return competency_delete(request, competency_id)
    return competency_detail(request, competency_id)


@json_permission_required('journey_audit.view_competency')
def competency_detail(request, competency_id):
    competency = get_object_or_404(Competency.objects.select_related('finished_by'), id=competency_id)
    return JsonResponse(competency_payload(competency))


# Os relatórios e as tratativas vão junto: não há como desfazer
@json_permission_required('journey_audit.delete_competency')
def competency_delete(request, competency_id):
    competency = get_object_or_404(Competency, id=competency_id)
    competency.delete()
    return JsonResponse({'status': 'success'})


@require_POST
@json_permission_required('journey_audit.change_competency')
def competency_finish_api(request, competency_id):
    competency = get_object_or_404(Competency, id=competency_id)
    competency.finished_at = timezone.now()
    competency.finished_by = request.user
    competency.save(update_fields=['finished_at', 'finished_by'])
    return JsonResponse({'competency': serialize_competency(competency)})


@require_POST
@json_permission_required('journey_audit.change_competency')
def reports_api(request):
    form = JourneyReportForm(request.POST, request.FILES)
    if not form.is_valid():
        return form_errors_response(form)

    try:
        competency = import_report(
            form.cleaned_data['start_date'],
            form.cleaned_data['end_date'],
            form.cleaned_data['type'],
            form.cleaned_data['file'],
            request.user,
        )
    except ValidationError as error:
        return JsonResponse({'detail': error.messages[0]}, status=400)

    return JsonResponse(competency_payload(competency), status=201)


@require_POST
@json_permission_required('journey_audit.change_competency')
def bank_hours_note_api(request, competency_id):
    competency = get_object_or_404(Competency, id=competency_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = BankHoursNoteForm(payload)
    if not form.is_valid():
        return form_errors_response(form)

    note, _ = BankHoursNote.objects.update_or_create(
        competency=competency,
        employee_id=form.cleaned_data['employee_id'],
        defaults={'note': form.cleaned_data['note'], 'updated_by': request.user},
    )
    return JsonResponse(serialize_bank_hours_note(note))


@require_http_methods(['GET', 'POST'])
def treatments_api(request, occurrence_id):
    if request.method == 'GET':
        return treatments_list(request, occurrence_id)
    return treatment_create(request, occurrence_id)


@json_permission_required('journey_audit.view_competency')
def treatments_list(request, occurrence_id):
    occurrence = get_object_or_404(Occurrence, id=occurrence_id)
    return JsonResponse({
        'occurrence': serialize_occurrence(occurrence),
        'treatments': [serialize_treatment(entry) for entry in occurrence.treatments.select_related('user')],
    })


@json_permission_required('journey_audit.change_competency')
def treatment_create(request, occurrence_id):
    occurrence = get_object_or_404(Occurrence, id=occurrence_id)
    payload = parse_json_body(request)
    if payload is None:
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    form = OccurrenceTreatmentForm(payload)
    if not form.is_valid():
        return form_errors_response(form)

    try:
        entry = register_treatment(
            occurrence,
            form.cleaned_data['treatment'],
            form.cleaned_data['note'],
            form.cleaned_data['responsible'],
            request.user,
        )
    except ValidationError as error:
        return JsonResponse({'detail': error.messages[0]}, status=400)

    return JsonResponse({
        'occurrence': serialize_occurrence(occurrence),
        'treatment': serialize_treatment(entry),
    }, status=201)


@require_http_methods(['GET'])
@json_permission_required('journey_audit.view_competency')
def recurrence_api(request):
    return JsonResponse({'employees': odd_punches_recurrence()})


# Sem competência, os rankings somam todas
@require_http_methods(['GET'])
@json_permission_required('journey_audit.view_competency')
def indicators_api(request, competency_id=None):
    competency = get_object_or_404(Competency, id=competency_id) if competency_id is not None else None
    return JsonResponse(indicators(competency))
