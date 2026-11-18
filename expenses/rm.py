"""
O lançamento da nota aprovada no RM.

Ainda não implementado: este é o ponto de extensão. O workflow chama
launch_in_rm depois do commit da aprovação na validação, com a nota já na
situação Aprovada. Quando o lançamento existir, é aqui que ele entra (e, se
precisar de um retorno do RM, ele volta para a nota e para o histórico).
"""


def launch_in_rm(expense):
    """Lança a nota aprovada no RM. Por enquanto não faz nada."""
    return None
