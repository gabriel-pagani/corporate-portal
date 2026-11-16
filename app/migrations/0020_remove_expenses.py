from django.db import migrations, models

# As tabelas do reembolso de despesas, que saiu do portal. O centro de custo fica.
EXPENSES_TABLES = (
    'expenses_guideseen', 'expenses_ignoredwordevent', 'expenses_ignoredword',
    'expenses_expensephoto', 'expenses_expenseitem', 'expenses_expenseevent', 'expenses_expense',
)


def remove_expenses(apps, schema_editor):
    # As permissões, o histórico do reversion e os contadores de acesso do
    # serviço vão junto com os tipos de conteúdo do app
    apps.get_model('app', 'ServiceAccess').objects.filter(service='expenses').delete()
    apps.get_model('contenttypes', 'ContentType').objects.filter(app_label='expenses').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0019_expenses_service'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('reversion', '0002_add_index_on_version_for_content_type_and_db'),
    ]

    operations = [
        migrations.RunSQL(
            [f'DROP TABLE IF EXISTS {table} CASCADE' for table in EXPENSES_TABLES]
            + ["DELETE FROM django_migrations WHERE app = 'expenses'"],
            migrations.RunSQL.noop,
        ),
        migrations.RunPython(remove_expenses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='costcenter',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Ativo'),
        ),
        migrations.AlterField(
            model_name='user',
            name='cost_center',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.PROTECT, related_name='users', to='app.costcenter', verbose_name='Centro de custo'),
        ),
        migrations.AlterField(
            model_name='serviceaccess',
            name='service',
            field=models.CharField(choices=[('contacts', 'Lista de Contatos'), ('notifications', 'Mural de Notificações'), ('tickets', 'Central de Chamados'), ('library', 'Biblioteca'), ('dashboards', 'Central de Dashboards'), ('toners', 'Controle de Toners'), ('customers-vendors', 'Clientes e Fornecedores'), ('journey-audit', 'Auditoria de Jornada')], max_length=30, verbose_name='Serviço'),
        ),
    ]
