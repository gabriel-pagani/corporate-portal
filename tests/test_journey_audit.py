import io
import json
import zipfile
from datetime import date
import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from app.models import User
from journey_audit.admin import CompetencyAdmin, OccurrenceAdmin
from journey_audit.models import Competency, Occurrence, OccurrenceTreatment, SourceReport
from journey_audit.analysis import (
    clock_minutes, duration_minutes, employee_id, format_minutes, parse_day,
)
from journey_audit.audit import current_period


START = '2026-10-21'
END = '2026-11-20'

DELETION_NOTE = 'A exclusão remove permanentemente'.encode()

SUMMARY_HEADER = [
    'Matrícula', 'Nome', 'Dia', 'Departamento', 'Escala',
    'Batida 1', 'Batida 2', 'Batida 3', 'Batida 4', 'Batida 5', 'Batida 6', 'Extra',
]

SUMMARY = [
    ['001', 'Ana Souza', '21/10/2026', 'RH', '08:00 às 17:00', '08:00', '12:00', '12:30', '17:00', '', '', '02:30'],
    ['001', 'Ana Souza', '22/10/2026', 'RH', '08:00 às 17:00', '08:00', '12:00', '', '', '', '', '00:45'],
    ['2', 'Bruno Lima', '23/10/2026', 'Frota', '', '', '', '', '', '', '', ''],
    ['2', 'Bruno Lima', '25/10/2026', 'Frota', '', '08:00', '12:00', '13:00', '17:00', '', '', ''],
    # Fora da competência e sem matrícula: não entram na análise
    ['001', 'Ana Souza', '20/10/2026', 'RH', '', '08:00', '12:00', '12:10', '17:00', '', '', ''],
    ['', 'Sem matrícula', '24/10/2026', 'RH', '', '08:00', '12:00', '12:10', '17:00', '', '', ''],
]

ODD_PUNCHES = [
    ['Matrícula', 'Dia', 'Batidas', 'Entrada 1', 'Saída 1', 'Entrada 2'],
    ['0002', '25/10/2026', '08:00 12:00 13:00', '08:00', '12:00', '13:00'],
]

ABSENCES = [
    ['Matrícula', 'Dia', 'Ausência integral', 'Ausência parcial', 'Falta', 'Afastamentos'],
    ['2', '23/10/2026', 'Sim', '-01:30', '', 'Atestado médico'],
]


def make_user(*codenames, username='operador'):
    user = User.objects.create_user(username=username, password='senha', first_name='Operador', last_name='RH')
    user.user_permissions.set(Permission.objects.filter(
        content_type__app_label__in=['app', 'journey_audit'], codename__in=codenames,
    ))
    return user


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type='application/json')


def csv_file(rows, name='relatorio.csv', delimiter=';', encoding='utf-8'):
    content = '\r\n'.join(delimiter.join(row) for row in rows)
    return SimpleUploadedFile(name, content.encode(encoding), content_type='text/csv')


def upload(client, report_type, file, start=START, end=END):
    return client.post(reverse('journey_audit:reports-api'), {
        'start_date': start, 'end_date': end, 'type': report_type, 'file': file,
    })


def occurrences(competency=None, **filters):
    queryset = Occurrence.objects.filter(**filters)
    if competency:
        queryset = queryset.filter(competency=competency)
    return {(o.employee_id, o.day.isoformat(), o.type): o for o in queryset}


@pytest.fixture
def editor(client):
    user = make_user('view_competency', 'change_competency')
    client.force_login(user)
    return user


@pytest.fixture
def imported(client, editor):
    assert upload(client, SourceReport.SUMMARY, csv_file([SUMMARY_HEADER, *SUMMARY])).status_code == 201
    return Competency.objects.get()


def make_occurrence(competency, day, type=Occurrence.ODD_PUNCHES, employee='10', **fields):
    return Occurrence.objects.create(
        competency=competency, day=day, employee_id=employee, employee_name=f'Colaborador {employee}',
        department='RH', type=type, evidence='Batidas do relatório: 08:00.', **fields,
    )


