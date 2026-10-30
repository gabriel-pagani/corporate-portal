import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Competency',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField(verbose_name='Início')),
                ('end_date', models.DateField(verbose_name='Fim')),
                ('analysed_rows', models.PositiveIntegerField(default=0, help_text='Linhas do Sumarizado que caíram dentro da competência na última análise.', verbose_name='Registros analisados')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='Conferência finalizada em')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Criada por')),
                ('finished_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Finalizada por')),
            ],
            options={
                'verbose_name': 'Competência',
                'verbose_name_plural': 'Competências',
                'ordering': ['-start_date', '-end_date'],
            },
        ),
        migrations.CreateModel(
            name='Occurrence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField(verbose_name='Data')),
                ('employee_id', models.CharField(max_length=30, verbose_name='Matrícula')),
                ('employee_name', models.CharField(max_length=150, verbose_name='Colaborador')),
                ('department', models.CharField(max_length=150, verbose_name='Departamento')),
                ('scale', models.CharField(blank=True, max_length=255, verbose_name='Escala')),
                ('type', models.CharField(choices=[('I', 'Batidas ímpares'), ('F', 'Falta a confirmar'), ('M', 'Intervalo sem marcações suficientes'), ('J', 'Intrajornada inferior a 1h'), ('E', 'Horas extras'), ('H', 'Horas extras acima de 2h'), ('S', 'Saldo negativo de jornada'), ('A', 'Afastamento informado')], max_length=1, verbose_name='Ocorrência')),
                ('evidence', models.TextField(verbose_name='Evidência')),
                ('in_reports', models.BooleanField(default=True, help_text='Desmarcada quando a ocorrência deixa de aparecer num relatório importado depois. Ela sai da conferência, mas continua contando na recorrência e no ajuste mensal.', verbose_name='Presente nos relatórios')),
                ('treatment', models.CharField(blank=True, choices=[('A', 'Ajuste realizado'), ('R', 'Ajuste recusado — ajuste mensal já utilizado'), ('F', 'Falta confirmada'), ('T', 'Justificada — atestado'), ('D', 'Justificada — declaração'), ('O', 'Justificada — outro motivo'), ('S', 'Suspensão'), ('L', 'Intervalo lançado'), ('C', 'Não necessário após conferência'), ('N', 'Não procede')], max_length=1, verbose_name='Tratativa')),
                ('note', models.TextField(blank=True, verbose_name='Observação')),
                ('responsible', models.CharField(blank=True, max_length=150, verbose_name='Responsável')),
                ('treated_at', models.DateTimeField(blank=True, null=True, verbose_name='Tratada em')),
                ('competency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='occurrences', to='journey_audit.competency', verbose_name='Competência')),
            ],
            options={
                'verbose_name': 'Ocorrência de Jornada',
                'verbose_name_plural': 'Ocorrências de Jornada',
                'ordering': ['day', 'employee_name', 'employee_id', 'type'],
            },
        ),
        migrations.CreateModel(
            name='OccurrenceTreatment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('treatment', models.CharField(blank=True, choices=[('A', 'Ajuste realizado'), ('R', 'Ajuste recusado — ajuste mensal já utilizado'), ('F', 'Falta confirmada'), ('T', 'Justificada — atestado'), ('D', 'Justificada — declaração'), ('O', 'Justificada — outro motivo'), ('S', 'Suspensão'), ('L', 'Intervalo lançado'), ('C', 'Não necessário após conferência'), ('N', 'Não procede')], max_length=1, verbose_name='Tratativa')),
                ('note', models.TextField(verbose_name='Observação')),
                ('responsible', models.CharField(max_length=150, verbose_name='Responsável')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Data')),
                ('occurrence', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='treatments', to='journey_audit.occurrence', verbose_name='Ocorrência')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Usuário')),
            ],
            options={
                'verbose_name': 'Tratativa de Ocorrência',
                'verbose_name_plural': 'Tratativas de Ocorrência',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='SourceReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('I', 'Batidas ímpares'), ('A', 'Ausências'), ('S', 'Sumarizado')], max_length=1, verbose_name='Relatório')),
                ('file_name', models.CharField(max_length=255, verbose_name='Arquivo')),
                ('rows', models.JSONField(default=list, verbose_name='Linhas')),
                ('uploaded_at', models.DateTimeField(auto_now=True, verbose_name='Enviado em')),
                ('competency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reports', to='journey_audit.competency', verbose_name='Competência')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Enviado por')),
            ],
            options={
                'verbose_name': 'Relatório do Ahgora',
                'verbose_name_plural': 'Relatórios do Ahgora',
                'ordering': ['competency', 'type'],
            },
        ),
        migrations.AddConstraint(
            model_name='competency',
            constraint=models.UniqueConstraint(fields=('start_date', 'end_date'), name='unique_competency_period', violation_error_message='Já existe uma competência com este período.'),
        ),
        migrations.AddConstraint(
            model_name='occurrence',
            constraint=models.UniqueConstraint(fields=('competency', 'day', 'employee_id', 'type'), name='unique_occurrence_per_competency'),
        ),
        migrations.AddConstraint(
            model_name='sourcereport',
            constraint=models.UniqueConstraint(fields=('competency', 'type'), name='unique_report_per_competency'),
        ),
    ]
