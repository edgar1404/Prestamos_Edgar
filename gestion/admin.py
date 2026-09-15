import calendar
import datetime
import urllib.parse

from django.contrib import admin, messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .models import (
    Cliente,
    ConfiguracionFinanciera,
    DeduccionSocio,
    HistorialAuditoria,
    Prestamo,
    Socio,
    Transaccion,
)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        'numero_fila',
        'nombre',
        'identificacion',
        'telefono',
        'tope_credito',
        'creado_en',
    )
    # Define explícitamente que el link para abrir el perfil está en la columna 'nombre'
    list_display_links = ('nombre',)
    search_fields = ('nombre', 'identificacion', 'telefono')

    def changelist_view(self, request, extra_context=None):
        # Reiniciar el contador en cada carga de la vista
        self._contador_fila = 0
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description='#')
    def numero_fila(self, obj):
        # Incrementa secuencialmente por cada fila renderizada
        if not hasattr(self, '_contador_fila'):
            self._contador_fila = 0
        self._contador_fila += 1
        return self._contador_fila


class EstadoMoraFilter(admin.SimpleListFilter):
    title = 'Estado de Mora'
    parameter_name = 'en_mora'

    def lookups(self, request, model_admin):
        return (
            ('si', 'En Mora'),
            ('no', 'Al Día'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'si':
            ids_morosos = [p.id for p in queryset if getattr(p, 'en_mora', False)]
            return queryset.filter(id__in=ids_morosos)

        if self.value() == 'no':
            ids_al_dia = [p.id for p in queryset if not getattr(p, 'en_mora', False)]
            return queryset.filter(id__in=ids_al_dia)

        return queryset


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = (
        'codigo_tramite',
        'cliente',
        'monto_prestado_format',
        'saldo_actual_format',
        'porcentaje_interes_format',
        'interes_pendiente_format',
        'mostrar_en_mora',
        'mostrar_activo',
        'fecha_inicio',
    )
    list_filter = (EstadoMoraFilter, 'activo', 'porcentaje_interes')
    search_fields = ('codigo_tramite', 'cliente__nombre', 'cliente__identificacion')
    readonly_fields = ('codigo_tramite', 'saldo_actual')
    actions = ['ejecutar_refinanciamiento_action']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('cliente')

    @admin.display(description='Monto Prestado')
    def monto_prestado_format(self, obj):
        return f"${obj.monto_prestado:,.2f}"

    @admin.display(description='Saldo Actual')
    def saldo_actual_format(self, obj):
        return f"${obj.saldo_actual:,.2f}"

    @admin.display(description='Interés (%)')
    def porcentaje_interes_format(self, obj):
        return f"{obj.porcentaje_interes}%"

    @admin.display(description='Interés Pendiente')
    def interes_pendiente_format(self, obj):
        monto = obj.interes_atrasado_acumulado
        if monto > 0:
            monto_str = f"${monto:,.2f}"
            return format_html('<span style="color: #e11d48; font-weight: bold;">{}</span>', monto_str)
        return format_html('<span style="color: #10b981;">$0.00</span>')

    @admin.display(description='¿En Mora?')
    def mostrar_en_mora(self, obj):
        en_mora = getattr(obj, 'en_mora', False)
        if callable(en_mora):
            en_mora = en_mora()

        if en_mora:
            return format_html('<span style="color: #dc2626; font-weight: bold;">{}</span>', 'Sí')
        return format_html('<span style="color: #16a34a; font-weight: bold;">{}</span>', 'No')

    @admin.display(description='Activo')
    def mostrar_activo(self, obj):
        if obj.activo:
            return format_html('<span style="color: #16a34a; font-weight: bold;">{}</span>', 'Sí')
        return format_html('<span style="color: #dc2626; font-weight: bold;">{}</span>', 'No')

    @admin.action(description="🔄 Aplicar Refinanciamiento (Consolidar interés y actualizar cartera)")
    def ejecutar_refinanciamiento_action(self, request, queryset):
        procesados = 0
        for prestamo in queryset:
            if prestamo.activo:
                trans = prestamo.aplicar_refinanciamiento(nuevo_monto_adicional=0)
                procesados += 1
                interes_str = f"${trans.interes_atrasado:,.2f}"
                saldo_str = f"${prestamo.saldo_actual:,.2f}"
                self.message_user(
                    request,
                    f"Préstamo {prestamo.codigo_tramite} refinanciado: "
                    f"Interés consolidado {interes_str} | "
                    f"Nuevo Saldo en Cartera: {saldo_str}",
                    messages.SUCCESS
                )
            else:
                self.message_user(
                    request,
                    f"El préstamo {prestamo.codigo_tramite} está inactivo y no se pudo refinanciar.",
                    messages.WARNING
                )


@admin.register(Transaccion)
class TransaccionAdmin(admin.ModelAdmin):
    list_display = (
        'prestamo',
        'tipo',
        'monto',
        'interes_mora_cobrado',
        'monto_abonado_capital',
        'interes_atrasado',
        'fecha',
        'boton_ver_ticket',
    )
    list_filter = ('tipo', 'fecha')

    readonly_fields = (
        'mora_pendiente_prestamo',
        'interes_mora_cobrado',
        'monto_abonado_capital',
        'interes_atrasado',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('prestamo', 'prestamo__cliente')

    def get_fields(self, request, obj=None):
        if obj is None:
            return (
                'prestamo',
                'mora_pendiente_prestamo',
                'tipo',
                'monto',
                'fecha',
            )
        return (
            'prestamo',
            'mora_pendiente_prestamo',
            'tipo',
            'monto',
            'interes_mora_cobrado',
            'monto_abonado_capital',
            'interes_atrasado',
            'fecha',
        )

    def mora_pendiente_prestamo(self, obj):
        mora_inicial = '$0.00'
        interes_inicial = '$0.00'

        if obj and obj.pk and obj.prestamo:
            val_mora = getattr(obj.prestamo, 'interes_atrasado_acumulado', 0)
            mora_inicial = f'${val_mora:.2f}'

            tasa = float(getattr(obj.prestamo, 'porcentaje_interes', 0)) / 100.0
            saldo = float(getattr(obj.prestamo, 'saldo_actual', 0))
            val_interes = saldo * tasa
            interes_inicial = f'${val_interes:.2f}'

        html_content = f'''
        <div id="mora-container-wrapper" style="display: flex; gap: 25px; align-items: center;">
            <div>
                <small style="color: #555; display: block; font-weight: 600;">Interés Corriente Est.:</small>
                <span id="interes-dinamico-val" style="font-weight: 700; color: #2563eb; font-size: 1.15em;">
                    {interes_inicial}
                </span>
            </div>
            <div>
                <small style="color: #555; display: block; font-weight: 600;">Mora Atrasada:</small>
                <span id="mora-dinamica-val" style="font-weight: 700; color: #dc2626; font-size: 1.15em;">
                    {mora_inicial}
                </span>
            </div>
        </div>
        <script>
            (function() {{
                function limpiarContenedorGris() {{
                    const wrapper = document.querySelector('#mora-container-wrapper');
                    if (wrapper) {{
                        const formRow = wrapper.closest('.form-row, .field-mora_pendiente_prestamo');
                        if (formRow) {{
                            const readonlyBox = formRow.querySelector('.readonly');
                            if (readonlyBox) {{
                                readonlyBox.style.background = 'transparent';
                                readonlyBox.style.border = 'none';
                                readonlyBox.style.padding = '4px 0';
                                readonlyBox.style.boxShadow = 'none';
                            }}
                        }}
                    }}
                }}

                function consultarMora(prestamoId) {{
                    const spanMora = document.querySelector('#mora-dinamica-val');
                    const spanInteres = document.querySelector('#interes-dinamico-val');
                    if (!spanMora || !spanInteres) return;
                    
                    if (!prestamoId) {{
                        spanMora.innerText = '$0.00';
                        spanInteres.innerText = '$0.00';
                        return;
                    }}
                    spanMora.innerText = '...';
                    spanInteres.innerText = '...';
                    
                    fetch('/gestion/api/prestamo/' + prestamoId + '/mora/')
                        .then(res => res.json())
                        .then(data => {{
                            if (data.status === 'ok') {{
                                spanMora.innerText = data.mora || '$0.00';
                                spanInteres.innerText = data.interes_corriente || '$0.00';
                            }} else {{
                                spanMora.innerText = '$0.00';
                                spanInteres.innerText = '$0.00';
                            }}
                        }})
                        .catch(() => {{
                            spanMora.innerText = 'Error';
                            spanInteres.innerText = 'Error';
                        }});
                }}

                function iniciar() {{
                    limpiarContenedorGris();
                    const $ = window.jQuery || window.django.jQuery;
                    const select = $('#id_prestamo');

                    if ($ && select.length) {{
                        select.on('change select2:select', function() {{
                            consultarMora($(this).val());
                        }});
                        if (select.val()) consultarMora(select.val());
                    }} else {{
                        const nativeSelect = document.querySelector('#id_prestamo');
                        if (nativeSelect) {{
                            nativeSelect.addEventListener('change', function() {{
                                consultarMora(this.value);
                            }});
                            if (nativeSelect.value) consultarMora(nativeSelect.value);
                        }}
                    }}
                }}

                if (document.readyState === 'complete' || document.readyState === 'interactive') {{
                    setTimeout(iniciar, 200);
                }} else {{
                    document.addEventListener('DOMContentLoaded', function() {{
                        setTimeout(iniciar, 200);
                    }});
                }}
            }})();
        </script>
        '''
        return mark_safe(html_content)

    mora_pendiente_prestamo.short_description = 'Información de Intereses'

    def interes_mora_cobrado(self, obj):
        if obj and obj.pk and obj.tipo == 'PAGO_CUOTA':
            interes_pagado = obj.monto - obj.monto_abonado_capital
            return f'${interes_pagado:.2f}'
        return '$0.00'

    interes_mora_cobrado.short_description = 'Interés/Mora Cobrado'

    def boton_ver_ticket(self, obj):
        if obj and obj.pk and obj.tipo == 'PAGO_CUOTA':
            url = f'/admin/gestion/transaccion/{obj.id}/ver-ticket/'
            return format_html(
                '''
                <button type="button" class="button" style="background-color: #17a2b8; color: white; padding: 5px 10px; border-radius: 5px; border: none; font-weight: bold; cursor: pointer;" onclick="abrirTicketModal('{}')">📄 Ver Ticket</button>
                <script>
                    if (!document.getElementById('modalTicketOverlay')) {{
                        let modalHTML = `
                            <div id="modalTicketOverlay" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:9999; justify-content:center; align-items:center;">
                                <div style="background:white; border-radius:10px; padding:0; position:relative; width:360px; max-width:90%; box-shadow:0 10px 25px rgba(0,0,0,0.3); overflow:hidden;">
                                    <button onclick="cerrarTicketModal()" style="position:absolute; top:10px; right:10px; background:#d32f2f; color:white; border:none; border-radius:50%; width:28px; height:28px; font-weight:bold; cursor:pointer; z-index:1000;">✕</button>
                                    <iframe id="iframeTicket" src="" style="width:100%; height:480px; border:none;"></iframe>
                                </div>
                            </div>
                        `;
                        document.body.insertAdjacentHTML('beforeend', modalHTML);
                    }}
                    function abrirTicketModal(url) {{
                        document.getElementById('iframeTicket').src = url;
                        document.getElementById('modalTicketOverlay').style.display = 'flex';
                    }}
                    function cerrarTicketModal() {{
                        document.getElementById('modalTicketOverlay').style.display = 'none';
                        document.getElementById('iframeTicket').src = '';
                    }}
                </script>
                ''',
                url,
            )
        return '-'

    boton_ver_ticket.short_description = 'Ticket'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/ver-ticket/',
                self.admin_site.admin_view(self.ver_ticket_view),
                name='ver_ticket_transaccion',
            ),
        ]
        return custom_urls + urls

    @xframe_options_sameorigin
    def ver_ticket_view(self, request, object_id, *args, **kwargs):
        transaccion = self.get_object(request, object_id)
        if transaccion is None:
            raise Http404('Transacción no encontrada')

        cliente_nombre = transaccion.prestamo.cliente.nombre
        codigo = transaccion.prestamo.codigo_tramite
        saldo_anterior = (
            transaccion.prestamo.saldo_actual + transaccion.monto_abonado_capital
        )
        interes_pagado = transaccion.monto - transaccion.monto_abonado_capital
        mora_pendiente = transaccion.interes_atrasado

        tasa_decimal = float(transaccion.prestamo.porcentaje_interes) / 100.0
        proximo_interes = float(transaccion.prestamo.saldo_actual) * tasa_decimal

        fecha_pago = transaccion.fecha
        proximo_mes = fecha_pago.month
        proximo_anio = fecha_pago.year

        if fecha_pago.day < 12:
            proximo_dia = 15
        else:
            proximo_dia = 30
            dias_en_mes = calendar.monthrange(proximo_anio, proximo_mes)[1]
            if proximo_dia > dias_en_mes:
                proximo_dia = dias_en_mes

        proxima_fecha_pago = datetime.date(proximo_anio, proximo_mes, proximo_dia).strftime('%d/%m/%Y')

        mensaje = transaccion.generar_ticket_whatsapp()
        mensaje_url = urllib.parse.quote(mensaje)
        telefono = transaccion.prestamo.cliente.telefono or ''
        telefono_limpio = ''.join(filter(str.isdigit, telefono))

        url_whatsapp = (
            f'https://wa.me/{telefono_limpio}?text={mensaje_url}'
            if telefono_limpio
            else f'https://wa.me/?text={mensaje_url}'
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #ffffff;
                    padding: 10px;
                }}
                .ticket-card {{
                    width: 280px;
                    margin: 0 auto;
                    background: white;
                    border: 1px solid #ccc;
                    border-radius: 6px;
                    overflow: hidden;
                    padding-bottom: 5px;
                }}
                .header {{
                    background-color: #075E54;
                    color: white;
                    text-align: center;
                    padding: 10px;
                    font-size: 14px;
                    font-weight: bold;
                }}
                .content {{
                    padding: 10px;
                    font-size: 12px;
                    color: #333;
                }}
                .line {{
                    border-bottom: 1px dashed #ccc;
                    margin: 6px 0;
                }}
                .fila {{
                    width: 100%;
                    clear: both;
                    padding: 2px 0;
                    display: block;
                    overflow: hidden;
                }}
                .col-izq {{ float: left; width: 55%; text-align: left; }}
                .col-der {{ float: right; width: 45%; text-align: right; }}
                .bold {{ font-weight: bold; }}
                .highlight {{ color: #d32f2f; font-weight: bold; }}
                .next-pay {{ color: #075E54; font-weight: bold; }}
                .footer {{
                    text-align: center;
                    padding: 8px;
                    font-size: 11px;
                    color: #666;
                }}
                .actions {{
                    display: flex;
                    gap: 8px;
                    margin-top: 10px;
                }}
                .btn {{
                    flex: 1;
                    padding: 8px;
                    border: none;
                    border-radius: 5px;
                    text-align: center;
                    text-decoration: none;
                    font-weight: bold;
                    font-size: 11px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }}
                .btn-ws {{ background-color: #25D366; color: white; }}
                .btn-print {{ background-color: #007bff; color: white; }}

                @page {{ size: auto; margin: 0; }}
                @media print {{
                    body {{ padding: 0; margin: 0; background: white; }}
                    .ticket-card {{ border: none; width: 100%; max-width: 100%; }}
                    .actions {{ display: none !important; }}
                    .col-izq {{ float: left !important; width: 55% !important; }}
                    .col-der {{ float: right !important; width: 45% !important; }}
                }}
            </style>
        </head>
        <body>
            <div class="ticket-card" id="ticketToCapture">
                <div class="header">COMPROBANTE DE PAGO</div>
                <div class="content">
                    <div class="fila"><span class="col-izq bold">Cliente:</span><span class="col-der">{cliente_nombre}</span></div>
                    <div class="fila"><span class="col-izq bold">Trámite:</span><span class="col-der">{codigo}</span></div>
                    <div class="fila"><span class="col-izq bold">Fecha:</span><span class="col-der">{transaccion.fecha.strftime('%d/%m/%Y')}</span></div>
                    
                    <div class="line"></div>
                    
                    <div class="fila"><span class="col-izq">Monto Recibido:</span><span class="col-der bold">${transaccion.monto:.2f}</span></div>
                    <div class="fila"><span class="col-izq">Abono a Capital:</span><span class="col-der">${transaccion.monto_abonado_capital:.2f}</span></div>
                    <div class="fila"><span class="col-izq">Interés / Mora:</span><span class="col-der">${interes_pagado:.2f}</span></div>
                    <div class="fila highlight"><span class="col-izq">Mora Pendiente:</span><span class="col-der">${mora_pendiente:.2f}</span></div>
                    
                    <div class="line"></div>
                    
                    <div class="fila"><span class="col-izq">Saldo Anterior:</span><span class="col-der">${saldo_anterior:.2f}</span></div>
                    <div class="fila highlight"><span class="col-izq">Saldo Actual:</span><span class="col-der">${transaccion.prestamo.saldo_actual:.2f}</span></div>
                    
                    <div class="line"></div>

                    <div class="fila next-pay"><span class="col-izq">Próximo Interés:</span><span class="col-der">${proximo_interes:.2f}</span></div>
                    <div class="fila next-pay"><span class="col-izq">Próximo Pago:</span><span class="col-der">{proxima_fecha_pago}</span></div>
                </div>
                <div class="footer">¡Gracias por su puntualidad!</div>
            </div>

            <div class="actions">
                <button onclick="copiarImagenYWhatsApp()" class="btn btn-ws">📲 Copiar Imagen y Abrir WS</button>
                <button onclick="window.print()" class="btn btn-print">🖨️ Imprimir</button>
            </div>

            <script>
            async function copiarImagenYWhatsApp() {{
                const element = document.getElementById('ticketToCapture');
                try {{
                    const canvas = await html2canvas(element, {{ scale: 2 }});
                    
                    if (navigator.share && navigator.canShare) {{
                        canvas.toBlob(async (blob) => {{
                            const file = new File([blob], 'ticket.png', {{ type: 'image/png' }});
                            if (navigator.canShare({{ files: [file] }})) {{
                                await navigator.share({{
                                    files: [file],
                                    title: 'Comprobante de Pago',
                                    text: 'Hola {cliente_nombre}, adjunto tu comprobante de pago.'
                                }});
                                return;
                            }}
                        }});
                    }}

                    canvas.toBlob(async (blob) => {{
                        try {{
                            const item = new ClipboardItem({{ 'image/png': blob }});
                            await navigator.clipboard.write([item]);
                            alert('¡Imagen copiada al portapapeles! Presiona Ctrl + V en el chat de WhatsApp para enviarla.');
                        }} catch (err) {{
                            console.error('Error al copiar imagen: ', err);
                        }}
                        window.open('{url_whatsapp}', '_blank');
                    }});
                }} catch (e) {{
                    console.error(e);
                    window.open('{url_whatsapp}', '_blank');
                }}
            }}
            </script>
        </body>
        </html>
        """
        return HttpResponse(html_content)


@admin.register(ConfiguracionFinanciera)
class ConfiguracionFinancieraAdmin(admin.ModelAdmin):
    list_display = ('capital_base',)
    readonly_fields = ('capital_base_field',)
    fields = ('capital_base_field',)

    def capital_base_field(self, obj):
        val = obj.capital_base if obj else "200.00"
        return format_html(
            '''
            <div class="input-group" style="max-width: 380px;">
                <input type="number" step="0.01" name="capital_base" id="id_capital_base" 
                       class="form-control" value="{}" readonly style="background-color: #e9ecef; font-weight: bold;">
                <div class="input-group-append">
                    <button type="button" class="btn btn-outline-primary btn-toggle-edit" data-target="id_capital_base">
                        <i class="fas fa-pencil-alt mr-1"></i> Editar
                    </button>
                </div>
            </div>
            <small class="form-text text-muted">Monto total del fondo asignado para préstamos.</small>
            ''',
            val
        )
    capital_base_field.short_description = "Capital Base Inicial"

    def has_add_permission(self, request):
        if ConfiguracionFinanciera.objects.exists():
            return False
        return super().has_add_permission(request)

    def changelist_view(self, request, extra_context=None):
        config = ConfiguracionFinanciera.objects.first()
        if not config:
            config = ConfiguracionFinanciera.objects.create(capital_base=200.00)
        return redirect(f'/admin/gestion/configuracionfinanciera/{config.id}/change/')

    class Media:
        js = ('admin/js/config_inline_edit.js',)


@admin.register(HistorialAuditoria)
class HistorialAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'usuario_formateado', 'accion_badge', 'tabla', 'descripcion')
    list_filter = ('accion', 'tabla', 'fecha_hora')
    search_fields = ('descripcion', 'usuario__username', 'tabla')
    readonly_fields = ('usuario', 'tabla', 'accion', 'descripcion', 'fecha_hora')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Usuario')
    def usuario_formateado(self, obj):
        if obj.usuario:
            return mark_safe(f'<strong>{obj.usuario.username}</strong>')
        return mark_safe('<em>Sistema</em>')

    @admin.display(description='Acción')
    def accion_badge(self, obj):
        colores = {
            'CREACION': '#28a745',
            'EDICION': '#ffc107',
            'ELIMINACION': '#dc3545',
        }
        color = colores.get(obj.accion, '#6c757d')
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{}</span>',
            color,
            obj.get_accion_display()
        )


class DeduccionSocioInline(admin.TabularInline):
    model = DeduccionSocio
    extra = 1


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 
        'capital_invertido_format', 
        'porcentaje_retorno_format', 
        'retorno_bruto_format', 
        'comision_gestion_format', 
        'total_deducciones_format', 
        'pago_neto_format',
        'mostrar_activo',
        'acciones_pdf',
    )
    inlines = [DeduccionSocioInline]

    @admin.display(description='Capital')
    def capital_invertido_format(self, obj):
        return f"${obj.capital_invertido:,.2f}"

    @admin.display(description='Retorno %')
    def porcentaje_retorno_format(self, obj):
        return f"{obj.porcentaje_retorno}%"

    @admin.display(description='Retorno Bruto')
    def retorno_bruto_format(self, obj):
        return f"${obj.retorno_bruto:,.2f}"

    @admin.display(description='Gestión Cobrador')
    def comision_gestion_format(self, obj):
        return f"${obj.comision_gestion:,.2f}"

    @admin.display(description='Total Deducciones')
    def total_deducciones_format(self, obj):
        return f"${obj.total_deducciones:,.2f}"

    @admin.display(description='Neto a Pagar')
    def pago_neto_format(self, obj):
        monto_str = f"${obj.pago_neto_quincenal:,.2f}"
        return format_html(
            '<span style="background-color: #dcfce7; color: #15803d; font-weight: bold; padding: 4px 10px; border-radius: 6px; display: inline-block;">{}</span>', 
            monto_str
        )

    @admin.display(description='Activo')
    def mostrar_activo(self, obj):
        texto = "Sí" if obj.activo else "No"
        color = "#16a34a" if obj.activo else "#dc2626"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            texto
        )

    @admin.display(description='Recibo')
    def acciones_pdf(self, obj):
        return format_html(
            '<a class="button" href="/socio/{}/pdf/" target="_blank" style="background-color: #0284c7; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; text-decoration: none;">PDF</a>',
            obj.id
        )




from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

# Desregistrar la vista predeterminada de User
admin.site.unregister(User)

# Registrar User con el CSS personalizado
@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    class Media:
        css = {
            'all': ('admin/css/admin_custom.css',)
        }