from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (
    ContenidoPAyV,
    ModificacionPAyV,
    RevisionPAyV,
)


# ==========================================================
# FUNCIONES AUXILIARES
# ==========================================================


def _comprobar_responsable(revision, profesional):
    """
    Comprueba que el profesional esté asignado como responsable
    de la revisión.
    """

    if not revision.responsables.filter(
        pk=profesional.pk
    ).exists():
        raise ValidationError(
            "El profesional no está asignado como responsable "
            "de esta revisión."
        )


# ==========================================================
# ELABORACIÓN INICIAL DEL PAyV
# ==========================================================


@transaction.atomic
def guardar_contenido_inicial(
    *,
    payv,
    seccion,
    contenido,
    profesional,
    titulo_personalizado="",
):
    """
    Añade contenido durante la elaboración inicial del PAyV.

    La operación:
    - solo está permitida mientras la elaboración inicial
      no haya sido completada;
    - crea el contenido;
    - registra automáticamente la trazabilidad mediante
      ModificacionPAyV;
    - no crea una revisión artificial.
    """

    if payv.elaboracion_inicial_completada:
        raise ValidationError(
            "La elaboración inicial de este PAyV ya está completada. "
            "Los cambios posteriores deben realizarse mediante "
            "una revisión."
        )

    if not seccion.activa:
        raise ValidationError(
            "No se puede añadir contenido a una sección inactiva."
        )

    contenido = contenido.strip()
    titulo_personalizado = titulo_personalizado.strip()

    if not contenido:
        raise ValidationError(
            "El contenido no puede estar vacío."
        )

    contenidos_existentes = ContenidoPAyV.objects.filter(
        payv=payv,
        seccion=seccion,
    )

    # En las secciones que no admiten múltiples contenidos,
    # solo puede existir uno.
    if (
        not seccion.permite_multiples
        and contenidos_existentes.exists()
    ):
        raise ValidationError(
            "Esta sección ya tiene contenido. "
            "Durante la elaboración inicial no puede duplicarse."
        )

    # Si la sección permite varios contenidos,
    # calculamos automáticamente el siguiente orden.
    ultimo_orden = (
        contenidos_existentes.aggregate(
            max_orden=Max("orden")
        )["max_orden"]
        or 0
    )

    nuevo_orden = ultimo_orden + 1

    nuevo_contenido = ContenidoPAyV.objects.create(
        payv=payv,
        seccion=seccion,
        titulo_personalizado=titulo_personalizado,
        contenido=contenido,
        orden=nuevo_orden,
    )

    modificacion = ModificacionPAyV.objects.create(
        contenido_payv=nuevo_contenido,
        revision=None,
        profesional=profesional,
        contenido_anterior="",
        contenido_nuevo=contenido,
        motivo="Elaboración inicial del PAyV",
    )

    return nuevo_contenido, modificacion


@transaction.atomic
def finalizar_elaboracion_inicial(
    *,
    payv,
    profesional,
):
    """
    Da por completada la elaboración inicial del PAyV.

    No exige un número concreto de secciones porque el PAyV
    no debe convertirse en un checklist obligatorio.
    Sí exige que exista al menos un contenido.
    """

    if payv.elaboracion_inicial_completada:
        raise ValidationError(
            "La elaboración inicial de este PAyV "
            "ya está completada."
        )

    if not payv.contenidos.exists():
        raise ValidationError(
            "No se puede finalizar un PAyV "
            "que todavía no tiene contenido."
        )

    payv.elaboracion_inicial_completada = True
    payv.fecha_elaboracion_inicial = timezone.now()
    payv.elaboracion_completada_por = profesional

    payv.save(
        update_fields=[
            "elaboracion_inicial_completada",
            "fecha_elaboracion_inicial",
            "elaboracion_completada_por",
        ]
    )

    return payv


# ==========================================================
# INICIAR REVISIÓN
# ==========================================================


@transaction.atomic
def iniciar_revision(
    revision,
    profesional,
):
    """
    Inicia una revisión pendiente.

    Registra:
    - el cambio de estado a EN_REVISION;
    - la fecha y hora de inicio;
    - el profesional que la inicia.
    """

    if (
        revision.estado
        != RevisionPAyV.Estado.PENDIENTE
    ):
        raise ValidationError(
            "Solo se puede iniciar una revisión "
            "que esté pendiente."
        )

    _comprobar_responsable(
        revision,
        profesional,
    )

    revision.estado = (
        RevisionPAyV.Estado.EN_REVISION
    )

    revision.fecha_inicio = timezone.now()
    revision.iniciada_por = profesional

    revision.save(
        update_fields=[
            "estado",
            "fecha_inicio",
            "iniciada_por",
        ]
    )

    return revision


# ==========================================================
# ACTUALIZAR CONTENIDO DEL PAyV
# ==========================================================


