from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0003_occurrence_minutes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='occurrence',
            name='minutes',
            field=models.PositiveIntegerField(blank=True, help_text='O tempo que a ocorrência mede: as horas extras do dia, o que faltou para 1h de intervalo ou o tempo de infração da interjornada.', null=True, verbose_name='Minutos'),
        ),
        migrations.AlterField(
            model_name='occurrence',
            name='type',
            field=models.CharField(choices=[('I', 'Batidas ímpares'), ('F', 'Falta a confirmar'), ('M', 'Intervalo sem marcações suficientes'), ('J', 'Intrajornada inferior a 1h'), ('N', 'Interjornada inferior a 11h'), ('E', 'Horas extras'), ('H', 'Horas extras acima de 2h'), ('S', 'Saldo negativo de jornada'), ('A', 'Afastamento informado')], max_length=1, verbose_name='Ocorrência'),
        ),
        migrations.AlterField(
            model_name='sourcereport',
            name='type',
            field=models.CharField(choices=[('I', 'Batidas ímpares'), ('A', 'Ausências'), ('S', 'Sumarizado'), ('N', 'Interjornada')], max_length=1, verbose_name='Relatório'),
        ),
    ]