def test_duration_reads_clock_hours_and_day_fractions():
    assert duration_minutes('02:30') == 150
    assert duration_minutes('-00:45') == -45
    assert duration_minutes('01:30:30') == 90.5
    assert duration_minutes('1,5') == 90
    assert duration_minutes('0.0625') == 90
    assert duration_minutes('') == 0
    assert duration_minutes('abc') == 0


def test_clock_minutes_needs_a_time():
    assert clock_minutes('08:05') == 485
    assert clock_minutes('08:00:59') == 480
    assert clock_minutes('0.5') == 720
    assert clock_minutes('') is None
    assert clock_minutes('8h') is None
    assert clock_minutes('0') is None


def test_format_minutes_rounds_half_up():
    assert format_minutes(150) == '2h 30min'
    assert format_minutes(-90) == '-1h 30min'
    assert format_minutes(59.5) == '1h 00min'


def test_parse_day_accepts_brazilian_iso_and_excel_dates():
    assert parse_day('21/10/2026') == date(2026, 10, 21)
    assert parse_day('1/2/2026') == date(2026, 2, 1)
    assert parse_day('2026-10-21T00:00:00') == date(2026, 10, 21)
    assert parse_day('46320') == date(2026, 10, 25)
    assert parse_day('31/02/2026') is None
    assert parse_day('amanhã') is None


def test_employee_id_matches_across_reports():
    assert employee_id('00123') == '123'
    assert employee_id('123.0') == '123'
    assert employee_id('000') == '0'
    assert employee_id('A12') == 'A12'


@pytest.mark.parametrize('today, period', [
    (date(2026, 10, 30), (date(2026, 10, 21), date(2026, 11, 20))),
    (date(2026, 10, 20), (date(2026, 9, 21), date(2026, 10, 20))),
    (date(2026, 1, 5), (date(2025, 12, 21), date(2026, 1, 20))),
    (date(2026, 12, 21), (date(2026, 12, 21), date(2027, 1, 20))),
    (date(2026, 2, 21), (date(2026, 2, 21), date(2026, 3, 20))),
])
def test_current_period_runs_from_the_21st_to_the_20th(today, period):
    assert current_period(today) == period


@pytest.mark.django_db
def test_page_requires_view_permission(client):
    client.force_login(make_user())
    assert client.get(reverse('journey_audit:audit')).status_code == 403


@pytest.mark.django_db
def test_viewer_cannot_import_or_treat(client):
    client.force_login(make_user('view_competency'))
    content = client.get(reverse('journey_audit:audit')).content
    assert b'data-report-input' not in content
    assert b'id="treatment-form"' not in content

    response = upload(client, SourceReport.SUMMARY, csv_file([SUMMARY_HEADER, *SUMMARY]))
    assert response.status_code == 403
    assert not Competency.objects.exists()


@pytest.mark.django_db
def test_editor_sees_import_and_treatment(client, editor):
    content = client.get(reverse('journey_audit:audit')).content
    assert b'data-report-input="S"' in content
    assert b'id="treatment-form"' in content
    assert DELETION_NOTE not in content


@pytest.mark.django_db
def test_home_links_to_the_audit_only_with_permission(client):
    client.force_login(make_user())
    assert reverse('journey_audit:audit').encode() not in client.get(reverse('app:home')).content

    client.force_login(make_user('view_competency', username='rh'))
    assert reverse('journey_audit:audit').encode() in client.get(reverse('app:home')).content


@pytest.mark.django_db
def test_api_rejects_anonymous(client):
    assert client.get(reverse('journey_audit:competencies-api')).status_code == 401
    assert client.get(reverse('journey_audit:recurrence-api')).status_code == 401


