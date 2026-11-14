from django.db.models.signals import post_delete
from django.dispatch import receiver

from app.signals import delete_stored_file
from expenses.models import ExpensePhoto


# Apagar a foto no banco não apaga o arquivo por conta própria
@receiver(post_delete, sender=ExpensePhoto)
def delete_photo_file(sender, instance, **kwargs):
    delete_stored_file(instance.file.storage, instance.file.name)
