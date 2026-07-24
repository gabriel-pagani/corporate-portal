from django.urls import path
from app.views import ramais_view

app_name = 'app'

urlpatterns = [
    path('ramais/', ramais_view, name='ramais'),
]
