"""
As ocorrências da auditoria de jornada, tiradas das linhas dos relatórios do Ahgora.

O Sumarizado conduz: só gera ocorrência o dia de colaborador que aparece nele
dentro da competência, e os relatórios de batidas ímpares e de ausências entram
como complemento desse dia. A interjornada é a exceção: vem pronta do relatório
de intervalos, que já traz o tempo de infração de cada dia.
"""
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from journey_audit.models import Occurrence, SourceReport


PUNCH_COLUMNS = [f'Batida {slot}' for slot in range(1, 7)]

ODD_PUNCH_COLUMNS = [f'Entrada {slot}' for slot in range(1, 5)] + [f'Saída {slot}' for slot in range(1, 5)]

REST_PUNCH_COLUMNS = ['1ª batida', '2ª batida']

REPORT_COLUMNS = {
    SourceReport.SUMMARY: ['Matrícula', 'Nome', 'Dia', 'Localização', 'Departamento', 'Escala', *PUNCH_COLUMNS, 'Extra'],
    SourceReport.ODD_PUNCHES: ['Matrícula', 'Dia', 'Batidas', *ODD_PUNCH_COLUMNS],
    SourceReport.ABSENCES: ['Matrícula', 'Dia', 'Ausência integral', 'Ausência parcial', 'Falta', 'Afastamentos'],
    SourceReport.REST: [
        'Matrícula', 'Nome', 'Data do registro', 'Tipo de intervalo', 'Tempo de Infração',
        'Localização', 'Departamento', 'Filial', 'Cargo', *REST_PUNCH_COLUMNS,
    ],
}

YES = {'sim', 'yes', 'true', '1', 'falta', 'integral'}

# O dia zero das datas do Excel, que guarda a data como número de dias
EXCEL_EPOCH = date(1899, 12, 30)


# Os espaços repetidos também somem: o relatório de intervalos pode vir com
# "Tipo de   intervalo" no cabeçalho
def normalize(text):
    text = unicodedata.normalize('NFD', str(text or ''))
    return ' '.join(''.join(letter for letter in text if not unicodedata.combining(letter)).split()).lower()


# O round do Python arredonda o meio para o par; os minutos seguem o do
# navegador, que sobe o meio, como na planilha que a equipe já conferia
def round_half_up(value):
    return math.floor(value + 0.5)


def to_number(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


# A mesma matrícula vem como 123, 00123 ou 123.0 conforme o relatório
def employee_id(value):
    text = str(value or '').strip()
    return re.sub(r'^0+(?=\d)', '', re.sub(r'\.0$', '', text)) or text


def parse_day(value):
    text = str(value or '').strip()
    if match := re.match(r'(\d{4})-(\d{2})-(\d{2})', text):
        year, month, day = match.groups()
    elif match := re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)', text):
        day, month, year = match.groups()
    elif re.fullmatch(r'\d{5}(\.\d+)?', text):
        return EXCEL_EPOCH + timedelta(days=int(float(text)))
    else:
        return None

    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def clock_minutes(value):
    """O horário de uma batida em minutos desde a meia-noite; None se não há horário."""
    text = str(value or '').strip()
    if match := re.fullmatch(r'(\d{1,2}):(\d{2})(?::\d{2})?', text):
        return int(match[1]) * 60 + int(match[2])

    # O Excel guarda o horário como fração do dia
    number = to_number(text) if text else None
    if number is not None and 0 < number < 1:
        return round_half_up(number * 1440)
    return None


def duration_minutes(value):
    """Uma duração com sinal, em minutos: 02:30, -00:45, 2.5 (horas) ou fração do dia."""
    text = str(value or '').strip().replace(',', '.', 1)
    if match := re.fullmatch(r'(-?)(\d{1,4}):(\d{2})(?::(\d{2}))?', text):
        sign = -1 if match[1] else 1
        return sign * (int(match[2]) * 60 + int(match[3]) + int(match[4] or 0) / 60)

    number = to_number(text) if text else None
    if number is None:
        return 0
    if 0 < number < 1:
        return round_half_up(number * 1440)
    return round_half_up(number * 60)


def balance_minutes(value):
    """O saldo do banco de horas em minutos: -01:30, +12:00 ou 1,5 (horas); None se não for um saldo."""
    text = re.sub(r'\s', '', str(value or ''))
    if match := re.fullmatch(r'([+-]?)(\d{1,4}):(\d{2})(?::\d{2})?', text):
        return (-1 if match[1] == '-' else 1) * (int(match[2]) * 60 + int(match[3]))

    number = to_number(text.replace(',', '.', 1)) if text else None
    return None if number is None else round_half_up(number * 60)


def format_minutes(value):
    sign = '-' if value < 0 else ''
    value = abs(round_half_up(value))
    return f'{sign}{value // 60}h {value % 60:02d}min'


def is_yes(value):
    return normalize(value) in YES


