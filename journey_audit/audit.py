"""
A auditoria de jornada no banco: importar os relatórios, manter as ocorrências
em dia com eles e registrar as tratativas do RH.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Func, IntegerField, Prefetch, Q
from django.utils import timezone

from journey_audit.models import Competency, Occurrence, OccurrenceTreatment, SourceReport
from journey_audit.analysis import balance_minutes, employee_id, find_occurrences, normalize
from journey_audit.reports import read_report


# A competência da folha vai do dia 21 ao dia 20 do mês seguinte
COMPETENCY_START_DAY = 21

PRIORITIES = {
    Occurrence.ODD_PUNCHES: 'Alta',
    Occurrence.ABSENCE: 'Alta',
    Occurrence.MISSING_BREAK: 'Alta',
    Occurrence.SHORT_BREAK: 'Alta',
    Occurrence.SHORT_REST: 'Alta',
    Occurrence.LONG_OVERTIME: 'Alta',
    Occurrence.NEGATIVE_BALANCE: 'Média',
    Occurrence.OVERTIME: 'Baixa',
    Occurrence.LEAVE: 'Baixa',
}

# O que a análise reescreve a cada importação; a tratativa nunca entra aqui
ANALYSIS_FIELDS = ['employee_name', 'location', 'scale', 'evidence', 'minutes', 'in_reports']

MONTHLY_ADJUSTMENT_ERROR = (
    'Já existe ajuste realizado para esta matrícula no mês. '
    'Registre a decisão como ajuste recusado ou confira se o registro anterior procede.'
)


def current_period(today=None):
    today = today or timezone.localdate()
    start = today.replace(day=COMPETENCY_START_DAY)
    if today.day < COMPETENCY_START_DAY:
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=COMPETENCY_START_DAY)
    end = (start + timedelta(days=31)).replace(day=COMPETENCY_START_DAY - 1)
    return start, end


def user_name(user):
    return (user.get_full_name() or user.username) if user else ''


def import_report(start, end, report_type, uploaded_file, user):
    # A leitura fica fora da transação: é a parte demorada, e não depende do banco
    rows = read_report(uploaded_file, report_type)

    with transaction.atomic():
        competency, _ = Competency.objects.get_or_create(
            start_date=start, end_date=end, defaults={'created_by': user},
        )
        # Enfileira as importações da mesma competência: cada análise parte dos
        # relatórios como a anterior os deixou
        competency = Competency.objects.select_for_update().get(pk=competency.pk)
        SourceReport.objects.update_or_create(
            competency=competency,
            type=report_type,
            defaults={'rows': rows, 'file_name': uploaded_file.name[:255], 'uploaded_by': user},
        )
        # O banco de horas não traz ocorrência: não pede análise nem reabre a conferência
        if report_type == SourceReport.BANK_HOURS:
            return competency

        analyse(competency)

        # Relatório novo reabre a conferência: pode ter trazido ocorrência a tratar
        competency.finished_at = None
        competency.finished_by = None
        competency.save(update_fields=['analysed_rows', 'finished_at', 'finished_by'])

    return competency


def fit(field, value):
    # Os valores vêm da planilha e podem passar do tamanho da coluna
    max_length = Occurrence._meta.get_field(field).max_length
    return value[:max_length] if max_length and isinstance(value, str) else value


def analyse(competency):
    rows = {report.type: report.rows for report in competency.reports.all()}
    found, competency.analysed_rows = find_occurrences(
        rows.get(SourceReport.SUMMARY, []),
        rows.get(SourceReport.ODD_PUNCHES, []),
        rows.get(SourceReport.ABSENCES, []),
        rows.get(SourceReport.REST, []),
        competency.start_date,
        competency.end_date,
    )

    current = {
        (occurrence.day, occurrence.employee_id, occurrence.type): occurrence
        for occurrence in competency.occurrences.select_for_update().only('day', 'employee_id', 'type', *ANALYSIS_FIELDS)
    }
    created, changed = [], []
    for values in found:
        values = {field: fit(field, value) for field, value in values.items()}
        occurrence = current.pop((values['day'], values['employee_id'], values['type']), None)
        if occurrence is None:
            created.append(Occurrence(competency=competency, **values))
            continue

        values['in_reports'] = True
        if any(getattr(occurrence, field) != values[field] for field in ANALYSIS_FIELDS):
            for field in ANALYSIS_FIELDS:
                setattr(occurrence, field, values[field])
            changed.append(occurrence)

    Occurrence.objects.bulk_create(created, batch_size=1000)
    Occurrence.objects.bulk_update(changed, ANALYSIS_FIELDS, batch_size=500)
    # O que sumiu dos relatórios continua guardado, com a tratativa que tiver: a
    # recorrência e a regra do ajuste mensal ainda contam com ele
    gone = [occurrence.pk for occurrence in current.values() if occurrence.in_reports]
    Occurrence.objects.filter(pk__in=gone).update(in_reports=False)


def register_treatment(occurrence, treatment, note, responsible, user):
    if not occurrence.is_actionable:
        raise ValidationError('Esta ocorrência é informativa e não pede tratativa.')
    # Em branco é a ocorrência que segue pendente, com a observação registrada
    if treatment and treatment not in Occurrence.TREATMENTS_BY_TYPE[occurrence.type]:
        raise ValidationError('Escolha um resultado válido para esta ocorrência.')

    # Um ajuste por matrícula em cada mês do calendário, mesmo que o outro dia
    # do mês tenha caído na competência anterior
    if treatment == Occurrence.ADJUSTED and Occurrence.objects.filter(
        type=Occurrence.ODD_PUNCHES,
        treatment=Occurrence.ADJUSTED,
        employee_id=occurrence.employee_id,
        day__year=occurrence.day.year,
        day__month=occurrence.day.month,
    ).exclude(day=occurrence.day).exists():
        raise ValidationError(MONTHLY_ADJUSTMENT_ERROR)

    with transaction.atomic():
        occurrence.treatment = treatment
        occurrence.note = note
        occurrence.responsible = responsible
        occurrence.treated_at = timezone.now()
        occurrence.save(update_fields=['treatment', 'note', 'responsible', 'treated_at'])
        entry = OccurrenceTreatment.objects.create(
            occurrence=occurrence, treatment=treatment, note=note, responsible=responsible, user=user,
        )

    return entry


def odd_punches_recurrence():
    """As batidas ímpares de cada matrícula, somando todas as competências."""
    employees = {}
    occurrences = (
        Occurrence.objects.filter(type=Occurrence.ODD_PUNCHES)
        .order_by('day')
        .values_list('employee_id', 'employee_name', 'day', 'treatment')
    )
    for employee, name, day, treatment in occurrences:
        entry = employees.setdefault(employee, {'employee_id': employee, 'days': set(), 'adjustments': 0})
        # Fica o nome do dia mais recente
        entry['employee_name'] = name
        entry['days'].add(day)
        entry['adjustments'] += treatment == Occurrence.ADJUSTED

    rows = [
        {**entry, 'count': len(entry['days']), 'days': [day.isoformat() for day in sorted(entry['days'])]}
        for entry in employees.values()
    ]
    return sorted(rows, key=lambda row: (-row['count'], normalize(row['employee_name'])))


def indicators(competency=None):
    """Os rankings de intervalo por colaborador, de uma competência ou somando todas."""
    occurrences = Occurrence.objects.filter(in_reports=True, type__in=[Occurrence.SHORT_BREAK, Occurrence.SHORT_REST])
    if competency:
        occurrences = occurrences.filter(competency=competency)

    rankings = {Occurrence.SHORT_BREAK: {}, Occurrence.SHORT_REST: {}}
    rows = occurrences.order_by('day').values_list('type', 'employee_id', 'employee_name', 'location', 'minutes')
    for type, employee, name, location, minutes in rows:
        entry = rankings[type].setdefault(employee, {'employee_id': employee, 'count': 0, 'minutes': 0})
        # Ficam o nome e a localização do dia mais recente
        entry.update(employee_name=name, location=location)
        entry['count'] += 1
        entry['minutes'] += minutes or 0

    return {'rankings': {type: list(employees.values()) for type, employees in rankings.items()}}


def catalog():
    """O que a tela precisa saber de cada tipo de ocorrência e tratativa."""
    return {
        'types': [
            {
                'code': code,
                'label': label,
                'priority': PRIORITIES[code],
                'actionable': code in Occurrence.TREATMENTS_BY_TYPE,
                'pending_label': 'Pendente de confirmação' if code == Occurrence.ABSENCE else 'Pendente de análise',
                'treatments': list(Occurrence.TREATMENTS_BY_TYPE.get(code, ())),
            }
            for code, label in Occurrence.TYPES
        ],
        'treatments': dict(Occurrence.TREATMENTS),
        'reports': dict(SourceReport.TYPES),
    }


def competencies_queryset():
    in_reports = Q(occurrences__in_reports=True)
    # A ordenação vai explícita: com a contagem a consulta agrupa, e o Django
    # deixa de aplicar a ordenação padrão do modelo
    return Competency.objects.select_related('finished_by').prefetch_related(
        Prefetch('reports', queryset=SourceReport.objects.only('id', 'competency_id', 'type')),
    ).annotate(
        occurrence_count=Count('occurrences', filter=in_reports),
        pending_count=Count('occurrences', filter=in_reports & Q(
            occurrences__type__in=list(Occurrence.TREATMENTS_BY_TYPE), occurrences__treatment='',
        )),
    ).order_by('-start_date', '-end_date')


def serialize_competency(competency):
    return {
        'id': competency.id,
        'start_date': competency.start_date.isoformat(),
        'end_date': competency.end_date.isoformat(),
        'finished_at': competency.finished_at.isoformat() if competency.finished_at else None,
        'finished_by': user_name(competency.finished_by),
    }


def serialize_competency_summary(competency):
    return {
        **serialize_competency(competency),
        'reports': sorted(report.type for report in competency.reports.all()),
        'occurrence_count': competency.occurrence_count,
        'pending_count': competency.pending_count,
    }


def serialize_report(report):
    return {
        'type': report.type,
        'file_name': report.file_name,
        'row_count': report.row_count,
        'uploaded_by': user_name(report.uploaded_by),
        'uploaded_at': report.uploaded_at.isoformat(),
    }


def serialize_occurrence(occurrence):
    return {
        'id': occurrence.id,
        'day': occurrence.day.isoformat(),
        'employee_id': occurrence.employee_id,
        'employee_name': occurrence.employee_name,
        'location': occurrence.location,
        'scale': occurrence.scale,
        'type': occurrence.type,
        'evidence': occurrence.evidence,
        'minutes': occurrence.minutes,
        'treatment': occurrence.treatment,
        'note': occurrence.note,
        'responsible': occurrence.responsible,
        'treated_at': occurrence.treated_at.isoformat() if occurrence.treated_at else None,
    }


def serialize_treatment(entry):
    return {
        'id': entry.id,
        'treatment': entry.treatment,
        'note': entry.note,
        'responsible': entry.responsible,
        'user': user_name(entry.user),
        'created_at': entry.created_at.isoformat(),
    }


def serialize_bank_hours_note(note):
    return {
        'note': note.note if note else '',
        'note_by': user_name(note.updated_by) if note else '',
        'note_at': note.updated_at.isoformat() if note else None,
    }


def bank_hours(competency):
    """Os saldos do banco de horas da competência, com a observação de cada colaborador."""
    report = competency.reports.filter(type=SourceReport.BANK_HOURS).first()
    if report is None:
        return []

    notes = {note.employee_id: note for note in competency.bank_hours_notes.select_related('updated_by')}
    rows = []
    for row in report.rows:
        employee = employee_id(row['Matrícula'])
        rows.append({
            'employee_id': employee,
            'employee_name': row.get('Nome') or 'Sem nome',
            'location': row.get('Localização') or 'Não informado',
            'balance': balance_minutes(row['Saldo']),
            **serialize_bank_hours_note(notes.get(employee)),
        })
    return rows


def competency_payload(competency):
    # As linhas dos relatórios ficam no banco: aqui só a contagem delas
    reports = competency.reports.select_related('uploaded_by').defer('rows').annotate(
        row_count=Func('rows', function='jsonb_array_length', output_field=IntegerField()),
    )
    return {
        'competency': serialize_competency(competency),
        'analysed_rows': competency.analysed_rows,
        'reports': {report.type: serialize_report(report) for report in reports},
        'occurrences': [serialize_occurrence(occurrence) for occurrence in competency.occurrences.filter(in_reports=True)],
        'bank_hours': bank_hours(competency),
    }
