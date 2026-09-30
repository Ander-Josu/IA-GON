from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# ==========================================================
# UNIDAD CONVIVENCIAL
# ==========================================================


class UnidadConvivencial(models.Model):
    nombre = models.CharField(
        max_length=100,
        unique=True,
    )

    descripcion = models.TextField(
        blank=True,
    )

    activa = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Unidad convivencial"
        verbose_name_plural = "Unidades convivenciales"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


# ==========================================================
# PROFESIONAL
# ==========================================================


class Profesional(models.Model):

    class Profesion(models.TextChoices):
        GEROCULTOR = (
            "GEROCULTOR",
            "Gerocultor/a",
        )
        ENFERMERIA = (
            "ENFERMERIA",
            "Enfermería",
        )
        MEDICINA = (
            "MEDICINA",
            "Medicina",
        )
        PSICOLOGIA = (
            "PSICOLOGIA",
            "Psicología",
        )
        FISIOTERAPIA = (
            "FISIOTERAPIA",
            "Fisioterapia",
        )
        TRABAJO_SOCIAL = (
            "TRABAJO_SOCIAL",
            "Trabajo social",
        )
        TERAPIA_OCUPACIONAL = (
            "TERAPIA_OCUPACIONAL",
            "Terapia ocupacional",
        )
        EDUCACION_SOCIAL = (
            "EDUCACION_SOCIAL",
            "Educación social",
        )
        OTRO = (
            "OTRO",
            "Otro",
        )

    usuario = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        related_name="profesional",
    )

    profesion = models.CharField(
        max_length=30,
        choices=Profesion.choices,
    )

    activo = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Profesional"
        verbose_name_plural = "Profesionales"
        ordering = [
            "usuario__last_name",
            "usuario__first_name",
        ]

    def __str__(self):
        nombre = self.usuario.get_full_name().strip()

        if not nombre:
            nombre = self.usuario.username

        return (
            f"{nombre} - "
            f"{self.get_profesion_display()}"
        )


# ==========================================================
# RESIDENTE
# ==========================================================


class Residente(models.Model):
    nombre = models.CharField(
        max_length=100,
    )

    apellidos = models.CharField(
        max_length=150,
    )

    nombre_preferido = models.CharField(
        max_length=100,
        blank=True,
    )

    fecha_nacimiento = models.DateField()

    fecha_ingreso = models.DateField()

    idioma_preferente = models.CharField(
        max_length=100,
        blank=True,
    )

    unidad = models.ForeignKey(
        UnidadConvivencial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="residentes",
    )

    profesional_referencia = models.ForeignKey(
        Profesional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="residentes_referencia",
    )

    activo = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Residente"
        verbose_name_plural = "Residentes"
        ordering = [
            "apellidos",
            "nombre",
        ]

    def __str__(self):
        return f"{self.apellidos}, {self.nombre}"


# ==========================================================
# SECCIÓN DEL PAyV
# ==========================================================


class SeccionPAyV(models.Model):

    class Bloque(models.TextChoices):
        QUIEN_SOY = (
            "QUIEN_SOY",
            "Quién soy",
        )
        QUE_QUIERO_NECESITO = (
            "QUE_QUIERO_NECESITO",
            "Qué quiero y qué necesito",
        )
        COMO_QUIERO = (
            "COMO_QUIERO",
            "Cómo quiero",
        )
        ME_ENCANTARIA = (
            "ME_ENCANTARIA",
            "Me encantaría",
        )

    codigo = models.CharField(
        max_length=100,
        unique=True,
    )

    bloque = models.CharField(
        max_length=30,
        choices=Bloque.choices,
    )

    categoria = models.CharField(
        max_length=150,
        blank=True,
    )

    titulo = models.CharField(
        max_length=200,
    )

    orden = models.PositiveIntegerField(
        default=0,
    )

    permite_multiples = models.BooleanField(
        default=False,
    )

    activa = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "Sección del PAyV"
        verbose_name_plural = "Secciones del PAyV"
        ordering = [
            "bloque",
            "orden",
            "titulo",
        ]

    def __str__(self):
        bloque = self.get_bloque_display()

        if self.categoria:
            return (
                f"{bloque} → "
                f"{self.categoria} → "
                f"{self.titulo}"
            )

        return f"{bloque} → {self.titulo}"


# ==========================================================
# PLAN DE ATENCIÓN Y VIDA
# ==========================================================


class PAyV(models.Model):
    residente = models.OneToOneField(
        Residente,
        on_delete=models.PROTECT,
        related_name="payv",
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
    )

    elaboracion_inicial_completada = models.BooleanField(
        default=False,
    )

    fecha_elaboracion_inicial = models.DateTimeField(
        null=True,
        blank=True,
    )

    elaboracion_completada_por = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payv_elaboraciones_completadas",
    )

    class Meta:
        verbose_name = "Plan de Atención y Vida"
        verbose_name_plural = "Planes de Atención y Vida"
        ordering = [
            "residente__apellidos",
            "residente__nombre",
        ]

    def __str__(self):
        return f"PAyV de {self.residente}"


# ==========================================================
# CONTENIDO DEL PAyV
# ==========================================================