def find_occurrences(summary, odd_punches, absences, rests, start, end):
    """As ocorrências do período e quantas linhas do Sumarizado entraram na análise."""
    odd_by_day = {}
    for row in odd_punches:
        key = (employee_id(row.get('Matrícula')), parse_day(row.get('Dia')))
        if all(key):
            odd_by_day[key] = row

    absences_by_day = defaultdict(list)
    for row in absences:
        key = (employee_id(row.get('Matrícula')), parse_day(row.get('Dia')))
        if all(key):
            absences_by_day[key].append(row)

    found = {}
    analysed = 0
    locations = {}
    for row in summary:
        employee = employee_id(row.get('Matrícula'))
        day = parse_day(row.get('Dia'))
        if not employee or not day or not start <= day <= end:
            continue
        analysed += 1

        base = {
            'day': day,
            'employee_id': employee,
            'employee_name': row.get('Nome') or 'Sem nome',
            # Departamento vale para o relatório que ainda vem com o nome antigo da coluna
            'location': row.get('Localização') or row.get('Departamento') or 'Não informado',
            'scale': row.get('Escala', ''),
        }
        locations.setdefault((employee, day), base['location'])
        occurrences = day_occurrences(row, odd_by_day.get((employee, day)), absences_by_day.get((employee, day), []))
        for type, evidence, minutes in occurrences:
            # Linha repetida no relatório não duplica a ocorrência: vale a primeira
            found.setdefault((day, employee, type), {**base, 'type': type, 'evidence': evidence, 'minutes': minutes})

    # Do relatório de intervalos vale a linha de interjornada com tempo de
    # infração, esteja o dia no Sumarizado ou não; dele só vem a localização,
    # quando o relatório de intervalos não traz nenhuma
    for row in rests:
        employee = employee_id(row.get('Matrícula'))
        day = parse_day(row.get('Data do registro'))
        kind, infraction = row.get('Tipo de intervalo', ''), row.get('Tempo de Infração', '')
        if normalize(kind) != 'interjornada' or not infraction or not employee or not day or not start <= day <= end:
            continue

        punches = ''.join(f' · {column}: {row[column]}' for column in REST_PUNCH_COLUMNS if row.get(column))
        found.setdefault((day, employee, Occurrence.SHORT_REST), {
            'day': day,
            'employee_id': employee,
            'employee_name': row.get('Nome') or 'Sem nome',
            'location': (
                row.get('Localização') or row.get('Departamento') or row.get('Filial')
                or locations.get((employee, day), 'Não informado')
            ),
            # O relatório de intervalos não traz a escala; no lugar dela fica o cargo
            'scale': row.get('Cargo', ''),
            'type': Occurrence.SHORT_REST,
            'evidence': f'Tipo de intervalo: {kind} · Tempo de Infração: {infraction}{punches}',
            'minutes': round_half_up(abs(duration_minutes(infraction))),
        })

    return list(found.values()), analysed


def day_occurrences(row, odd, absences):
    """Os tipos de ocorrência de um dia do Sumarizado, com a evidência e os minutos de cada um."""
    if odd is not None:
        raw = odd.get('Batidas', '')
        details = ' · '.join(f'{column}: {odd[column]}' for column in ODD_PUNCH_COLUMNS if odd.get(column))
        evidence = f'Batidas do relatório: {raw or details or "ver relatório de batidas ímpares"}.'
        if details:
            evidence += f' Detalhamento: {details}'
        yield Occurrence.ODD_PUNCHES, evidence, None

    # O intervalo é o que vai da segunda à terceira batida. Faltando uma delas,
    # não dá para dizer que o intervalo foi curto, só que precisa ser conferido;
    # e o dia sem batida nenhuma fica com o relatório de ausências.
    punches = [(slot, row.get(column, '')) for slot, column in enumerate(PUNCH_COLUMNS, start=1)]
    second, third = punches[1][1], punches[2][1]
    second_minutes, third_minutes = clock_minutes(second), clock_minutes(third)
    if second_minutes is not None and third_minutes is not None:
        gap = third_minutes - second_minutes
        if gap < 0:
            gap += 1440
        # Os minutos são o que faltou para completar 1h de intervalo
        if gap < 60:
            yield Occurrence.SHORT_BREAK, (
                f'Batida 2: {second} · Batida 3: {third} · Intervalo calculado: {format_minutes(gap)}.'
            ), 60 - gap
    elif any(raw for _, raw in punches):
        listed = ' · '.join(f'Batida {slot}: {raw}' for slot, raw in punches if raw)
        yield Occurrence.MISSING_BREAK, (
            f'{listed}. Não foi possível confirmar o intervalo pelas posições Batida 2 e Batida 3.'
        ), None

    extra = row.get('Extra', '')
    extra_minutes = duration_minutes(extra)
    if extra and extra_minutes > 0:
        type = Occurrence.LONG_OVERTIME if extra_minutes > 120 else Occurrence.OVERTIME
        yield type, (
            f'Extra informada no sumarizado: {extra} ({format_minutes(extra_minutes)}).'
        ), round_half_up(extra_minutes)

    for absence in absences:
        integral = is_yes(absence.get('Ausência integral'))
        missed = is_yes(absence.get('Falta'))
        if integral or missed:
            reasons = '; '.join(
                reason for reason, present in (('Ausência integral: Sim', integral), ('Falta: Sim', missed)) if present
            )
            yield Occurrence.ABSENCE, f'Relatório de ausências: {reasons}. Confirmar se a falta procede.', None

        partial = absence.get('Ausência parcial', '')
        if partial and duration_minutes(partial) < 0:
            yield Occurrence.NEGATIVE_BALANCE, (
                f'Ausência parcial informada: {partial} ({format_minutes(duration_minutes(partial))}). '
                'Pode decorrer de atraso, saída antecipada ou intervalo; informação para conferência.'
            ), None

        leave = absence.get('Afastamentos', '')
        if leave:
            yield Occurrence.LEAVE, f'Afastamento: {leave}', None
