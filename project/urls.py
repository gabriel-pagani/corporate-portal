from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.views.generic import RedirectView

admin.site.site_header = "Portal de Administração"
admin.site.site_title = "Sistema"
admin.site.index_title = "Painel de Controle"

urlpatterns = [
    path('', include('app.urls', namespace='app')),
    path('', include('journey_audit.urls', namespace='journey_audit')),
    # O painel entra pela tela do portal, que é onde estão o código e o cadastro
    # do aplicativo. O ?next= vai junto, e o login confere antes de seguir.
    path(F'{settings.ADMIN_PANEL_PATH}/login/', RedirectView.as_view(pattern_name='app:login', query_string=True)),
    path(F'{settings.ADMIN_PANEL_PATH}/', admin.site.urls),
]