@pytest.mark.django_db
def test_import_builds_occurrences_from_the_three_reports(client, editor):
    # Sem o Sumarizado não há dia para analisar, em qualquer ordem de envio
    assert upload(client, SourceReport.ODD_PUNCHES, csv_file(ODD_PUNCHES)).status_code == 201
    assert upload(client, SourceReport.ABSENCES, csv_file(ABSENCES)).status_code == 201
    assert not Occurrence.objects.exists()

    response = upload(client, SourceReport.SUMMARY, csv_file([SUMMARY_HEADER, *SUMMARY], name='sumarizado.csv'))
    assert response.status_code == 201

    competency = Competency.objects.get()
    assert (competency.start_date, competency.end_date, competency.created_by) == (date(2026, 10, 21), date(2026, 11, 20), editor)
    assert competency.analysed_rows == 4

    found = occurrences()
    assert {key: o.evidence for key, o in found.items()} == {
        ('1', '2026-10-21', Occurrence.SHORT_BREAK): 'Batida 2: 12:00 · Batida 3: 12:30 · Intervalo calculado: 0h 30min.',
        ('1', '2026-10-21', Occurrence.LONG_OVERTIME): 'Extra informada no sumarizado: 02:30 (2h 30min).',
        ('1', '2026-10-22', Occurrence.MISSING_BREAK): (
            'Batida 1: 08:00 · Batida 2: 12:00. Não foi possível confirmar o intervalo pelas posições Batida 2 e Batida 3.'
        ),
        ('1', '2026-10-22', Occurrence.OVERTIME): 'Extra informada no sumarizado: 00:45 (0h 45min).',
        ('2', '2026-10-23', Occurrence.ABSENCE): 'Relatório de ausências: Ausência integral: Sim. Confirmar se a falta procede.',
        ('2', '2026-10-23', Occurrence.NEGATIVE_BALANCE): (
            'Ausência parcial informada: -01:30 (-1h 30min). '
            'Pode decorrer de atraso, saída antecipada ou intervalo; informação para conferência.'
        ),
        ('2', '2026-10-23', Occurrence.LEAVE): 'Afastamento: Atestado médico',
        ('2', '2026-10-25', Occurrence.ODD_PUNCHES): (
            'Batidas do relatório: 08:00 12:00 13:00. Detalhamento: Entrada 1: 08:00 · Entrada 2: 13:00 · Saída 1: 12:00'
        ),
    }
    ana = found[('1', '2026-10-21', Occurrence.SHORT_BREAK)]
    assert (ana.employee_name, ana.department, ana.scale) == ('Ana Souza', 'RH', '08:00 às 17:00')

    payload = response.json()
    assert len(payload['occurrences']) == 8
    assert payload['analysed_rows'] == 4
    assert {code: report['row_count'] for code, report in payload['reports'].items()} == {'I': 1, 'A': 1, 'S': 6}
    assert payload['reports']['S']['file_name'] == 'sumarizado.csv'
    assert payload['reports']['S']['uploaded_by'] == 'Operador RH'


@pytest.mark.django_db
def test_reimport_keeps_treatments_and_hides_what_left_the_reports(client, editor, imported):
    missing_break = occurrences(type=Occurrence.MISSING_BREAK)[('1', '2026-10-22', Occurrence.MISSING_BREAK)]
    url = reverse('journey_audit:treatments-api', args=[missing_break.id])
    assert post_json(client, url, {
        'treatment': Occurrence.BREAK_RECORDED, 'note': 'Intervalo lançado no Ahgora.', 'responsible': 'Carla',
    }).status_code == 201

    # O dia 22 foi corrigido no Ahgora, e a Ana mudou de departamento
    corrected = [SUMMARY_HEADER, [*SUMMARY[0][:3], 'Financeiro', *SUMMARY[0][4:]], *SUMMARY[2:]]
    response = upload(client, SourceReport.SUMMARY, csv_file(corrected))
    assert response.status_code == 201
    assert all(item['id'] != missing_break.id for item in response.json()['occurrences'])

    missing_break.refresh_from_db()
    assert (missing_break.in_reports, missing_break.treatment, missing_break.note) == (
        False, Occurrence.BREAK_RECORDED, 'Intervalo lançado no Ahgora.',
    )
    assert occurrences(type=Occurrence.SHORT_BREAK)[('1', '2026-10-21', Occurrence.SHORT_BREAK)].department == 'Financeiro'

    # Voltando ao relatório, volta à conferência com a tratativa que já tinha
    assert upload(client, SourceReport.SUMMARY, csv_file([SUMMARY_HEADER, *SUMMARY])).status_code == 201
    missing_break.refresh_from_db()
    assert (missing_break.in_reports, missing_break.treatment) == (True, Occurrence.BREAK_RECORDED)
    assert Occurrence.objects.count() == 4
    assert SourceReport.objects.get().file_name == 'relatorio.csv'


