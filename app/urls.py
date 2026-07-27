from django.urls import path
from app.views import employees_view

app_name = 'app'

urlpatterns = [
    path('employees-list/', employees_view, name='employees-list'),
]
