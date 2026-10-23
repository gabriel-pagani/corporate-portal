from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('app', '0008_user_registration_permission')]

    operations = [
        migrations.AddField(
            model_name='toner',
            name='idprd',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='IDPRD',
                help_text='Código do produto no RM. Sem ele o toner não pode ser solicitado pelo portal.',
            ),
        ),
        migrations.AddField(
            model_name='toner',
            name='requested_quantity',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='Quantidade Solicitada',
                help_text='Quantidade pedida ao RM e ainda não recebida. Diminui conforme as entradas são registradas.',
            ),
        ),
        migrations.AlterModelOptions(
            name='toner',
            options={
                'ordering': ['location__name', 'name'],
                'verbose_name': 'Toner',
                'verbose_name_plural': 'Toners',
                'permissions': [
                    ('request_toner', 'Can request toners'),
                ],
            },
        ),
    ]
