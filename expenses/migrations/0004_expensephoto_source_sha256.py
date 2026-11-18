from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0003_discard_untouched_expense'),
    ]

    operations = [
        migrations.AddField(
            model_name='expensephoto',
            name='source_sha256',
            field=models.CharField(
                blank=True, db_index=True, max_length=64, verbose_name='SHA-256 do arquivo enviado',
            ),
        ),
        migrations.AlterField(
            model_name='expensephoto',
            name='sha256',
            field=models.CharField(db_index=True, max_length=64, verbose_name='SHA-256'),
        ),
    ]
