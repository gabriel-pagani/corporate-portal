from django.urls import path
from app.views import contacts_view

app_name = 'app'

urlpatterns = [
    path('contacts-list/', contacts_view, name='contacts-list'),
]
