import re
from app.utils.customer_vendor.connection import execute_query
from app.utils.customer_vendor.qive import cnpj_lookup
from app.utils.customer_vendor.rm import create_new_customer_vendor
from app.utils.customer_vendor.validator import is_valid_cnpj


COMPANY_IDS = ('1', '5', '6')

TYPE_LABELS = {
    'c': 'cliente',
    'f': 'fornecedor',
    'a': 'cliente/fornecedor',
}

NEXT_CODE_QUERY = """
    SELECT
        'F' + RIGHT('00000' + CAST((CAST(SUBSTRING((SELECT TOP 1 CODCFO FROM FCFO WHERE CODCFO LIKE 'F%' AND CODCOLIGADA in (1,5,6) ORDER BY CODCFO DESC), 2, 5) AS INT) + 1) AS VARCHAR), 5) AS COD_FOR,
        'C' + RIGHT('00000' + CAST((CAST(SUBSTRING((SELECT TOP 1 CODCFO FROM FCFO WHERE CODCFO LIKE 'C%' AND CODCOLIGADA in (1,5,6) ORDER BY CODCFO DESC), 2, 5) AS INT) + 1) AS VARCHAR), 5) AS COD_CLI,
        'A' + RIGHT('00000' + CAST((CAST(SUBSTRING((SELECT TOP 1 CODCFO FROM FCFO WHERE CODCFO LIKE 'A%' AND CODCOLIGADA in (1,5,6) ORDER BY CODCFO DESC), 2, 5) AS INT) + 1) AS VARCHAR), 5) AS COD_CLIFOR
"""


def format_cnpj(cnpj: str) -> str:
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def sanitize_entry(entry: dict) -> dict:
    """Normaliza e valida um item da lista, replicando as regras de `add_cnpj_to_list`."""
    cnpj = re.sub(r"\D", "", str(entry.get('cnpj') or ''))

    raw_ie = str(entry.get('ie') or '').strip()
    ie = 'isento' if raw_ie.lower() == 'isento' else re.sub(r"\D", "", raw_ie)

    type_ = str(entry.get('type') or '').strip().lower()

    if not cnpj:
        raise ValueError('Campo "cnpj" obrigatório!')

    if not is_valid_cnpj(cnpj):
        raise ValueError('Cnpj inválido!')

    if ie and ie != 'isento' and not ie.isdigit():
        raise ValueError('Inscrição estadual inválida!')

    if type_ not in TYPE_LABELS:
        raise ValueError('Campo "type" deve ser "c" (cliente), "f" (fornecedor) ou "a" (ambos).')

    return {'cnpj': cnpj, 'ie': ie, 'type': type_}


def register_customer_vendor(cnpj: str, ie: str, type_: str) -> dict:
    """Cadastra um único CNPJ nas coligadas. Retorna o resultado da operação."""
    formatted_cnpj = format_cnpj(cnpj)
    label = TYPE_LABELS[type_]

    existing = execute_query(
        "SELECT TOP 1 CODCFO FROM FCFO WHERE CODCOLIGADA IN (1,5,6) AND CGCCFO = ?",
        (formatted_cnpj,),
    )
    if existing:
        return {
            'cnpj': formatted_cnpj,
            'status': 'skipped',
            'codcfo': existing[0][0],
            'message': f'O {label} {formatted_cnpj} já está cadastrado! CODCFO: {existing[0][0]}',
        }

    codes = execute_query(NEXT_CODE_QUERY)
    codcfo = codes[0][0] if type_ == 'f' else (codes[0][1] if type_ == 'c' else codes[0][2])

    data = cnpj_lookup(codcfo=codcfo, cnpj=cnpj, ie=ie)

    if data['status'].upper() != 'ATIVA':
        raise RuntimeError('CNPJ com situação irregular')

    for company_id in COMPANY_IDS:
        create_new_customer_vendor(
            companyId=company_id,
            code=data['code'],
            shortName=data['shortName'],
            name=data['name'],
            type=data['type'],
            mainNIF=data['mainNIF'],
            stateRegister=data['stateRegister'],
            zipCode=data['zipCode'],
            streetType=data['streetType'],
            streetName=data['streetName'],
            number=data['number'],
            districtType=data['districtType'],
            district=data['district'],
            stateCode=data['stateCode'],
            cityInternalId=data['cityInternalId'],
            phoneNumber=data['phoneNumber'],
            email=data['email'],
            contributor=data['contributor'],
        )

    execute_query(
        "UPDATE FCFO SET CONTRIBUINTE = ?, COMPLEMENTO = ? WHERE CODCOLIGADA IN (1,5,6) AND CGCCFO = ?",
        (
            data['contributor'],
            data['complement'] if data['complement'] else None,
            formatted_cnpj,
        ),
    )

    return {
        'cnpj': formatted_cnpj,
        'status': 'created',
        'codcfo': codcfo,
        'message': f'Sucesso ao cadastrar o {label} {formatted_cnpj}! CODCFO: {codcfo}',
    }


def register_customers_vendors(entries: list) -> dict:
    """Processa a lista de CNPJs e retorna o resultado de cada um."""
    results = []
    seen = set()

    for entry in entries:
        if not isinstance(entry, dict):
            results.append({
                'cnpj': None,
                'status': 'error',
                'message': 'Cada item deve ser um objeto com "cnpj", "ie" e "type".',
            })
            continue

        try:
            item = sanitize_entry(entry)
        except ValueError as e:
            results.append({
                'cnpj': entry.get('cnpj'),
                'status': 'error',
                'message': str(e),
            })
            continue

        if item['cnpj'] in seen:
            results.append({
                'cnpj': format_cnpj(item['cnpj']),
                'status': 'error',
                'message': 'Esse cnpj está duplicado na requisição!',
            })
            continue

        seen.add(item['cnpj'])

        try:
            results.append(register_customer_vendor(item['cnpj'], item['ie'], item['type']))
        except Exception as e:
            results.append({
                'cnpj': format_cnpj(item['cnpj']),
                'status': 'error',
                'message': f'Erro ao cadastrar o {TYPE_LABELS[item["type"]]} {format_cnpj(item["cnpj"])}! ERRO: {e}',
            })

    summary = {
        'total': len(results),
        'created': sum(1 for r in results if r['status'] == 'created'),
        'skipped': sum(1 for r in results if r['status'] == 'skipped'),
        'errors': sum(1 for r in results if r['status'] == 'error'),
    }

    return {'summary': summary, 'results': results}