@pytest.mark.django_db
def test_csv_in_windows_encoding_with_commas(client, editor):
    rows = [['Matrícula', 'Nome', 'Dia', 'Batida 1'], ['7', 'Célia', '21/10/2026', '08:00']]
    response = upload(client, SourceReport.SUMMARY, csv_file(rows, delimiter=',', encoding='cp1252'))
    assert response.status_code == 201

    occurrence = Occurrence.objects.get()
    assert (occurrence.employee_name, occurrence.department, occurrence.type) == (
        'Célia', 'Não informado', Occurrence.MISSING_BREAK,
    )


def xlsx_file(rows, name='sumarizado.xlsx'):
    """Um .xlsx mínimo: textos compartilhados, números e texto inline, como os do Ahgora."""
    strings = []

    def cell(reference, value):
        if isinstance(value, (int, float)):
            return f'<c r="{reference}"><v>{value}</v></c>'
        if value.startswith('inline:'):
            return f'<c r="{reference}" t="inlineStr"><is><t>{value[7:]}</t></is></c>'
        strings.append(value)
        return f'<c r="{reference}" t="s"><v>{len(strings) - 1}</v></c>'

    sheet_rows = ''.join(
        f'<row r="{number}">' + ''.join(cell(f'{chr(65 + column)}{number}', value) for column, value in enumerate(row) if value != '') + '</row>'
        for number, row in enumerate(rows, start=1)
    )
    namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    relationships = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/workbook.xml', (
            f'<workbook xmlns="{namespace}" xmlns:r="{relationships}">'
            '<sheets><sheet name="Relatório" sheetId="1" r:id="rId7"/></sheets></workbook>'
        ))
        archive.writestr('xl/_rels/workbook.xml.rels', (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId7" Type="worksheet" Target="worksheets/dados.xml"/></Relationships>'
        ))
        archive.writestr('xl/worksheets/dados.xml', f'<worksheet xmlns="{namespace}"><sheetData>{sheet_rows}</sheetData></worksheet>')
        archive.writestr('xl/sharedStrings.xml', (
            f'<sst xmlns="{namespace}">' + ''.join(f'<si><t>{text}</t></si>' for text in strings) + '</sst>'
        ))
    return SimpleUploadedFile(name, buffer.getvalue())


@pytest.mark.django_db
def test_xlsx_report_is_read_from_the_first_sheet(client, editor):
    # Matrícula e data como número, horários como fração do dia
    rows = [
        ['MATRICULA', 'Nome', 'Dia', 'Departamento', 'Batida 1', 'Batida 2', 'Batida 3', 'Extra'],
        [42, 'inline:Davi Rocha', 46320, 'Portaria', '07:00', 0.5, 0.520833333333333, '03:00'],
    ]
    assert upload(client, SourceReport.SUMMARY, xlsx_file(rows)).status_code == 201

    found = occurrences()
    assert set(found) == {('42', '2026-10-25', Occurrence.SHORT_BREAK), ('42', '2026-10-25', Occurrence.LONG_OVERTIME)}
    short_break = found[('42', '2026-10-25', Occurrence.SHORT_BREAK)]
    assert (short_break.employee_name, short_break.department) == ('Davi Rocha', 'Portaria')
    assert short_break.evidence.endswith('Intervalo calculado: 0h 30min.')


