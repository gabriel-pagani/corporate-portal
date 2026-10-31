import re

from django.db import migrations, models


# O tempo das ocorrências analisadas antes do campo existir está só na evidência,
# no formato que a própria análise escreve: "Intervalo calculado: 0h 30min." e
# "Extra informada no sumarizado: 02:30 (2h 30min)."
EVIDENCE_TIME = {
    'J': r'Intervalo calculado: (\d+)h (\d+)min',
    'E': r'\((\d+)h (\d+)min\)\.$',
    'H': r'\((\d+)h (\d+)min\)\.$',
}


def fill_minutes(apps, schema_editor):
    Occurrence = apps.get_model('journey_audit', 'Occurrence')
    changed = []
    for occurrence in Occurrence.objects.filter(type__in=EVIDENCE_TIME, minutes=None).only('type', 'evidence'):
        match = re.search(EVIDENCE_TIME[occurrence.type], occurrence.evidence)
        if match:
            minutes = int(match[1]) * 60 + int(match[2])
            # Do intervalo conta o que faltou para completar 1h
            occurrence.minutes = 60 - minutes if occurrence.type == 'J' else minutes
            changed.append(occurrence)
    Occurrence.objects.bulk_update(changed, ['minutes'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0002_occurrence_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='occurrence',
            name='minutes',
            field=models.PositiveIntegerField(blank=True, help_text='O tempo que a ocorrência mede: as horas extras do dia ou o que faltou para 1h de intervalo.', null=True, verbose_name='Minutos'),
        ),
        migrations.RunPython(fill_minutes, migrations.RunPython.noop),
    ]
