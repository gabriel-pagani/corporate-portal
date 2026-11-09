"""
As ocorrências da auditoria de jornada, tiradas das linhas dos relatórios do Ahgora.

O Sumarizado conduz: só gera ocorrência o dia de colaborador que aparece nele
dentro da competência, e os relatórios de batidas ímpares e de ausências entram
como complemento desse dia. A interjornada é a exceção: vem pronta do relatório
de intervalos, que já traz o tempo de infração de cada dia.

O relatório de afastamentos não gera ocorrência: dele saem o ranking de
atestados, a lista dos afastamentos do mês e o contexto mostrado ao tratar uma
ocorrência, sem mudar o tipo dela.

O departamento Serviços/Obras fica fora da auditoria: a jornada dele é
acompanhada pelo banco de horas das obras.
"""
import math
import re
import unicodedata
from calendar import FRIDAY, MONDAY, SATURDAY, SUNDAY, THURSDAY, TUESDAY, WEDNESDAY
from collections import defaultdict
from datetime import date, timedelta

from journey_audit.models import Occurrence, SourceReport


PUNCH_COLUMNS = [f'Batida {slot}' for slot in range(1, 7)]

ODD_PUNCH_COLUMNS = [f'Entrada {slot}' for slot in range(1, 5)] + [f'Saída {slot}' for slot in range(1, 5)]

REST_PUNCH_COLUMNS = ['1ª batida', '2ª batida']

LEAVE_REASON_COLUMNS = ['Motivo', 'Tipo de afastamento', 'Afastamento', 'Descrição']

# A localização de cada relatório, na ordem em que vale. O Departamento é o
# setor, e não a localização: dele só sai o Serviços/Obras, que fica de fora
SUMMARY_LOCATION_COLUMNS = ['Localização', 'Cidade']
REST_LOCATION_COLUMNS = ['Localização', 'Cidade', 'Filial']
LEAVE_LOCATION_COLUMNS = ['Localização', 'Cidade', 'Unidade', 'Filial']

REPORT_COLUMNS = {
    SourceReport.SUMMARY: [
        'Matrícula', 'Nome', 'Dia', *SUMMARY_LOCATION_COLUMNS, 'Departamento', 'Escala', *PUNCH_COLUMNS, 'Extra',
    ],
    SourceReport.ODD_PUNCHES: ['Matrícula', 'Dia', 'Batidas', *ODD_PUNCH_COLUMNS],
    SourceReport.ABSENCES: ['Matrícula', 'Dia', 'Ausência integral', 'Ausência parcial', 'Falta', 'Afastamentos'],
    SourceReport.REST: [
        'Matrícula', 'Nome', 'Data do registro', 'Tipo de intervalo', 'Tempo de Infração',
        *REST_LOCATION_COLUMNS, 'Departamento', 'Cargo', *REST_PUNCH_COLUMNS,
    ],
    SourceReport.LEAVES: [
        'Matrícula', 'Nome', 'Dia', 'Data início', 'Data fim', *LEAVE_REASON_COLUMNS, 'ID Afastamento',
        *LEAVE_LOCATION_COLUMNS, 'Departamento',
    ],
}

YES = {'sim', 'yes', 'true', '1', 'falta', 'integral'}

# O dia zero das datas do Excel, que guarda a data como número de dias
EXCEL_EPOCH = date(1899, 12, 30)

WEEKEND = (SATURDAY, SUNDAY)

