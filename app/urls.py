from django.urls import path
from app.views import employees_view

app_name = 'app'

urlpatterns = [
    path('ramais/', employees_view, name='ramais'),
]
