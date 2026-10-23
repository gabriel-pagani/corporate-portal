from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0009_toner_request')]

    operations = [
        migrations.AlterField(
            model_name='toner',
            name='idprd',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                unique=True,
                error_messages={'unique': 'Já existe um toner cadastrado com este IDPRD.'},
                verbose_name='IDPRD',
                help_text='Código do produto no RM. Sem ele o toner não pode ser solicitado pelo portal.',
            ),
        ),
    ]
