import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0020_remove_expenses'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='sector',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='users', to='app.sector', verbose_name='Setor'),
        ),
    ]
