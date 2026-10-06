from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('app', '0007_unaccent_extension')]

    operations = [
        migrations.AlterModelOptions(
            name='user',
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'permissions': [
                    ('register_customers_suppliers', 'Can register customers and suppliers'),
                ],
            },
        ),
    ]
