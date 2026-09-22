from django.urls import path
from django.views.generic import RedirectView
from app.views import (
    home_view, contacts_view, dashboards_view, dashboard_view, favorite_dashboard,
    login_view, logout_view, customers_vendors_api, toners_view, toners_api, toner_api,
    toner_movements_api,
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

    # API
    path('api/customers-vendors/', customers_vendors_api, name='customers-vendors-api'),
    path('api/toners/', toners_api, name='toners-api'),
    path('api/toners/<int:toner_id>/', toner_api, name='toner-api'),
    path('api/toners/<int:toner_id>/movements/', toner_movements_api, name='toner-movements-api'),

    # Redirects
    path('ramais/', RedirectView.as_view(pattern_name='app:contacts', permanent=True)),
    path('indicadores/', RedirectView.as_view(pattern_name='app:dashboards', permanent=True)),
]
