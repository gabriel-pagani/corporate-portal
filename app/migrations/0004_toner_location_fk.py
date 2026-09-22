import django.db.models.deletion
from django.db import migrations, models


LOCATIONS = [
    'Brother',
    'Central',
    'Diretoria',
    'Lic/Rec/Obr',
    'Obras',
    'Parking',
    'Placas/Metalúrgica',
]


def text_to_location(apps, schema_editor):
    Toner = apps.get_model('app', 'Toner')
    TonerLocation = apps.get_model('app', 'TonerLocation')

    TonerLocation.objects.bulk_create(
        [TonerLocation(name=name) for name in LOCATIONS], ignore_conflicts=True,
    )
    by_name = {location.name.casefold(): location for location in TonerLocation.objects.all()}

    for toner in Toner.objects.exclude(old_location='').iterator():
        text = toner.old_location.strip()
        location = by_name.get(text.casefold())
        if location is None:
            # Qualquer local fora da lista é preservado como está para nada se perder
            location = TonerLocation.objects.create(name=text)
            by_name[text.casefold()] = location

        toner.location = location
        toner.save(update_fields=['location'])


def location_to_text(apps, schema_editor):
    Toner = apps.get_model('app', 'Toner')

    for toner in Toner.objects.exclude(location=None).select_related('location').iterator():
        toner.old_location = toner.location.name
        toner.save(update_fields=['old_location'])


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_unique_toner_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='TonerLocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Impressora / Setor')),
            ],
            options={
                'verbose_name': 'Local de Toner',
                'verbose_name_plural': 'Locais de Toner',
                'ordering': ['name'],
            },
        ),
        migrations.RenameField(
            model_name='toner',
            old_name='location',
            new_name='old_location',
        ),
        migrations.AddField(
            model_name='toner',
            name='location',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='app.tonerlocation',
                verbose_name='Impressora / Setor',
            ),
        ),
        migrations.RunPython(text_to_location, location_to_text),
        migrations.RemoveField(
            model_name='toner',
            name='old_location',
        ),
        migrations.AlterModelOptions(
            name='toner',
            options={
                'ordering': ['location__name', 'name'],
                'verbose_name': 'Toner',
                'verbose_name_plural': 'Toners',
            },
        ),
    ]
