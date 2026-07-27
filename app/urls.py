from django.urls import path
from app.views import contacts_view, dashboards_view, dashboard_view, favorite_dashboard

app_name = 'app'

urlpatterns = [
    path('contacts/', contacts_view, name='contacts'),
    path('dashboards/', dashboards_view, name='dashboards'),
    path('dashboard/<int:dashboard_id>/', dashboard_view, name='dashboard'),
    path('dashboard/<int:dashboard_id>/favorite/', favorite_dashboard, name='favorite-dashboard'),
]
