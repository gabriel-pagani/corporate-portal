from django.urls import path
from app.views import (
    home_view, contacts_view, dashboards_view, dashboard_view, favorite_dashboard,
    login_view, login_done, logout_view,
)

app_name = 'app'

urlpatterns = [
    path('', home_view, name='home'),
    path('login/', login_view, name='login'),
    path('login/done', login_done, name='login-done'),
    path('logout/', logout_view, name='logout'),
    path('contacts/', contacts_view, name='contacts'),
    path('dashboards/', dashboards_view, name='dashboards'),
    path('dashboard/<int:dashboard_id>/', dashboard_view, name='dashboard'),
    path('dashboard/<int:dashboard_id>/favorite/', favorite_dashboard, name='favorite-dashboard'),
]
