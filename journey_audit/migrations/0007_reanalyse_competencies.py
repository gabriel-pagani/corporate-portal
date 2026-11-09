from django.db import migrations


def reanalyse(apps, schema_editor):
    """
    Refaz a análise das competências já salvas com as regras novas: o
    Serviços/Obras fora da auditoria e o intervalo cobrado só no dia em que a
    escala prevê intervalo. A análise é a do código atual, que trabalha com os
    modelos de agora, e por isso roda só onde já há competência: no banco novo
    (como o dos testes) não há nada a refazer.
    """
    from journey_audit.audit import analyse
    from journey_audit.models import Competency

    for competency in Competency.objects.select_for_update().order_by('start_date'):
        analyse(competency)
        competency.save(update_fields=['analysed_rows'])


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0006_leaves'),
    ]

    operations = [
        migrations.RunPython(reanalyse, migrations.RunPython.noop),
    ]