@pytest.mark.django_db
@pytest.mark.parametrize('file, message', [
    (SimpleUploadedFile('ponto.xls', b'antigo'), 'O formato .xls antigo não é compatível.'),
    (SimpleUploadedFile('ponto.pdf', b'%PDF'), 'Formato não reconhecido. Selecione um arquivo .xlsx ou .csv.'),
    (SimpleUploadedFile('ponto.xlsx', b'nao e zip'), 'O arquivo não parece ser um Excel .xlsx válido.'),
    (SimpleUploadedFile('ponto.csv', b'\r\n;;\r\n'), 'A planilha está vazia.'),
])
def test_rejects_unreadable_files(client, editor, file, message):
    response = upload(client, SourceReport.SUMMARY, file)
    assert response.status_code == 400
    assert response.json()['detail'].startswith(message)
    assert not Competency.objects.exists()


@pytest.mark.django_db
def test_rejects_report_without_the_key_columns(client, editor):
    response = upload(client, SourceReport.ABSENCES, csv_file([['Matrícula', 'Data'], ['1', '21/10/2026']]))
    assert response.status_code == 400
    assert response.json()['detail'] == 'O arquivo não tem a coluna Dia. Confira se é mesmo o relatório "Ausências".'

    response = upload(client, SourceReport.SUMMARY, csv_file([['Nome'], ['Ana']]))
    assert response.json()['detail'].startswith('O arquivo não tem as colunas Matrícula e Dia.')


@pytest.mark.django_db
def test_rejects_spreadsheet_that_expands_too_much(client, editor, monkeypatch):
    monkeypatch.setattr('journey_audit.reports.MAX_UNCOMPRESSED_SIZE', 100)
    rows = [SUMMARY_HEADER, *SUMMARY]
    response = upload(client, SourceReport.SUMMARY, xlsx_file(rows))
    assert response.status_code == 400
    assert response.json()['detail'] == 'A planilha é grande demais para ser importada.'


@pytest.mark.django_db
def test_rejects_period_ending_before_it_starts(client, editor):
    response = upload(client, SourceReport.SUMMARY, csv_file([SUMMARY_HEADER, *SUMMARY]), start=END, end=START)
    assert response.status_code == 400
    assert response.json()['detail'] == 'O fim da competência deve ser igual ou posterior ao início.'


@pytest.mark.django_db
def test_treatment_requires_note_and_responsible(client, editor, imported):
    occurrence = Occurrence.objects.get(type=Occurrence.MISSING_BREAK)
    url = reverse('journey_audit:treatments-api', args=[occurrence.id])

    response = post_json(client, url, {'treatment': Occurrence.BREAK_RECORDED, 'note': '  ', 'responsible': 'Carla'})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Registre uma observação antes de salvar a tratativa.'

    response = post_json(client, url, {'treatment': Occurrence.BREAK_RECORDED, 'note': 'Conferido.', 'responsible': ''})
    assert response.json()['detail'] == 'Informe quem realizou a conferência.'
    assert not OccurrenceTreatment.objects.exists()


@pytest.mark.django_db
def test_treatment_must_fit_the_occurrence(client, editor, imported):
    missing_break = Occurrence.objects.get(type=Occurrence.MISSING_BREAK)
    response = post_json(client, reverse('journey_audit:treatments-api', args=[missing_break.id]), {
        'treatment': Occurrence.ADJUSTED, 'note': 'Ajustado.', 'responsible': 'Carla',
    })
    assert response.status_code == 400
    assert response.json()['detail'] == 'Escolha um resultado válido para esta ocorrência.'

    short_break = Occurrence.objects.get(type=Occurrence.SHORT_BREAK)
    response = post_json(client, reverse('journey_audit:treatments-api', args=[short_break.id]), {
        'treatment': '', 'note': 'Visto.', 'responsible': 'Carla',
    })
    assert response.status_code == 400
    assert response.json()['detail'] == 'Esta ocorrência é informativa e não pede tratativa.'


