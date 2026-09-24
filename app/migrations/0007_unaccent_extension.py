from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0006_alter_notification_end_at'),
    ]

    operations = [
        UnaccentExtension(),
    ]
