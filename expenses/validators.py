"""Limpeza e conferência dos campos da nota, a mesma para o que a IA lê e para o que o Controle digita."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import cycle


def clean_cnpj(value):
    # Desde 2026 o CNPJ pode ter letras
    return re.sub(r'[^0-9A-Za-z]', '', str(value or '')).upper()


def clean_access_key(value):
    return re.sub(r'\D', '', str(value or ''))


def clean_number(value):
    return re.sub(r'[^0-9A-Za-z]', '', str(value or '')).upper()


def check_digit(values, weights):
    """O dígito verificador do módulo 11 usado no CNPJ e na chave de acesso."""
    rest = sum(value * weight for value, weight in zip(reversed(values), cycle(weights))) % 11
    return 0 if rest < 2 else 11 - rest


def valid_cnpj(cnpj):
    """
    Confere os dois dígitos verificadores. No CNPJ alfanumérico cada caractere
    vale o código ASCII menos 48, e os dígitos verificadores seguem numéricos.
    """
    if len(cnpj) != 14 or not cnpj[12:].isdigit() or len(set(cnpj)) == 1:
        return False
    values = [ord(char) - 48 for char in cnpj]
    return all(values[size] == check_digit(values[:size], range(2, 10)) for size in (12, 13))


def valid_access_key(key):
    if len(key) != 44 or not key.isdigit():
        return False
    digits = [int(char) for char in key]
    return digits[-1] == check_digit(digits[:-1], range(2, 10))


def clean_decimal(value, places, limit=10 ** 10):
    """O número com as casas pedidas; None se não for um valor que caiba no banco."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or not 0 <= number < limit:
        return None
    return number.quantize(Decimal(1).scaleb(-places))


def clean_date(value):
    try:
        return date.fromisoformat(str(value or ''))
    except ValueError:
        return None


def clean_text(value, size):
    return ' '.join(str(value or '').split())[:size]