@pytest.mark.django_db
def test_treatments_are_kept_in_history(client, editor, imported):
    occurrence = Occurrence.objects.get(type=Occurrence.MISSING_BREAK)
    url = reverse('journey_audit:treatments-api', args=[occurrence.id])

    # Pendente com observação: registra o andamento sem concluir a tratativa
    response = post_json(client, url, {'treatment': '', 'note': 'Aguardando o gestor.', 'responsible': 'Carla'})
    assert response.status_code == 201
    assert response.json()['occurrence']['treatment'] == ''

    response = post_json(client, url, {
        'treatment': Occurrence.NOT_NEEDED, 'note': 'Jornada de meio período.', 'responsible': 'Carla',
    })
    assert response.status_code == 201
    assert response.json()['occurrence']['note'] == 'Jornada de meio período.'

    occurrence.refresh_from_db()
    assert (occurrence.treatment, occurrence.responsible) == (Occurrence.NOT_NEEDED, 'Carla')
    assert occurrence.treated_at is not None

    history = client.get(url).json()['treatments']
    assert [(entry['treatment'], entry['note'], entry['user']) for entry in history] == [
        (Occurrence.NOT_NEEDED, 'Jornada de meio período.', 'Operador RH'),
        ('', 'Aguardando o gestor.', 'Operador RH'),
    ]


@pytest.mark.django_db
def test_one_adjustment_per_employee_in_each_calendar_month(client, editor):
    previous = Competency.objects.create(start_date=date(2026, 9, 21), end_date=date(2026, 10, 20))
    current = Competency.objects.create(start_date=date(2026, 10, 21), end_date=date(2026, 11, 20))
    make_occurrence(previous, date(2026, 10, 15), treatment=Occurrence.ADJUSTED)
    same_month = make_occurrence(current, date(2026, 10, 25))
    next_month = make_occurrence(current, date(2026, 11, 3))
    other_employee = make_occurrence(current, date(2026, 10, 26), employee='11')

    def treat(occurrence, treatment):
        return post_json(client, reverse('journey_audit:treatments-api', args=[occurrence.id]), {
            'treatment': treatment, 'note': 'Conferido.', 'responsible': 'Carla',
        })

    # O ajuste de outubro já foi usado, ainda que na competência anterior
    response = treat(same_month, Occurrence.ADJUSTED)
    assert response.status_code == 400
    assert response.json()['detail'].startswith('Já existe ajuste realizado para esta matrícula no mês.')
    assert treat(same_month, Occurrence.ADJUSTMENT_REFUSED).status_code == 201
    assert treat(next_month, Occurrence.ADJUSTED).status_code == 201
    assert treat(other_employee, Occurrence.ADJUSTED).status_code == 201
    # Salvar de novo o mesmo dia não conta como segundo ajuste
    assert treat(next_month, Occurrence.ADJUSTED).status_code == 201


@pytest.mark.django_db
def test_treatment_requires_change_permission(client, imported):
    client.force_login(make_user('view_competency', username='consulta'))
    occurrence = Occurrence.objects.get(type=Occurrence.MISSING_BREAK)
    url = reverse('journey_audit:treatments-api', args=[occurrence.id])

    assert client.get(url).status_code == 200
    response = post_json(client, url, {'treatment': '', 'note': 'Visto.', 'responsible': 'Carla'})
    assert response.status_code == 403


@pytest.mark.django_db
def test_recurrence_adds_up_every_competency(client, editor):
    previous = Competency.objects.create(start_date=date(2026, 9, 21), end_date=date(2026, 10, 20))
    current = Competency.objects.create(start_date=date(2026, 10, 21), end_date=date(2026, 11, 20))
    make_occurrence(previous, date(2026, 10, 1), treatment=Occurrence.ADJUSTED)
    make_occurrence(current, date(2026, 10, 25))
    # A ocorrência que saiu do relatório continua contando
    make_occurrence(current, date(2026, 11, 2), in_reports=False)
    make_occurrence(current, date(2026, 10, 25), employee='11')
    make_occurrence(current, date(2026, 10, 25), type=Occurrence.SHORT_BREAK, employee='12')

    employees = client.get(reverse('journey_audit:recurrence-api')).json()['employees']
    assert employees == [
        {
            'employee_id': '10', 'employee_name': 'Colaborador 10', 'count': 3, 'adjustments': 1,
            'days': ['2026-10-01', '2026-10-25', '2026-11-02'],
        },
        {
            'employee_id': '11', 'employee_name': 'Colaborador 11', 'count': 1, 'adjustments': 0,
            'days': ['2026-10-25'],
        },
    ]


