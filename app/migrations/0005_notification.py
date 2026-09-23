import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_toner_location_fk'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150, verbose_name='Título')),
                ('message', models.TextField(verbose_name='Mensagem')),
                ('level', models.CharField(choices=[('I', 'Informação'), ('A', 'Aviso'), ('U', 'Urgente')], default='I', max_length=1, verbose_name='Nível')),
                ('start_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Exibir a partir de')),
                ('end_at', models.DateTimeField(blank=True, help_text='Deixe em branco para exibir até o usuário marcar como lida.', null=True, verbose_name='Exibir até')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('groups', models.ManyToManyField(blank=True, related_name='notifications', to='auth.group', verbose_name='Grupos')),
                ('read_by', models.ManyToManyField(blank=True, related_name='read_notifications', to=settings.AUTH_USER_MODEL, verbose_name='Lida Por')),
                ('users', models.ManyToManyField(blank=True, help_text='Deixe usuários e grupos em branco para enviar a todos.', related_name='notifications', to=settings.AUTH_USER_MODEL, verbose_name='Usuários')),
            ],
            options={
                'verbose_name': 'Notificação',
                'verbose_name_plural': 'Notificações',
                'ordering': ['-start_at'],
            },
        ),
    ]
