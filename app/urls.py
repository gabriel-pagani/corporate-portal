from django.urls import path
from django.contrib.auth.views import LogoutView
from app.views import home_view, contacts_view, dashboards_view, dashboard_view, favorite_dashboard

app_name = 'app'

urlpatterns = [
    path('', home_view, name='home'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('contacts/', contacts_view, name='contacts'),
    path('dashboards/', dashboards_view, name='dashboards'),
    path('dashboard/<int:dashboard_id>/', dashboard_view, name='dashboard'),
    path('dashboard/<int:dashboard_id>/favorite/', favorite_dashboard, name='favorite-dashboard'),
]
