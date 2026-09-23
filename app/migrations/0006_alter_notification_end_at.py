from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0005_notification'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='end_at',
            field=models.DateTimeField(blank=True, help_text='Depois desta data a notificação sai do mural e deixa de aparecer como alerta. Deixe em branco para mantê-la no mural.', null=True, verbose_name='Exibir até'),
        ),
    ]