# Os dias de descanso (DSR) de cada escala, pelo código com que a escala começa
# no Sumarizado, como o RH informou. Nesses dias o intervalo não é cobrado. As
# 12x36 revezam os dias, e o descanso segue a jornada de cada um: nenhum dia da
# semana é fixo. Escala fora da lista (a 117.1 veio sem DSR informado), em
# branco ou NaN:NaN não tem descanso presumido.
SCHEDULE_REST_DAYS = {
    '97.1': WEEKEND,
    '125.1': (FRIDAY, SATURDAY),
    '129.1': (SUNDAY, MONDAY),
    '107.1': (THURSDAY, FRIDAY),
    '114.1': WEEKEND,
    '100.1': (SUNDAY,),
    '122.1': WEEKEND,
    '72.1': WEEKEND,
    '127.3': WEEKEND,
    '103.1': WEEKEND,
    '109.1': (SUNDAY, MONDAY),
    '133.1': (FRIDAY, SATURDAY),
    '105.1': (FRIDAY, SATURDAY),
    '124.1': (SUNDAY, MONDAY),
    '104.1': (TUESDAY, WEDNESDAY),
    '1.1': WEEKEND,
    '134.1': (SUNDAY,),
    '1.7': (SUNDAY,),
    '1.9': (SUNDAY,),
    '1.11': (),
    '1.13': (),
    '114.2': WEEKEND,
    '122.2': WEEKEND,
    '132.1': WEEKEND,
}

# Os dias da semana como as escalas os abreviam, na ordem do weekday() (segunda
# é 0); "segunda", "sábado" e as outras formas longas também valem
WEEKDAY_TOKENS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']
WEEKDAY_TOKEN = re.compile(r'\b(seg|ter|qua|qui|sex|sab|dom)[a-z]*\b')
RANGE_CONNECTORS = ('a', '-', 'ate')

# Jornada com intervalo: o horário de entrada e saída seguido, depois de "e" ou
# "/", do horário da volta, como em 08:00 às 12:00 e 13:00 às 17:00 (já sem acento)
SPLIT_SCHEDULE = re.compile(r'\d{1,2}:\d{2}\s*(?:-|as)\s*\d{1,2}:\d{2}.*(?:e|/)\s*\d{1,2}:\d{2}')

CLOCK = re.compile(r'\d{1,2}:\d{2}')

# Atestados e declarações (médica, odontológica, de comparecimento...), já sem
# acento e em minúsculas
MEDICAL_LEAVE = re.compile(r'atestado|declaracao')

SERVICES_WORKS = ('servicos/obras', 'servicos / obras', 'servicos obras')


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


def first_of(row, columns):
    return next((row[column] for column in columns if row.get(column)), '')


def is_services_works(department):
    text = re.sub(r'[\s_-]+', ' ', normalize(department))
    return any(name in text for name in SERVICES_WORKS) or text in ('servicos', 'obras')


def schedule_code(scale):
    match = re.match(r'\s*(\d+\.\d+)', str(scale or ''))
    return match[1] if match else ''


def is_rest_day(scale, day):
    return day.weekday() in SCHEDULE_REST_DAYS.get(schedule_code(scale), ())


def is_unidentified_schedule(scale):
    return normalize(scale) in ('', 'nan:nan')


def schedule_blocks(text):
    """
    Os trechos da escala, cada um com os dias da semana a que se aplica e os
    horários deles: "seg a qui 08:00 as 12:00 e 13:00 as 18:00 sex 08:00 as 12:00"
    são dois trechos. Os dias seguidos formam um trecho até aparecer um horário;
    "a" entre dois dias é o intervalo de dias (qui a dom passa pelo fim de
    semana, e "-" ou "até" também), e vírgula, "e" ou "/" listam os dias. Sem dia nenhum, a escala vale
    para a semana inteira.
    """
    tokens = list(WEEKDAY_TOKEN.finditer(text))
    if not tokens:
        return [(set(range(7)), text)]

    blocks = []
    days, range_from = set(), None
    for index, token in enumerate(tokens):
        weekday = WEEKDAY_TOKENS.index(token[1])
        if range_from is not None:
            day = range_from
            while day != weekday:
                days.add(day)
                day = (day + 1) % 7
        days.add(weekday)

        last = index + 1 == len(tokens)
        following = text[token.end():] if last else text[token.end():tokens[index + 1].start()]
        if last or CLOCK.search(following):
            blocks.append((days, following))
            days, range_from = set(), None
        else:
            range_from = weekday if following.strip() in RANGE_CONNECTORS else None
    return blocks


