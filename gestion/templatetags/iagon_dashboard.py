from django import template

from gestion.models import (
    PAyV,
    Profesional,
    Residente,
    RevisionPAyV,
    UnidadConvivencial,
)


register = template.Library()


@register.simple_tag
def datos_dashboard():
    """
    Devuelve los principales indicadores del panel
    de seguimiento de IA-GON.
    """

    datos = {
        "residentes_activos": (
            Residente.objects.filter(
                activo=True
            ).count()
        ),
        "profesionales_activos": (
            Profesional.objects.filter(
                activo=True
            ).count()
        ),
        "unidades_activas": (
            UnidadConvivencial.objects.filter(
                activa=True
            ).count()
        ),
        "actualizados": 0,
        "requieren_revision": 0,
        "en_revision": 0,
        "en_elaboracion": 0,
        "sin_contenido": 0,
        "revisiones_pendientes": (
            RevisionPAyV.objects.filter(
                estado=RevisionPAyV.Estado.PENDIENTE
            ).count()
        ),
        "revisiones_en_revision": (
            RevisionPAyV.objects.filter(
                estado=RevisionPAyV.Estado.EN_REVISION
            ).count()
        ),
    }

    payvs = PAyV.objects.all()

    for payv in payvs:

        if payv.revisiones.filter(
            estado=RevisionPAyV.Estado.PENDIENTE
        ).exists():
            datos["requieren_revision"] += 1

        elif payv.revisiones.filter(
            estado=RevisionPAyV.Estado.EN_REVISION
        ).exists():
            datos["en_revision"] += 1

        elif not payv.contenidos.exists():
            datos["sin_contenido"] += 1

        elif not payv.elaboracion_inicial_completada:
            datos["en_elaboracion"] += 1

        else:
            datos["actualizados"] += 1

    return datos