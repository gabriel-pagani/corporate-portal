"""
Leitura dos relatórios exportados do Ahgora: a primeira planilha do .xlsx, ou o
.csv, sempre com os cabeçalhos na primeira linha.

Das linhas fica só o que a análise usa, com o nome da coluna como o relatório
escreve, e a coluna é encontrada sem ligar para acento e maiúscula.
"""
import csv
import io
import posixpath
import zipfile
import zlib
from contextlib import closing
from xml.etree import ElementTree

from django.core.exceptions import ValidationError

from journey_audit.models import SourceReport
from journey_audit.analysis import REPORT_COLUMNS, normalize


# Sem matrícula e dia nenhuma linha entra na análise: faltando essas colunas, o
# arquivo provavelmente é outro relatório, escolhido no campo errado.
REQUIRED_COLUMNS = ['Matrícula', 'Dia']

MAX_ROWS = 200_000

# Teto do que se descompacta do .xlsx: um arquivo forjado ocupa pouco no upload
# e pode se expandir até esgotar a memória do servidor.
MAX_UNCOMPRESSED_SIZE = 200 * 1024 * 1024

DEFAULT_SHEET = 'xl/worksheets/sheet1.xml'


def read_report(uploaded_file, report_type):
    name = uploaded_file.name.lower()
    if name.endswith('.xlsx'):
        rows = xlsx_rows(uploaded_file)
    elif name.endswith('.csv'):
        rows = csv_rows(uploaded_file)
    elif name.endswith('.xls'):
        raise ValidationError('O formato .xls antigo não é compatível. Salve a planilha como .xlsx ou exporte como CSV.')
    else:
        raise ValidationError('Formato não reconhecido. Selecione um arquivo .xlsx ou .csv.')

    with closing(rows):
        return project_rows(rows, report_type)


def project_rows(rows, report_type):
    """Só as colunas que a análise usa, da primeira linha (o cabeçalho) em diante."""
    header = next(rows, None)
    if header is None:
        raise ValidationError('A planilha está vazia.')

    # De dois cabeçalhos com o mesmo nome vale o primeiro
    positions = {}
    for position, title in sorted(header.items(), reverse=True):
        if title.strip():
            positions[normalize(title)] = position

    columns = {
        column: positions[normalize(column)]
        for column in REPORT_COLUMNS[report_type] if normalize(column) in positions
    }
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise ValidationError(
            f'O arquivo não tem {"a coluna" if len(missing) == 1 else "as colunas"} {" e ".join(missing)}. '
            f'Confira se é mesmo o relatório "{dict(SourceReport.TYPES)[report_type]}".'
        )

    records = []
    for row in rows:
        record = {
            column: value
            for column, position in columns.items()
            if (value := str(row.get(position, '')).strip())
        }
        if not record:
            continue
        records.append(record)
        if len(records) > MAX_ROWS:
            raise ValidationError(f'A planilha passa de {MAX_ROWS:,} linhas.'.replace(',', '.'))

    return records


def csv_rows(uploaded_file):
    data = uploaded_file.read()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        # O Excel em português grava o CSV em Windows-1252 quando não se escolhe o UTF-8
        text = data.decode('cp1252', errors='replace')

    first_line = next((line for line in text.splitlines() if line.strip()), '')
    delimiter = ';' if first_line.count(';') >= first_line.count(',') else ','

    try:
        for row in csv.reader(io.StringIO(text, newline=''), delimiter=delimiter):
            if any(field.strip() for field in row):
                yield {position: value.strip() for position, value in enumerate(row)}
    except csv.Error:
        raise ValidationError('Não foi possível ler o CSV. Exporte o relatório de novo e tente outra vez.')


def xlsx_rows(uploaded_file):
    try:
        archive = zipfile.ZipFile(uploaded_file)
    except zipfile.BadZipFile:
        raise ValidationError('O arquivo não parece ser um Excel .xlsx válido.')

    with archive:
        try:
            shared = shared_strings(archive)
            sheet = first_sheet(archive)
            # Lida linha a linha: a planilha inteira em árvore ocuparia dez vezes
            # o tamanho do arquivo na memória
            for _, element in ElementTree.iterparse(open_entry(archive, sheet)):
                if local_name(element.tag) == 'row':
                    yield row_cells(element, shared)
                    element.clear()
        except (ElementTree.ParseError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError):
            raise ValidationError('A planilha Excel está corrompida ou contém XML inválido.')


def open_entry(archive, name):
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise ValidationError('Não encontrei a primeira planilha dentro do Excel.')
    if info.file_size > MAX_UNCOMPRESSED_SIZE:
        raise ValidationError('A planilha é grande demais para ser importada.')
    return archive.open(info)


def local_name(tag):
    return tag.rsplit('}', 1)[-1]


def first_sheet(archive):
    names = archive.namelist()
    if 'xl/workbook.xml' not in names or 'xl/_rels/workbook.xml.rels' not in names:
        return DEFAULT_SHEET

    workbook = ElementTree.parse(open_entry(archive, 'xl/workbook.xml'))
    sheet = next((element for element in workbook.iter() if local_name(element.tag) == 'sheet'), None)
    if sheet is None:
        return DEFAULT_SHEET
    # O r:id da planilha, qualquer que seja o namespace que o gerador usou
    relation_id = next((value for key, value in sheet.attrib.items() if key.startswith('{') and local_name(key) == 'id'), None)

    relations = ElementTree.parse(open_entry(archive, 'xl/_rels/workbook.xml.rels'))
    for relation in relations.iter():
        if local_name(relation.tag) == 'Relationship' and relation.get('Id') == relation_id:
            target = relation.get('Target', '').lstrip('/')
            return target if target.startswith('xl/') else posixpath.normpath(f'xl/{target}')
    return DEFAULT_SHEET


def shared_strings(archive):
    if 'xl/sharedStrings.xml' not in archive.namelist():
        return []

    strings = []
    for _, element in ElementTree.iterparse(open_entry(archive, 'xl/sharedStrings.xml')):
        if local_name(element.tag) == 'si':
            strings.append(''.join(text.text or '' for text in element.iter() if local_name(text.tag) == 't'))
            element.clear()
    return strings


def column_index(reference):
    index = 0
    for letter in reference.upper():
        if not 'A' <= letter <= 'Z':
            break
        index = index * 26 + ord(letter) - ord('A') + 1
    return max(index, 1) - 1


def row_cells(row, shared):
    cells = {}
    position = -1
    for cell in row:
        if local_name(cell.tag) != 'c':
            continue
        # A referência (B2) é opcional no formato: sem ela, a célula é a seguinte
        reference = cell.get('r')
        position = column_index(reference) if reference else position + 1
        kind = cell.get('t')

        if kind == 'inlineStr':
            value = ''.join(text.text or '' for text in cell.iter() if local_name(text.tag) == 't')
        else:
            stored = next((child for child in cell if local_name(child.tag) == 'v'), None)
            value = (stored.text or '') if stored is not None else ''
            if stored is not None and kind == 's':
                value = shared[int(value)] if value.isdigit() and int(value) < len(shared) else ''
            elif stored is not None and kind == 'b':
                value = 'TRUE' if value == '1' else 'FALSE'

        cells[position] = value
    return cells
