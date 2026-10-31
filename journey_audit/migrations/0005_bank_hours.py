import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0004_interjornada'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='sourcereport',
            name='type',
            field=models.CharField(choices=[('I', 'Batidas ímpares'), ('A', 'Ausências'), ('S', 'Sumarizado'), ('N', 'Interjornada'), ('B', 'Banco de horas')], max_length=1, verbose_name='Relatório'),
        ),
        migrations.CreateModel(
            name='BankHoursNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('employee_id', models.CharField(max_length=30, verbose_name='Matrícula')),
                ('note', models.TextField(blank=True, verbose_name='Observação')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
                ('competency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_hours_notes', to='journey_audit.competency', verbose_name='Competência')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Atualizada por')),
            ],
            options={
                'verbose_name': 'Observação do Banco de Horas',
                'verbose_name_plural': 'Observações do Banco de Horas',
                'ordering': ['competency', 'employee_id'],
                'constraints': [models.UniqueConstraint(fields=('competency', 'employee_id'), name='unique_bank_hours_note_per_employee')],
            },
        ),
    ]
