from django.urls import path
from app.views import contacts_view

app_name = 'app'

urlpatterns = [
    path('contacts/', contacts_view, name='contacts'),
]
