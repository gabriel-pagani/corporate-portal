import pyodbc
from contextlib import contextmanager
from django.conf import settings


def get_connection():
    parts = [
        f"DRIVER={{{settings.SQLSERVER_DRIVER}}}",
        f"SERVER={settings.SQLSERVER_HOST}",
        f"DATABASE={settings.SQLSERVER_DB}",
        f"UID={settings.SQLSERVER_USER}",
        f"PWD={settings.SQLSERVER_PASSWORD}",
    ]

    if 'freetds' in settings.SQLSERVER_DRIVER.lower():
        # FreeTDS usa PORT/TDS_Version em vez das opções de TLS do driver da Microsoft
        parts.append(f"PORT={settings.SQLSERVER_PORT}")
        parts.append(f"TDS_Version={settings.SQLSERVER_TDS_VERSION}")
    else:
        parts.append("TrustServerCertificate=yes")

    return pyodbc.connect(';'.join(parts))


@contextmanager
def _cursor():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            yield cursor
        connection.commit()
    finally:
        connection.close()


def execute_query(query: str, params=None) -> list:
    """Executa a query e retorna as linhas quando houver resultado."""
    with _cursor() as cursor:
        if params is not None:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        if cursor.description is not None:
            return cursor.fetchall()

    return []
