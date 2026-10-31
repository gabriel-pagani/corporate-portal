from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('journey_audit', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='occurrence',
            old_name='department',
            new_name='location',
        ),
        migrations.AlterField(
            model_name='occurrence',
            name='location',
            field=models.CharField(max_length=150, verbose_name='Localização'),
        ),
    ]