@pytest.mark.django_db
def test_competency_list_counts_what_is_still_in_the_reports(client, editor, imported):
    Occurrence.objects.filter(type=Occurrence.LONG_OVERTIME).update(in_reports=False)
    Occurrence.objects.filter(type=Occurrence.MISSING_BREAK).update(treatment=Occurrence.BREAK_RECORDED)

    competency = client.get(reverse('journey_audit:competencies-api')).json()['competencies'][0]
    assert (competency['start_date'], competency['end_date'], competency['reports']) == (START, END, ['S'])
    assert (competency['occurrence_count'], competency['pending_count']) == (3, 0)


@pytest.mark.django_db
def test_finish_marks_the_review_and_a_new_report_reopens_it(client, editor, imported):
    response = client.post(reverse('journey_audit:competency-finish-api', args=[imported.id]))
    assert response.status_code == 200
    assert response.json()['competency']['finished_by'] == 'Operador RH'

    imported.refresh_from_db()
    assert (imported.finished_by, imported.finished_at is not None) == (editor, True)

    assert upload(client, SourceReport.ABSENCES, csv_file(ABSENCES)).status_code == 201
    imported.refresh_from_db()
    assert (imported.finished_by, imported.finished_at) == (None, None)


@pytest.mark.django_db
def test_delete_requires_permission_and_takes_everything(client, editor, imported):
    url = reverse('journey_audit:competency-api', args=[imported.id])
    occurrence = Occurrence.objects.get(type=Occurrence.MISSING_BREAK)
    post_json(client, reverse('journey_audit:treatments-api', args=[occurrence.id]), {
        'treatment': Occurrence.NOT_NEEDED, 'note': 'Conferido.', 'responsible': 'Carla',
    })
    assert client.delete(url).status_code == 403

    client.force_login(make_user('view_competency', 'delete_competency', username='admin-rh'))
    assert DELETION_NOTE in client.get(reverse('journey_audit:audit')).content
    assert client.delete(url).status_code == 200
    assert not Competency.objects.exists()
    assert not SourceReport.objects.exists()
    assert not Occurrence.objects.exists()
    assert not OccurrenceTreatment.objects.exists()


@pytest.mark.django_db
def test_page_opens_the_competency_of_the_current_period(client, editor):
    start, end = current_period()
    competency = Competency.objects.create(start_date=start, end_date=end)
    make_occurrence(competency, start, employee='77')
    Competency.objects.create(start_date=date(2020, 1, 21), end_date=date(2020, 2, 20))

    response = client.get(reverse('journey_audit:audit'))
    assert response.status_code == 200
    period = response.context['period']
    assert (period['start_date'], period['end_date']) == (start.isoformat(), end.isoformat())
    assert [item['employee_id'] for item in response.context['competency']['occurrences']] == ['77']
    assert [item['start_date'] for item in response.context['competencies']] == [start.isoformat(), '2020-01-21']


@pytest.mark.django_db
def test_detail_returns_the_selected_competency(client, editor, imported):
    other = Competency.objects.create(start_date=date(2020, 1, 21), end_date=date(2020, 2, 20))
    make_occurrence(other, date(2020, 1, 25), employee='88')

    payload = client.get(reverse('journey_audit:competency-api', args=[other.id])).json()
    assert payload['competency']['start_date'] == '2020-01-21'
    assert [item['employee_id'] for item in payload['occurrences']] == ['88']
    assert payload['reports'] == {}


@pytest.mark.django_db
def test_admin_does_not_edit_what_comes_from_the_reports():
    competency_admin = CompetencyAdmin(Competency, site)
    occurrence_admin = OccurrenceAdmin(Occurrence, site)
    assert not competency_admin.has_add_permission(None)
    assert not competency_admin.has_change_permission(None)
    assert not occurrence_admin.has_add_permission(None)
    assert not occurrence_admin.has_change_permission(None)
    assert not occurrence_admin.has_delete_permission(None)
