from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0005_bank_hours'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sourcereport',
            name='type',
            field=models.CharField(choices=[('I', 'Batidas ímpares'), ('A', 'Ausências'), ('S', 'Sumarizado'), ('N', 'Interjornada'), ('L', 'Afastamentos'), ('B', 'Banco de horas')], max_length=1, verbose_name='Relatório'),
        ),
    ]
