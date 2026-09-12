from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.admin.models import LogEntry
from .models import Cliente, Prestamo, Transaccion, HistorialAuditoria

def obtener_usuario_accion(instance):
    """
    Obtiene el usuario autenticado que ejecutó la operación
    consultando el registro oficial de la interfaz Admin de Django.
    """
    try:
        log = LogEntry.objects.filter(object_id=str(instance.pk)).order_by('-action_time').first()
        return log.user if log else None
    except Exception:
        return None

# ==========================================
# 1. AUDITORÍA DE CLIENTES
# ==========================================
@receiver(post_save, sender=Cliente)
def auditar_cliente_guardar(sender, instance, created, **kwargs):
    accion = 'CREACION' if created else 'EDICION'
    desc = f"Se {'creó' if created else 'actualizó'} el cliente {instance.nombre} (ID: {instance.identificacion or 'S/N'})."
    usr = obtener_usuario_accion(instance)
    HistorialAuditoria.objects.create(
        usuario=usr,
        tabla='Cliente',
        accion=accion,
        descripcion=desc
    )

@receiver(post_delete, sender=Cliente)
def auditar_cliente_eliminar(sender, instance, **kwargs):
    desc = f"Se eliminó el cliente {instance.nombre}."
    usr = obtener_usuario_accion(instance)
    HistorialAuditoria.objects.create(
        usuario=usr,
        tabla='Cliente',
        accion='ELIMINACION',
        descripcion=desc
    )

# ==========================================
# 2. AUDITORÍA DE PRÉSTAMOS
# ==========================================
@receiver(post_save, sender=Prestamo)
def auditar_prestamo_guardar(sender, instance, created, **kwargs):
    accion = 'CREACION' if created else 'EDICION'
    desc = f"Se {'creó' if created else 'actualizó'} el préstamo {instance.codigo_tramite} del cliente {instance.cliente.nombre}. Monto: ${instance.monto_prestado}."
    usr = obtener_usuario_accion(instance)
    HistorialAuditoria.objects.create(
        usuario=usr,
        tabla='Préstamo',
        accion=accion,
        descripcion=desc
    )

@receiver(post_delete, sender=Prestamo)
def auditar_prestamo_eliminar(sender, instance, **kwargs):
    desc = f"Se eliminó el préstamo {instance.codigo_tramite} del cliente {instance.cliente.nombre}."
    usr = obtener_usuario_accion(instance)
    HistorialAuditoria.objects.create(
        usuario=usr,
        tabla='Préstamo',
        accion='ELIMINACION',
        descripcion=desc
    )

# ==========================================
# 3. AUDITORÍA DE TRANSACCIONES / PAGOS
# ==========================================
@receiver(post_save, sender=Transaccion)
def auditar_transaccion_guardar(sender, instance, created, **kwargs):
    if created:
        desc = f"Se registró un pago/transacción de ${instance.monto} para el préstamo {instance.prestamo.codigo_tramite}."
        usr = obtener_usuario_accion(instance)
        HistorialAuditoria.objects.create(
            usuario=usr,
            tabla='Transacción',
            accion='CREACION',
            descripcion=desc
        )