def schedule_has_split(scale, day):
    """
    Se a escala prevê intervalo no dia: None quando a escala não foi
    identificada; False quando o dia não está na escala ou a jornada dele não
    tem intervalo, e aí o intervalo não é cobrado.
    """
    if is_unidentified_schedule(scale):
        return None
    covering = [hours for days, hours in schedule_blocks(normalize(scale)) if day.weekday() in days]
    return any(SPLIT_SCHEDULE.search(hours) for hours in covering)


def leave_reason(row):
    return first_of(row, LEAVE_REASON_COLUMNS)


def is_medical_leave(reason):
    return bool(MEDICAL_LEAVE.search(normalize(reason)))


def leave_period(row):
    """
    O primeiro e o último dia do afastamento: o Dia da linha, ou de Data início
    a Data fim. Sem a Data fim o afastamento segue em aberto, e o último dia é None.
    """
    if day := parse_day(row.get('Dia')):
        return day, day
    return parse_day(row.get('Data início')), parse_day(row.get('Data fim'))


def leaves_on(rows, employee, day):
    """Os afastamentos da matrícula que cobrem o dia, sem repetir."""
    found = []
    for row in rows:
        if employee_id(row.get('Matrícula')) != employee:
            continue
        start, end = leave_period(row)
        if start and start <= day <= (end or day):
            leave = {
                'reason': leave_reason(row) or 'Afastamento lançado',
                'start': start.isoformat(),
                'end': end.isoformat() if end else None,
            }
            if leave not in found:
                found.append(leave)
    return found


def leave_events(rows, start, end):
    """
    Os afastamentos de todos os motivos que caem entre start e end, com os dias
    de afastamento dentro do período. As linhas do mesmo afastamento (o mesmo ID
    repetido em cada dia do relatório) viram um só; sem o ID, o afastamento é a
    matrícula com o período e o motivo. A linha sem matrícula, como a de
    totalização, e o departamento Serviços/Obras ficam de fora.
    """
    events = {}
    for row in rows:
        employee = employee_id(row.get('Matrícula'))
        reason = leave_reason(row)
        if not employee or not reason or is_services_works(row.get('Departamento')):
            continue
        first, last = leave_period(row)
        # O afastamento em aberto segue até o fim do período
        if not first or first > end or (last is not None and last < start):
            continue

        days = set()
        day = max(first, start)
        while day <= min(last or end, end):
            days.add(day)
            day += timedelta(days=1)

        identifier = row.get('ID Afastamento')
        key = (employee, 'id', identifier) if identifier else (employee, first, last, normalize(reason))
        event = events.setdefault(key, {
            'key': key,
            'employee_id': employee,
            'employee_name': 'Sem nome',
            'location': 'Não informado',
            'reason': reason,
            'medical': is_medical_leave(reason),
            'periods': set(),
            'days': set(),
        })
        if row.get('Nome'):
            event['employee_name'] = row['Nome']
        if location := first_of(row, LEAVE_LOCATION_COLUMNS):
            event['location'] = location
        event['periods'].add((first, last))
        event['days'] |= days
    return list(events.values())


def medical_leaves(rows, start, end):
    """
    Os atestados e as declarações de cada matrícula, com os dias de afastamento
    que caem entre start e end. O documento é identificado pelo ID do
    afastamento, para o mesmo atestado em dois relatórios não contar duas vezes.
    """
    employees = {}
    for event in leave_events(rows, start, end):
        if not event['medical']:
            continue
        entry = employees.setdefault(event['employee_id'], {
            'employee_id': event['employee_id'], 'leaves': set(), 'days': set(), 'reasons': set(),
        })
        entry['employee_name'] = event['employee_name']
        entry['location'] = event['location']
        entry['leaves'].add(event['key'])
        entry['reasons'].add(event['reason'])
        entry['days'] |= event['days']
    return employees


