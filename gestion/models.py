# -*- coding: utf-8 -*-
import calendar
import datetime
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.timezone import now
from datetime import date, timedelta

class Cliente(models.Model):
    nombre = models.CharField(max_length=150, verbose_name="Nombre Completo")
    identificacion = models.CharField(max_length=50, blank=True, null=True, verbose_name="Cédula / ID")
    telefono = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono / WhatsApp")
    tope_credito = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Límite de Crédito ($)")
    
    cedula_frontal = models.ImageField(upload_to='clientes/cedulas/', null=True, blank=True, verbose_name="Cédula (Parte Frontal)")
    cedula_trasera = models.ImageField(upload_to='clientes/cedulas/', null=True, blank=True, verbose_name="Cédula (Parte Trasera)")
    
    observacion = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'

    def __str__(self):
        return self.nombre


class Prestamo(models.Model):
    TASAS_CHOICES = [
        (Decimal('0.00'), '0% Sin Interés'),
        (Decimal('7.50'), '7.5% Quincenal'),
        (Decimal('10.00'), '10% Quincenal'),
        (Decimal('15.00'), '15% Quincenal'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='prestamos')
    codigo_tramite = models.CharField(max_length=20, blank=True, null=True, editable=False)
    monto_prestado = models.DecimalField(max_digits=10, decimal_places=2)
    saldo_actual = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    porcentaje_interes = models.DecimalField(max_digits=5, decimal_places=2, choices=TASAS_CHOICES, default=Decimal('10.00'))
    fecha_inicio = models.DateField()
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Préstamo'
        verbose_name_plural = 'Préstamos'

    def __str__(self):
        codigo = self.codigo_tramite or 'Sin Código'
        return f"{self.cliente.nombre if hasattr(self.cliente, 'nombre') else self.cliente} - {codigo} (${self.saldo_actual})"

    def save(self, *args, **kwargs):
        if self.saldo_actual is None and self.monto_prestado is not None:
            self.saldo_actual = Decimal(str(self.monto_prestado))

        saldo_num = Decimal(str(self.saldo_actual)) if self.saldo_actual is not None else Decimal('0.00')

        if saldo_num > Decimal('0.00'):
            self.activo = True
        else:
            self.saldo_actual = Decimal('0.00')
            self.activo = False

        super().save(*args, **kwargs)

        if not self.codigo_tramite and self.pk:
            self.codigo_tramite = f'#{self.pk:03d}'
            super().save(update_fields=['codigo_tramite'])

    def obtener_quincenas_pendientes(self, fecha_hasta=None):
        if not self.activo or (self.saldo_actual and self.saldo_actual <= 0):
            return 0

        if fecha_hasta is None:
            fecha_hasta = now().date()

        ultima_transaccion = (
            self.transacciones.filter(tipo__in=['PAGO_CUOTA', 'REFINANCIAMIENTO'])
            .order_by('-fecha', '-id')
            .first()
        )
        fecha_referencia = (
            ultima_transaccion.fecha
            if ultima_transaccion and ultima_transaccion.fecha
            else self.fecha_inicio
        )

        if not fecha_referencia or fecha_hasta <= fecha_referencia:
            return 0

        # Calcula directamente las quincenas completas de 15 días sin avanzar al siguiente ciclo
        dias_diferencia = (fecha_hasta - fecha_referencia).days
        return max(0, dias_diferencia // 15)

    @property
    def interes_atrasado_acumulado(self):
        """
        Calcula el interés atrasado sin incluir el interés corriente del período actual.
        """
        if not self.activo or (self.saldo_actual and self.saldo_actual <= Decimal('0.00')):
            return Decimal('0.00')

        ultima_transaccion = (
            self.transacciones.filter(tipo__in=['PAGO_CUOTA', 'REFINANCIAMIENTO'])
            .order_by('-fecha', '-id')
            .first()
        )

        if ultima_transaccion and getattr(ultima_transaccion, 'interes_atrasado', None) is not None:
            return Decimal(str(ultima_transaccion.interes_atrasado)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Quincenas totales transcurridas hasta hoy
        quincenas_totales = self.obtener_quincenas_pendientes()

        # Si hay quincenas pendientes, dejamos 1 para el 'Interés Corriente' y el resto a 'Mora Atrasada'
        quincenas_atrasadas = max(0, quincenas_totales - 1)

        tasa_decimal = Decimal(str(self.porcentaje_interes)) / Decimal('100.00')
        mora = Decimal(str(self.saldo_actual)) * tasa_decimal * Decimal(str(quincenas_atrasadas))

        return mora.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def en_mora(self):
        if not self.activo or (self.saldo_actual and self.saldo_actual <= Decimal('0.00')):
            return False

        return self.dias_sin_pagar > 15 or self.interes_atrasado_acumulado > Decimal('0.00')

    @transaction.atomic
    def aplicar_refinanciamiento(self, nuevo_monto_adicional=0, interes_pagado_efectivo=True):
        interes_cobrado = Decimal(str(self.interes_atrasado_acumulado or 0))
        monto_adicional_dec = Decimal(str(nuevo_monto_adicional or 0))
        saldo_previo = Decimal(str(self.saldo_actual or 0))

        if interes_pagado_efectivo:
            nuevo_saldo = saldo_previo + monto_adicional_dec
            monto_interes_transaccion = interes_cobrado
        else:
            nuevo_saldo = saldo_previo + interes_cobrado + monto_adicional_dec
            monto_interes_transaccion = Decimal('0.00')

        self.monto_prestado = Decimal(str(self.monto_prestado)) + monto_adicional_dec
        self.saldo_actual = nuevo_saldo
        self.save()

        return Transaccion.objects.create(
            prestamo=self,
            tipo='REFINANCIAMIENTO',
            monto=monto_adicional_dec + monto_interes_transaccion,
            monto_abonado_capital=monto_adicional_dec,
            interes_atrasado=monto_interes_transaccion,
            fecha=now().date()
        )

    @property
    def dias_sin_pagar(self):
        ultima_transaccion = self.transacciones.filter(
            tipo__in=['PAGO_CUOTA', 'REFINANCIAMIENTO']
        ).order_by('-fecha', '-id').first()

        if ultima_transaccion and ultima_transaccion.fecha:
            fecha_referencia = ultima_transaccion.fecha
        else:
            fecha_referencia = self.fecha_inicio

        if fecha_referencia:
            return (now().date() - fecha_referencia).days
        return 0

    @property
    def en_riesgo_critico(self):
        return self.activo and self.saldo_actual > Decimal('0.00') and self.dias_sin_pagar > 30


class Transaccion(models.Model):
    TIPO_CHOICES = [
        ('PAGO_CUOTA', 'Pago de Cuota / Abono'),
        ('ABONO_CAPITAL', 'Abono a Capital Solo'),
        ('REFINANCIAMIENTO', 'Refinanciamiento'),
    ]

    prestamo = models.ForeignKey(Prestamo, on_delete=models.CASCADE, related_name='transacciones')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default='PAGO_CUOTA')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    cobrar_mora = models.BooleanField(default=True, verbose_name='¿Cobrar mora por atraso?')
    interes_atrasado = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    monto_abonado_capital = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fecha = models.DateField(default=timezone.now)
    observacion = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transacción'
        verbose_name_plural = 'Transacciones'

    def __str__(self):
        return f'{self.get_tipo_display()} - ${self.monto} ({self.fecha})'

    @transaction.atomic
    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None

        if es_nuevo and self.prestamo:
            prestamo = self.prestamo
            monto_disponible = Decimal(str(self.monto or '0.00'))

            if self.tipo == 'ABONO_CAPITAL':
                # El 100% va directo a reducir el saldo del capital
                self.interes_atrasado = Decimal('0.00')
                self.monto_abonado_capital = monto_disponible

                prestamo.saldo_actual = max(
                    Decimal('0.00'),
                    Decimal(str(prestamo.saldo_actual)) - monto_disponible
                )

            elif self.tipo == 'PAGO_CUOTA':
                # 1. Interés corriente de la quincena
                tasa_decimal = Decimal(str(prestamo.porcentaje_interes)) / Decimal('100.00')
                interes_corriente_quincena = Decimal(str(prestamo.saldo_actual)) * tasa_decimal

                # 2. Consultar mora de la última transacción
                ultima_trans = prestamo.transacciones.filter(
                    tipo__in=['PAGO_CUOTA', 'ABONO_CAPITAL', 'REFINANCIAMIENTO']
                ).exclude(pk=self.pk).order_by('-fecha', '-id').first()

                mora_previa = Decimal(str(ultima_trans.interes_atrasado)) if ultima_trans else Decimal('0.00')
                interes_total = interes_corriente_quincena + mora_previa

                if not self.cobrar_mora:
                    interes_total = Decimal('0.00')

                # 3. Descontar del monto ingresado
                if monto_disponible >= interes_total:
                    excedente_capital = monto_disponible - interes_total
                    self.interes_atrasado = Decimal('0.00')
                    self.monto_abonado_capital = excedente_capital
                    
                    prestamo.saldo_actual = max(
                        Decimal('0.00'), 
                        Decimal(str(prestamo.saldo_actual)) - excedente_capital
                    )
                else:
                    self.interes_atrasado = (interes_total - monto_disponible).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    self.monto_abonado_capital = Decimal('0.00')

            elif self.tipo == 'REFINANCIAMIENTO':
                interes_pendiente = Decimal(str(prestamo.interes_atrasado_acumulado or '0.00'))

                if Decimal('0.00') < interes_pendiente <= monto_disponible:
                    self.interes_atrasado = Decimal('0.00')
                else:
                    self.interes_atrasado = max(Decimal('0.00'), interes_pendiente - monto_disponible)

                capital_adicional = max(Decimal('0.00'), monto_disponible - interes_pendiente)
                self.monto_abonado_capital = capital_adicional
                prestamo.saldo_actual += capital_adicional

            prestamo.save()




    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.prestamo:
            prestamo = self.prestamo

            if self.tipo in ['PAGO_CUOTA', 'ABONO_CAPITAL']:
                # Si se elimina un pago o abono, se devuelve el capital abonado al saldo
                monto_abonado = Decimal(str(self.monto_abonado_capital or '0.00'))
                prestamo.saldo_actual += monto_abonado

            elif self.tipo == 'REFINANCIAMIENTO':
                # Si se elimina un refinanciamiento, se resta el capital que se había sumado
                monto_adicional = Decimal(str(self.monto_abonado_capital or '0.00'))
                prestamo.saldo_actual = max(
                    Decimal('0.00'),
                    Decimal(str(prestamo.saldo_actual)) - monto_adicional
                )

            prestamo.save()

        super().delete(*args, **kwargs)


    def generar_ticket_whatsapp(self):
        cliente_nombre = self.prestamo.cliente.nombre
        codigo = self.prestamo.codigo_tramite
        saldo_anterior = self.prestamo.saldo_actual + self.monto_abonado_capital
        interes_pagado = self.monto - self.monto_abonado_capital

        tasa_decimal = self.prestamo.porcentaje_interes / Decimal('100.00')
        proximo_interes = (self.prestamo.saldo_actual * tasa_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        ticket = (
            '*COMPROBANTE DE PAGO*\n'
            '-----------------------------------\n'
            f'*Cliente:* {cliente_nombre}\n'
            f'*Trámite:* {codigo}\n'
            f"*Fecha:* {self.fecha.strftime('%d/%m/%Y')}\n"
            '-----------------------------------\n'
            f'*Monto Recibido:* ${self.monto:.2f}\n'
            f'*Abono a Capital:* ${self.monto_abonado_capital:.2f}\n'
            f'*Interés/Mora Pagado:* ${interes_pagado:.2f}\n'
            f'*Mora Pendiente:* ${self.interes_atrasado:.2f}\n'
            '-----------------------------------\n'
            f'*Saldo Anterior:* ${saldo_anterior:.2f}\n'
            f'*Saldo Actual:* ${self.prestamo.saldo_actual:.2f}\n'
            '-----------------------------------\n'
            f'*Próximo Interés:* ${proximo_interes:.2f}\n'
            '¡Gracias por su pago!'
        )
        return ticket

    def generar_url_whatsapp(self):
        texto = self.generar_ticket_whatsapp()
        telefono = self.prestamo.cliente.telefono or ''
        telefono_limpio = ''.join(filter(str.isdigit, telefono))
        return f'https://wa.me/{telefono_limpio}?text={quote(texto)}'


class HistorialAuditoria(models.Model):
    ACCIONES = (
        ('CREACION', 'Creación'),
        ('EDICION', 'Edición'),
        ('ELIMINACION', 'Eliminación'),
    )

    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Usuario")
    tabla = models.CharField(max_length=50, verbose_name="Módulo / Tabla")
    accion = models.CharField(max_length=20, choices=ACCIONES, verbose_name="Acción")
    descripcion = models.TextField(verbose_name="Descripción")
    fecha_hora = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y Hora")

    class Meta:
        verbose_name = "Historial de Auditoría"
        verbose_name_plural = "Historial de Auditoría"
        ordering = ['-fecha_hora']

    def __str__(self):
        usr = self.usuario.username if self.usuario else 'Sistema'
        return f"[{self.fecha_hora.strftime('%d/%m/%Y %H:%M')}] {usr} - {self.accion} en {self.tabla}"


class ConfiguracionFinanciera(models.Model):
    capital_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('200.00'),
        verbose_name="Capital Base Inicial",
    )

    class Meta:
        verbose_name = "Configuración Financiera"
        verbose_name_plural = "Configuración Financiera"

    def __str__(self):
        return f"Capital Base: ${self.capital_base}"


@receiver(post_delete, sender=Transaccion)
def reversar_transaccion_al_eliminar(sender, instance, **kwargs):
    prestamo = instance.prestamo

    if instance.tipo == 'PAGO_CUOTA':
        prestamo.saldo_actual += instance.monto_abonado_capital
    elif instance.tipo == 'REFINANCIAMIENTO':
        prestamo.saldo_actual -= instance.monto_abonado_capital

    if prestamo.saldo_actual > Decimal('0.00'):
        prestamo.activo = True

    prestamo.save()

    HistorialAuditoria.objects.create(
        tabla='Transacción',
        accion='ELIMINACION',
        descripcion=f'Se eliminó la transacción #{instance.id} del préstamo {prestamo.codigo_tramite}. Monto: ${instance.monto}. Saldo del préstamo restaurado a ${prestamo.saldo_actual}.',
    )


class Socio(models.Model):
    nombre = models.CharField(max_length=100)
    identificacion = models.CharField(max_length=20, blank=True, null=True)
    capital_invertido = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    porcentaje_retorno = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        help_text="Ejemplo: 10.00 para 10%"
    )
    comision_gestion = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'), 
        help_text="Monto retenido para el socio cobrador/administrador (ej. 40.00)"
    )
    activo = models.BooleanField(default=True)
    fecha_ingreso = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} - Capital: ${self.capital_invertido:,.2f}"

    @property
    def retorno_bruto(self):
        return (self.capital_invertido * self.porcentaje_retorno) / Decimal('100.00')

    @property
    def total_deducciones(self):
        deducciones_extra = sum(d.monto for d in self.deducciones.filter(activa=True))
        return self.comision_gestion + deducciones_extra

    @property
    def pago_neto_quincenal(self):
        return self.retorno_bruto - self.total_deducciones


class DeduccionSocio(models.Model):
    socio = models.ForeignKey(Socio, on_delete=models.CASCADE, related_name='deducciones')
    concepto = models.CharField(max_length=150, help_text="Ej: Descuento gastos nieta")
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    activa = models.BooleanField(default=True, help_text="Marcar para aplicar en la liquidación")

    def __str__(self):
        return f"{self.concepto} (${self.monto}) - {self.socio.nombre}"


class ConfiguracionEmpresa(models.Model):
    nombre_empresa = models.CharField(
        max_length=100, 
        default="Financiera La Dorada", 
        verbose_name="Nombre de la Empresa"
    )
    logo = models.ImageField(
        upload_to="empresa/", 
        blank=True, 
        null=True, 
        verbose_name="Logo de la Empresa"
    )
    telefono = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="Teléfono / WhatsApp de Contacto"
    )
    direccion = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Dirección Física"
    )

    class Meta:
        verbose_name = "Administración de la Página"
        verbose_name_plural = "Administración de la Página"

    def __str__(self):
        return self.nombre_empresa