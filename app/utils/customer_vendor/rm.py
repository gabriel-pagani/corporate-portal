import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings


CUSTOMER_VENDOR_PATH = '/api/framework/v1/customerVendor'


def create_new_customer_vendor(
    companyId: str,
    code: str,
    shortName: str,
    name: str,
    type: int,
    mainNIF: str,
    stateRegister: str,
    zipCode: str,
    streetType: str,
    streetName: str,
    number: str,
    districtType: str,
    district: str,
    stateCode: str,
    cityInternalId: str,
    phoneNumber: str,
    email: str,
    contributor: int,
):
    if not settings.RM_API_ROOT_URL or not settings.RM_USER or not settings.RM_PASSWORD:
        raise RuntimeError('Credenciais do TOTVS RM não configuradas.')

    api_url = f"{settings.RM_API_ROOT_URL.rstrip('/')}{CUSTOMER_VENDOR_PATH}"

    session = requests.Session()
    session.auth = HTTPBasicAuth(settings.RM_USER, settings.RM_PASSWORD)
    session.headers.update({"Accept": "application/json"})

    json = {
        "companyId": companyId,
        "code": code,
        "companyInternalId": f"{companyId}|{code}",
        "shortName": shortName,
        "name": name,
        "type": type,
        "entityType": "J",  # Pessoa jurídica
        "mainNIF": mainNIF,
        "stateRegister": stateRegister,
        "registerSituation": 1,  # Ativo
        "address": {
            "zipCode": zipCode,
            "streetType": streetType,
            "streetName": streetName,
            "number": number,
            "districtType": districtType,
            "district": district,
            "country": {
                "countryInternalId": "1",
                "countryDescription": "Brasil"
            },
            "state": {
                "stateCode": stateCode
            },
            "city": {
                "cityInternalId": cityInternalId
            },
            "communicationInformation": {
                "phoneNumber": phoneNumber,
                "email": email
            }
        },
        "contributor": contributor,
        "fuelOperationType": 3,  # Nenhum
        "complementaryFields": {
            "codcoligada": int(companyId),
            "codcfo": code
        }
    }

    resp = session.post(api_url, json=json, timeout=30)
    resp.raise_for_status()
