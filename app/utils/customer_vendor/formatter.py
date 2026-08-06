import re


def format_name(name: str) -> str:
    from app.constants.abbreviations import abbreviations

    if not name:
        return ""

    name = name.strip()

    name = re.sub(r" & ", " e ", name)

    # remove pontuação (mantém acentos) e números
    name = re.sub(r"[^\w\s]", " ", name, flags=re.UNICODE)
    name = re.sub(r"\d+", " ", name)  # Remove dígitos

    name = name.title()

    # Aplica abreviações (case-insensitive)
    for key, value in abbreviations.items():
        pattern = re.compile(rf"\b{re.escape(key)}\b", flags=re.IGNORECASE)
        name = pattern.sub(value, name)

    name = re.sub(r"\s+", " ", name).strip()  # Colapsa espaços repetidos
    return name


def suffix_remover(text: str) -> str:
    if not text:
        return ""

    # Remove "Sa", "S A" e "Ltda" em qualquer posição (como palavra), com ou sem ponto
    pattern = re.compile(r"(?:\bLtda\b\.?|\bSa\b\.?|\bS\s+A\b\.?)", flags=re.IGNORECASE)
    text = pattern.sub(" ", text)

    # Normaliza espaços após a remoção
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_zipcode(zipCode: str) -> str:
    if not zipCode:
        return ""

    return zipCode.replace(".", "").replace("-", "").strip()


def format_street(street: str) -> list:
    from app.constants.streets import street_types

    if not street:
        return ["", ""]

    # remove pontuação e normaliza espaços
    street = re.sub(r"[^\w\s]", " ", street, flags=re.UNICODE)
    street = re.sub(r"\s+", " ", street).strip().upper()
    street_type = street.split()[0]

    if street_type in street_types:
        street = re.sub(rf"^{re.escape(street_type)}\s+", "", street)
        street_type = street_types[street_type]
        return [street_type, street.title()]
    else:
        return ["1", street.title()]


def format_number(number: str) -> str:
    if not number:
        return ""

    # se não tem dígito retorna ""
    if not re.search(r"\d", number):
        return ""

    return number.upper().strip()


def format_district(district: str) -> list:
    from app.constants.districts import district_types

    if not district:
        return ["", ""]

    # remove pontuação e normaliza espaços
    district = re.sub(r"[^\w\s]", " ", district, flags=re.UNICODE)
    district = re.sub(r"\s+", " ", district).strip().upper()
    district_type = district.split()[0]

    if district_type in district_types:
        district = re.sub(rf"^{re.escape(district_type)}\s+", "", district)
        district_type = district_types[district_type]
        return [district_type, district.title()]
    else:
        return ["1", district.title()]


def format_municipality(municipality: str, state: str) -> str:
    from app.constants.municipalities import municipalities

    if not municipality or not state:
        return ""

    key = (municipality.upper().strip(), state.upper().strip())
    codmun = municipalities.get(key)

    return codmun if codmun else ""


def format_phone(phone: str) -> str:
    if not phone:
        return ""

    phone = phone.replace("(", "").replace(")", "").replace("-", "").replace(" ", "")
    phone = phone.split("/")[0].strip()  # usa apenas o primeiro quando houver mais de um
    return phone
