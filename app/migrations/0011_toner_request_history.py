import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('app', '0010_unique_toner_idprd'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TonerRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[('E', 'Enviada ao RM'), ('F', 'Falha no envio'), ('S', 'Sem resposta do RM')],
                    max_length=1,
                    verbose_name='Situação',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Data')),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Usuário',
                )),
            ],
            options={
                'verbose_name': 'Solicitação de Toner',
                'verbose_name_plural': 'Solicitações de Toner',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TonerRequestItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('idprd', models.PositiveIntegerField(verbose_name='IDPRD')),
                ('quantity', models.PositiveIntegerField(verbose_name='Quantidade')),
                ('request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='app.tonerrequest',
                    verbose_name='Solicitação',
                )),
                ('toner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='request_items',
                    to='app.toner',
                    verbose_name='Toner',
                )),
            ],
            options={
                'verbose_name': 'Item da Solicitação',
                'verbose_name_plural': 'Itens da Solicitação',
                'ordering': ['-request__created_at', 'id'],
            },
        ),
    ]