class ContenidoPAyV(models.Model):
    payv = models.ForeignKey(
        PAyV,
        on_delete=models.PROTECT,
        related_name="contenidos",
    )

    seccion = models.ForeignKey(
        SeccionPAyV,
        on_delete=models.PROTECT,
        related_name="contenidos",
    )

    titulo_personalizado = models.CharField(
        max_length=200,
        blank=True,
    )

    contenido = models.TextField()

    orden = models.PositiveIntegerField(
        default=0,
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Contenido del PAyV"
        verbose_name_plural = "Contenidos del PAyV"
        ordering = [
            "payv",
            "seccion__orden",
            "orden",
        ]

    def __str__(self):
        return (
            f"{self.payv.residente} - "
            f"{self.seccion}"
        )


# ==========================================================
# ACONTECIMIENTO
# ==========================================================


class Acontecimiento(models.Model):

    class Tipo(models.TextChoices):
        CAIDA = (
            "CAIDA",
            "Caída",
        )
        HOSPITALIZACION = (
            "HOSPITALIZACION",
            "Hospitalización",
        )
        REGRESO_HOSPITALARIO = (
            "REGRESO_HOSPITALARIO",
            "Regreso hospitalario",
        )
        CAMBIO_SITUACION = (
            "CAMBIO_SITUACION",
            "Cambio significativo de situación",
        )
        OTRO = (
            "OTRO",
            "Otro",
        )

    residente = models.ForeignKey(
        Residente,
        on_delete=models.PROTECT,
        related_name="acontecimientos",
    )

    tipo = models.CharField(
        max_length=30,
        choices=Tipo.choices,
    )

    fecha_hora = models.DateTimeField(
        verbose_name="Fecha y hora del acontecimiento",
    )

    hora_aproximada = models.BooleanField(
        default=False,
        verbose_name="Hora aproximada",
    )

    descripcion = models.TextField()

    registrado_por = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name="acontecimientos_registrados",
    )

    fecha_hora_registro = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de registro",
    )

    class Meta:
        verbose_name = "Acontecimiento"
        verbose_name_plural = "Acontecimientos"
        ordering = [
            "-fecha_hora",
        ]

    def __str__(self):
        return (
            f"{self.residente} - "
            f"{self.get_tipo_display()} - "
            f"{self.fecha_hora:%d/%m/%Y}"
        )


# ==========================================================
# REVISIÓN DEL PAyV
# ==========================================================


class RevisionPAyV(models.Model):

    class Estado(models.TextChoices):
        PENDIENTE = (
            "PENDIENTE",
            "Pendiente",
        )
        EN_REVISION = (
            "EN_REVISION",
            "En revisión",
        )
        COMPLETADA = (
            "COMPLETADA",
            "Completada",
        )

    payv = models.ForeignKey(
        PAyV,
        on_delete=models.PROTECT,
        related_name="revisiones",
    )

    seccion = models.ForeignKey(
        SeccionPAyV,
        on_delete=models.PROTECT,
        related_name="revisiones",
    )

    acontecimiento = models.ForeignKey(
        Acontecimiento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisiones",
    )

    motivo = models.TextField()

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    responsables = models.ManyToManyField(
        Profesional,
        related_name="revisiones_asignadas",
        blank=True,
    )

    creada_por = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name="revisiones_creadas",
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
    )

    # ------------------------------------------------------
    # TRAZABILIDAD DEL INICIO
    # ------------------------------------------------------

    iniciada_por = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisiones_iniciadas",
    )

    fecha_inicio = models.DateTimeField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------
    # TRAZABILIDAD DE LA FINALIZACIÓN
    # ------------------------------------------------------

    completada_por = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisiones_completadas",
    )

    fecha_completada = models.DateTimeField(
        null=True,
        blank=True,
    )

    conclusion = models.TextField(
        blank=True,
    )

    class Meta:
        verbose_name = "Revisión del PAyV"
        verbose_name_plural = "Revisiones del PAyV"
        ordering = [
            "-fecha_creacion",
        ]

    def __str__(self):
        return (
            f"{self.payv.residente} - "
            f"{self.seccion} - "
            f"{self.get_estado_display()}"
        )


# ==========================================================
# MODIFICACIÓN DEL PAyV
# ==========================================================


class ModificacionPAyV(models.Model):
    contenido_payv = models.ForeignKey(
        ContenidoPAyV,
        on_delete=models.PROTECT,
        related_name="modificaciones",
    )

    revision = models.ForeignKey(
        RevisionPAyV,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="modificaciones",
    )

    profesional = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name="modificaciones_payv",
    )

    contenido_anterior = models.TextField(
        blank=True,
    )

    contenido_nuevo = models.TextField()

    motivo = models.TextField()

    fecha_hora = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Modificación del PAyV"
        verbose_name_plural = "Modificaciones del PAyV"
        ordering = [
            "-fecha_hora",
        ]

    def __str__(self):
        fecha_local = timezone.localtime(
            self.fecha_hora
        )

        return (
            f"{self.contenido_payv.payv.residente} - "
            f"{self.contenido_payv.seccion} - "
            f"{fecha_local:%d/%m/%Y %H:%M}"
        )