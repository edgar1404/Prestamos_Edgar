import calendar
import datetime
import urllib.parse
from datetime import timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Case, DecimalField, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.timezone import now

from .models import ConfiguracionFinanciera, Prestamo, Socio, Transaccion


@staff_member_required
def dashboard_admin(request):
    """
    Dashboard de Administración con separación estricta de interés y capital.
    """
    hoy = now().date()

    # 1. Cartera Activa: Saldo total acumulado prestado
    cartera_activa = Prestamo.objects.filter(activo=True, saldo_actual__gt=0).aggregate(
        total=Sum('saldo_actual')
    )['total'] or Decimal('0.00')

    # 2. Cobros del Día: Suma directa de recaudación real
    transacciones_hoy = Transaccion.objects.filter(fecha=hoy)

    cobros_dia = transacciones_hoy.aggregate(
        total=Coalesce(
            Sum(
                Case(
                    # Refinanciamiento: extrae únicamente la ganancia de interés
                    When(tipo='REFINANCIAMIENTO', then=Coalesce(F('interes_atrasado'), Decimal('0.00'))),
                    # Pagos de cuotas ordinarias: suma el monto cobrado
                    default=F('monto'),
                    output_field=DecimalField()
                )
            ),
            Decimal('0.00')
        )
    )['total']

    cant_transacciones_hoy = transacciones_hoy.count()

    # 3. Créditos en Mora
    prestamos_activos = Prestamo.objects.filter(activo=True, saldo_actual__gt=0)
    prestamos_mora = sum(1 for p in prestamos_activos if p.en_mora)

    # 4. Logs de Auditoría
    log_entries = LogEntry.objects.select_related('content_type', 'user')

    context = {
        'cartera_activa': round(float(cartera_activa), 2),
        'cobros_dia': round(float(cobros_dia), 2),
        'transacciones_hoy': cant_transacciones_hoy,
        'prestamos_mora': prestamos_mora,
        'log_entries': log_entries,
        'title': 'Panel de control',
        'available_apps': admin.site.get_app_list(request),
    }

    return render(request, 'admin/index.html', context)


@staff_member_required
def cartera_activa_view(request):
    """
    Vista detallada del Panel de Cartera Activa con métricas y segmentación.
    """
    hoy = now().date()
    estado_filtro = request.GET.get('estado', 'todos')

    # Base de préstamos
    todos_prestamos = Prestamo.objects.select_related('cliente').prefetch_related('transacciones')
    prestamos_activos = todos_prestamos.filter(activo=True, saldo_actual__gt=0)

    # 1. MÉTRICAS SUPERIORES
    capital_colocado = prestamos_activos.aggregate(
        total=Sum('saldo_actual')
    )['total'] or Decimal('0.00')

    prestamos_riesgo_ids = [p.id for p in prestamos_activos if p.en_riesgo_critico]
    capital_en_riesgo = prestamos_activos.filter(id__in=prestamos_riesgo_ids).aggregate(
        total=Sum('saldo_actual')
    )['total'] or Decimal('0.00')

    proyeccion_interes = sum(
        (p.saldo_actual * (p.porcentaje_interes / Decimal('100.00')) * Decimal('2'))
        for p in prestamos_activos
    )

    tasa_promedio = prestamos_activos.aggregate(
        promedio=Avg('porcentaje_interes')
    )['promedio'] or Decimal('0.00')

    # 2. FILTRADO POR PESTAÑAS (SEGMENTACIÓN)
    if estado_filtro == 'al_dia':
        lista_prestamos = [p for p in prestamos_activos if not p.en_mora and p.dias_sin_pagar <= 30]
    elif estado_filtro == 'pre_mora':
        lista_prestamos = [p for p in prestamos_activos if p.dias_sin_pagar <= 30 and p.en_mora]
    elif estado_filtro == 'riesgo':
        lista_prestamos = [p for p in prestamos_activos if p.en_riesgo_critico]
    elif estado_filtro == 'refinanciados':
        lista_prestamos = prestamos_activos.filter(transacciones__tipo='REFINANCIAMIENTO').distinct()
    elif estado_filtro == 'liquidados':
        lista_prestamos = todos_prestamos.filter(activo=False, saldo_actual=0)
    else:
        lista_prestamos = prestamos_activos

    context = {
        'title': 'Gestión de Cartera Activa',
        'prestamos': lista_prestamos,
        'estado_filtro': estado_filtro,
        'capital_colocado': round(float(capital_colocado), 2),
        'capital_en_riesgo': round(float(capital_en_riesgo), 2),
        'proyeccion_interes': round(float(proyeccion_interes), 2),
        'tasa_promedio': round(float(tasa_promedio), 2),
        'cant_todos': prestamos_activos.count(),
        'cant_al_dia': sum(1 for p in prestamos_activos if not p.en_mora and p.dias_sin_pagar <= 30),
        'cant_pre_mora': sum(1 for p in prestamos_activos if p.dias_sin_pagar <= 30 and p.en_mora),
        'cant_riesgo': len(prestamos_riesgo_ids),
        'cant_refinanciados': prestamos_activos.filter(transacciones__tipo='REFINANCIAMIENTO').distinct().count(),
        'available_apps': admin.site.get_app_list(request) if hasattr(admin.site, 'get_app_list') else [],
    }

    return render(request, 'admin/cartera_activa.html', context)


