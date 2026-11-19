from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0023_alter_serviceaccess_service'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='session_version',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
    ]