def find_occurrences(summary, odd_punches, absences, rests, start, end):
    """
    As ocorrências do período, quantas linhas do Sumarizado entraram na análise
    e os dias de colaborador do departamento Serviços/Obras, que ficaram de fora.
    """
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
    excluded = set()
    for row in summary:
        employee = employee_id(row.get('Matrícula'))
        day = parse_day(row.get('Dia'))
        if not employee or not day or not start <= day <= end:
            continue
        if is_services_works(row.get('Departamento')):
            excluded.add((employee, day))
            continue
        analysed += 1

        base = {
            'day': day,
            'employee_id': employee,
            'employee_name': row.get('Nome') or 'Sem nome',
            'location': first_of(row, SUMMARY_LOCATION_COLUMNS) or 'Não informado',
            'scale': row.get('Escala', ''),
        }
        locations.setdefault((employee, day), base['location'])
        occurrences = day_occurrences(row, day, odd_by_day.get((employee, day)), absences_by_day.get((employee, day), []))
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
        if is_services_works(row.get('Departamento')) or (employee, day) in excluded:
            excluded.add((employee, day))
            continue

        punches = ''.join(f' · {column}: {row[column]}' for column in REST_PUNCH_COLUMNS if row.get(column))
        found.setdefault((day, employee, Occurrence.SHORT_REST), {
            'day': day,
            'employee_id': employee,
            'employee_name': row.get('Nome') or 'Sem nome',
            'location': first_of(row, REST_LOCATION_COLUMNS) or locations.get((employee, day), 'Não informado'),
            # O relatório de intervalos não traz a escala; no lugar dela fica o cargo
            'scale': row.get('Cargo', ''),
            'type': Occurrence.SHORT_REST,
            'evidence': f'Tipo de intervalo: {kind} · Tempo de Infração: {infraction}{punches}',
            'minutes': round_half_up(abs(duration_minutes(infraction))),
        })

    return list(found.values()), analysed, excluded


def day_occurrences(row, day, odd, absences):
    """Os tipos de ocorrência de um dia do Sumarizado, com a evidência e os minutos de cada um."""
    if odd is not None:
        details = ' · '.join(f'{column}: {odd[column]}' for column in ODD_PUNCH_COLUMNS if odd.get(column))
        yield Occurrence.ODD_PUNCHES, (
            f'Batidas do relatório: {odd.get("Batidas") or details or "ver relatório de batidas ímpares"}.'
        ), None

    yield from break_occurrences(row, day)

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


def break_occurrences(row, day):
    """
    O intervalo do dia, que vai da segunda à terceira batida. Só é cobrado
    quando a escala prevê intervalo naquele dia, e nunca no dia de descanso
    dela. Faltando uma das batidas, não dá para dizer que o intervalo foi curto,
    só que precisa ser conferido; e o dia sem batida nenhuma fica com o
    relatório de ausências. Com a escala não identificada, todo dia com batida
    pede a conferência manual.
    """
    scale = row.get('Escala', '')
    punches = [(slot, row.get(column, '')) for slot, column in enumerate(PUNCH_COLUMNS, start=1)]
    listed = ' · '.join(f'Batida {slot}: {raw}' for slot, raw in punches if raw)
    if not listed or is_rest_day(scale, day):
        return

    split = schedule_has_split(scale, day)
    if split is None:
        yield Occurrence.MISSING_BREAK, (
            f'Escala não identificada ({scale or "não informada"}). {listed}. '
            'Conferir manualmente se havia intervalo previsto.'
        ), None
        return
    if not split:
        return

    second, third = punches[1][1], punches[2][1]
    second_minutes, third_minutes = clock_minutes(second), clock_minutes(third)
    if second_minutes is None or third_minutes is None:
        yield Occurrence.MISSING_BREAK, (
            f'{listed}. Não foi possível confirmar o intervalo pelas posições Batida 2 e Batida 3.'
        ), None
        return

    gap = third_minutes - second_minutes
    if gap < 0:
        gap += 1440
    # Os minutos são o que faltou para completar 1h de intervalo
    if gap < 60:
        yield Occurrence.SHORT_BREAK, f'Batida 2: {second} · Batida 3: {third} · Intervalo calculado: {format_minutes(gap)}.', 60 - gap