def obtener_mora_prestamo(request, prestamo_id):
    """
    API endpoint para obtener el interés corriente estimado y la mora atrasada vía AJAX.
    """
    try:
        prestamo = get_object_or_404(Prestamo, id=prestamo_id)

        # 1. Cálculo de mora/interés atrasado
        mora_val = Decimal(getattr(prestamo, 'interes_atrasado_acumulado', Decimal('0.00'))) if prestamo.en_mora else Decimal('0.00')

        # 2. Cálculo del interés corriente del período actual (Saldo * Tasa %)
        saldo = Decimal(str(getattr(prestamo, 'saldo_actual', '0.00')))
        tasa = Decimal(str(getattr(prestamo, 'porcentaje_interes', '0.00'))) / Decimal('100.00')
        interes_corriente_val = saldo * tasa

        total_pendiente = mora_val + interes_corriente_val

        return JsonResponse({
            'status': 'ok',
            'mora': f'${mora_val:,.2f}',
            'interes_corriente': f'${interes_corriente_val:,.2f}',
            'total_pendiente': f'${total_pendiente:,.2f}'
        })
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'mora': '$0.00', 'interes_corriente': '$0.00', 'detalle': str(e)}, 
            status=400
        )


@login_required
def reporte_utilidades(request):
    """
    Vista del reporte detallado de utilidades.
    """
    config = ConfiguracionFinanciera.objects.first()
    CAPITAL_BASE_INICIAL = Decimal(str(config.capital_base)) if config else Decimal('200.00')

    prestamos_activos = Prestamo.objects.filter(activo=True, saldo_actual__gt=0)
    capital_en_calle = prestamos_activos.aggregate(
        total=Sum('saldo_actual')
    )['total'] or Decimal('0.00')

    # Filtrar únicamente pagos de cuotas para calcular lo cobrado en caja
    pagos_cuotas = Transaccion.objects.filter(tipo='PAGO_CUOTA')

    capital_retornado = pagos_cuotas.aggregate(
        total=Sum('monto_abonado_capital')
    )['total'] or Decimal('0.00')

    total_cobrado_efectivo = pagos_cuotas.aggregate(
        total=Sum('monto')
    )['total'] or Decimal('0.00')

    # Utilidad real cobrada = (Monto total recibido en pagos de cuotas) - (Abonos reales a capital)
    # Esto incluye automáticamente tanto el interés corriente como el interés por mora/atraso cobrado.
    utilidad_real_cobrada = total_cobrado_efectivo - capital_retornado

    # Capital disponible actual en caja (Sin incluir las utilidades cobradas)
    capital_disponible = CAPITAL_BASE_INICIAL - capital_en_calle

    prestamos_con_interes = prestamos_activos.filter(porcentaje_interes__gt=0)
    utilidad_quincenal_esperada = sum(
        (p.saldo_actual * (p.porcentaje_interes / Decimal('100.00')))
        for p in prestamos_con_interes
    )
    utilidad_mensual_esperada = utilidad_quincenal_esperada * Decimal('2.0')

    context = {
        'available_apps': admin.site.get_app_list(request),
        'capital_base_inicial': round(float(CAPITAL_BASE_INICIAL), 2),
        'capital_en_calle': round(float(capital_en_calle), 2),
        'capital_retornado': round(float(capital_retornado), 2),
        'capital_disponible': round(float(capital_disponible), 2),
        'utilidad_real_cobrada': round(float(utilidad_real_cobrada), 2),
        'utilidad_quincenal_esperada': round(float(utilidad_quincenal_esperada), 2),
        'utilidad_mensual_esperada': round(float(utilidad_mensual_esperada), 2),
        'total_prestamos_activos': prestamos_activos.count(),
    }

    return render(request, 'utilidades.html', context)