@transaction.atomic
def actualizar_contenido_payv(
    *,
    contenido,
    nuevo_contenido,
    profesional,
    motivo,
    revision=None,
):
    """
    Actualiza un contenido ya existente del PAyV y genera
    automáticamente el registro de trazabilidad correspondiente.
    """

    nuevo_contenido = nuevo_contenido.strip()
    motivo = motivo.strip()

    if not nuevo_contenido:
        raise ValidationError(
            "El nuevo contenido no puede estar vacío."
        )

    if not motivo:
        raise ValidationError(
            "Debe indicarse el motivo del cambio."
        )

    contenido_anterior = contenido.contenido

    if (
        contenido_anterior.strip()
        == nuevo_contenido
    ):
        raise ValidationError(
            "El nuevo contenido es igual al contenido actual."
        )

    if revision is not None:

        if (
            revision.estado
            != RevisionPAyV.Estado.EN_REVISION
        ):
            raise ValidationError(
                "La revisión debe estar en estado "
                "'En revisión' para modificar el PAyV."
            )

        _comprobar_responsable(
            revision,
            profesional,
        )

        if revision.payv_id != contenido.payv_id:
            raise ValidationError(
                "El contenido no pertenece al PAyV "
                "de esta revisión."
            )

        if (
            revision.seccion_id
            != contenido.seccion_id
        ):
            raise ValidationError(
                "El contenido no pertenece a la sección "
                "asociada a esta revisión."
            )

    contenido.contenido = nuevo_contenido

    contenido.save(
        update_fields=[
            "contenido",
            "fecha_actualizacion",
        ]
    )

    modificacion = ModificacionPAyV.objects.create(
        contenido_payv=contenido,
        revision=revision,
        profesional=profesional,
        contenido_anterior=contenido_anterior,
        contenido_nuevo=nuevo_contenido,
        motivo=motivo,
    )

    return modificacion


# ==========================================================
# GUARDAR CONTENIDO DESDE UNA REVISIÓN
# ==========================================================


@transaction.atomic
def guardar_contenido_revision(
    *,
    revision,
    nuevo_contenido,
    profesional,
    motivo,
):
    """
    Crea o modifica el contenido correspondiente a la sección
    de una revisión.

    Si todavía no existe contenido para esa sección, se crea.
    Si existe uno, se actualiza.
    Si existen varios, el sistema no decide automáticamente cuál
    debe modificarse.
    """

    if (
        revision.estado
        != RevisionPAyV.Estado.EN_REVISION
    ):
        raise ValidationError(
            "La revisión debe estar en estado "
            "'En revisión'."
        )

    _comprobar_responsable(
        revision,
        profesional,
    )

    nuevo_contenido = nuevo_contenido.strip()
    motivo = motivo.strip()

    if not nuevo_contenido:
        raise ValidationError(
            "El contenido no puede estar vacío."
        )

    if not motivo:
        raise ValidationError(
            "Debe indicarse el motivo del cambio."
        )

    contenidos = list(
        ContenidoPAyV.objects.filter(
            payv=revision.payv,
            seccion=revision.seccion,
        ).order_by(
            "orden",
            "id",
        )
    )

    # ------------------------------------------------------
    # NO EXISTE CONTENIDO PREVIO
    # ------------------------------------------------------

    if len(contenidos) == 0:

        contenido = ContenidoPAyV.objects.create(
            payv=revision.payv,
            seccion=revision.seccion,
            contenido=nuevo_contenido,
            orden=1,
        )

        modificacion = ModificacionPAyV.objects.create(
            contenido_payv=contenido,
            revision=revision,
            profesional=profesional,
            contenido_anterior="",
            contenido_nuevo=nuevo_contenido,
            motivo=motivo,
        )

        return (
            contenido,
            modificacion,
            True,
        )

    # ------------------------------------------------------
    # EXISTE UN ÚNICO CONTENIDO
    # ------------------------------------------------------

    if len(contenidos) == 1:

        contenido = contenidos[0]

        modificacion = actualizar_contenido_payv(
            contenido=contenido,
            nuevo_contenido=nuevo_contenido,
            profesional=profesional,
            motivo=motivo,
            revision=revision,
        )

        return (
            contenido,
            modificacion,
            False,
        )

    # ------------------------------------------------------
    # EXISTEN VARIOS CONTENIDOS
    # ------------------------------------------------------

    raise ValidationError(
        "Esta sección tiene varios contenidos. "
        "IA-GON no puede decidir automáticamente "
        "cuál debe modificarse."
    )


# ==========================================================
# COMPLETAR REVISIÓN
# ==========================================================


@transaction.atomic
def completar_revision(
    revision,
    profesional,
    conclusion,
):
    """
    Completa una revisión que se encuentra en curso.

    Registra:
    - la conclusión;
    - la fecha y hora de finalización;
    - el profesional que la completa.
    """

    if (
        revision.estado
        != RevisionPAyV.Estado.EN_REVISION
    ):
        raise ValidationError(
            "Solo se puede completar una revisión "
            "que esté en estado 'En revisión'."
        )

    _comprobar_responsable(
        revision,
        profesional,
    )

    conclusion = conclusion.strip()

    if not conclusion:
        raise ValidationError(
            "Debe indicarse una conclusión "
            "antes de completar la revisión."
        )

    revision.estado = (
        RevisionPAyV.Estado.COMPLETADA
    )

    revision.fecha_completada = timezone.now()
    revision.completada_por = profesional
    revision.conclusion = conclusion

    revision.save(
        update_fields=[
            "estado",
            "fecha_completada",
            "completada_por",
            "conclusion",
        ]
    )

    return revision