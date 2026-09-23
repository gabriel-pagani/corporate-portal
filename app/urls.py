from django.urls import path
from django.views.generic import RedirectView
from app.views import (
    home_view, contacts_view, dashboards_view, dashboard_view, favorite_dashboard,
    login_view, logout_view, customers_vendors_api, toners_view, toners_api, toner_api,
    toner_movements_api, notifications_view, notifications_api, notification_read_api,
    notifications_read_all_api,
)

app_name = 'app'

urlpatterns = [
    path('', home_view, name='home'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('contacts/', contacts_view, name='contacts'),
    path('dashboards/', dashboards_view, name='dashboards'),
    path('dashboard/<int:dashboard_id>/', dashboard_view, name='dashboard'),
    path('dashboard/<int:dashboard_id>/favorite/', favorite_dashboard, name='favorite-dashboard'),
    path('toners/', toners_view, name='toners'),
    path('notifications/', notifications_view, name='notifications'),

    # API
    path('api/customers-vendors/', customers_vendors_api, name='customers-vendors-api'),
    path('api/toners/', toners_api, name='toners-api'),
    path('api/toners/<int:toner_id>/', toner_api, name='toner-api'),
    path('api/toners/<int:toner_id>/movements/', toner_movements_api, name='toner-movements-api'),
    path('api/notifications/', notifications_api, name='notifications-api'),
    path('api/notifications/read-all/', notifications_read_all_api, name='notifications-read-all-api'),
    path('api/notifications/<int:notification_id>/read/', notification_read_api, name='notification-read-api'),

    # Redirects
    path('ramais/', RedirectView.as_view(pattern_name='app:contacts', permanent=True)),
    path('indicadores/', RedirectView.as_view(pattern_name='app:dashboards', permanent=True)),
]