@staff_member_required
def exportar_cartera_pdf(request):
    """
    Vista de impresión/exportación para el reporte de cartera.
    """
    estado_filtro = request.GET.get('estado', 'todos')
    todos_prestamos = Prestamo.objects.select_related('cliente').prefetch_related('transacciones')
    prestamos_activos = todos_prestamos.filter(activo=True, saldo_actual__gt=0)

    if estado_filtro == 'al_dia':
        lista_prestamos = [p for p in prestamos_activos if not p.en_mora and p.dias_sin_pagar <= 30]
    elif estado_filtro == 'pre_mora':
        lista_prestamos = [p for p in prestamos_activos if p.dias_sin_pagar <= 30 and p.en_mora]
    elif estado_filtro == 'riesgo':
        lista_prestamos = [p for p in prestamos_activos if p.en_riesgo_critico]
    elif estado_filtro == 'refinanciados':
        lista_prestamos = prestamos_activos.filter(transacciones__tipo='REFINANCIAMIENTO').distinct()
    else:
        lista_prestamos = prestamos_activos

    total_cartera = sum(p.saldo_actual for p in lista_prestamos)

    context = {
        'prestamos': lista_prestamos,
        'estado_filtro': estado_filtro,
        'total_cartera': round(float(total_cartera), 2),
        'fecha_generacion': now(),
    }
    return render(request, 'admin/exportar_cartera.html', context)


@staff_member_required
def gestion_socios_view(request):
    """
    Dashboard para la gestión de socios e inversionistas con prefetch de deducciones.
    """
    socios = Socio.objects.filter(activo=True).prefetch_related('deducciones')

    total_capital = socios.aggregate(Sum('capital_invertido'))['capital_invertido__sum'] or Decimal('0.00')
    total_gestion = socios.aggregate(Sum('comision_gestion'))['comision_gestion__sum'] or Decimal('0.00')

    total_bruto = sum(s.retorno_bruto for s in socios)
    total_neto = sum(s.pago_neto_quincenal for s in socios)

    context = {
        'socios': socios,
        'total_capital_invertido': total_capital,
        'total_retorno_bruto': total_bruto,
        'total_gestion': total_gestion,
        'total_pago_neto': total_neto,
    }
    return render(request, 'gestion/socios.html', context)


@staff_member_required
def comprobante_socio_pdf(request, socio_id):
    """
    Genera la plantilla del recibo/comprobante impreso de liquidación para un socio.
    """
    socio = get_object_or_404(Socio, pk=socio_id)
    deducciones_activas = socio.deducciones.filter(activa=True)

    context = {
        'socio': socio,
        'deducciones': deducciones_activas,
    }
    return render(request, 'gestion/comprobante_socio.html', context)