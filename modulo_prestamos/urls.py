from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path
from gestion.views import (
    dashboard_admin,
    cartera_activa_view,
    exportar_cartera_pdf,
    reporte_utilidades,
    obtener_mora_prestamo,
)
from django.urls import path
from gestion import views



urlpatterns = [
    # Redirige la raíz '/' al panel de administración
    path('', lambda request: redirect('admin/')),

    # Dashboard personalizado
    path('admin/', dashboard_admin, name='admin_index'),

    # Vista dedicada a Cartera Activa
    path('admin/cartera/', cartera_activa_view, name='cartera_activa'),

    # Exportar / Imprimir Cartera (DEBE IR ANTES DE admin.site.urls)
    path('admin/cartera/exportar/', exportar_cartera_pdf, name='exportar_cartera_pdf'),

    # Panel de control de Django / Jazzmin
    path('admin/', admin.site.urls),

    # Reporte de utilidades
    path('utilidades/', reporte_utilidades, name='reporte_utilidades'),

    # API para calcular mora
    path(
        'gestion/api/prestamo/<int:prestamo_id>/mora/',
        obtener_mora_prestamo,
        name='obtener_mora_prestamo',
    ),
    path('socio/<int:socio_id>/pdf/', views.comprobante_socio_pdf, name='comprobante_socio_pdf'),
]
