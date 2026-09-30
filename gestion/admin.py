from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join

from .models import (
    UnidadConvivencial,
    Profesional,
    Residente,
    PAyV,
    SeccionPAyV,
    ContenidoPAyV,
    Acontecimiento,
    RevisionPAyV,
    ModificacionPAyV,
)

from .services import (
    completar_revision,
    finalizar_elaboracion_inicial,
    guardar_contenido_inicial,
    guardar_contenido_revision,
    iniciar_revision,
)


# ==========================================================
# FUNCIONES AUXILIARES
# ==========================================================


def estado_coloreado(texto, color):
    return format_html(
        '<span style="color:{}; font-weight:600;">● {}</span>',
        color,
        texto,
    )


def obtener_profesional_usuario(usuario):
    try:
        return usuario.profesional
    except Profesional.DoesNotExist:
        return None


# ==========================================================
# FORMULARIOS
# ==========================================================


class ResidenteAdminForm(forms.ModelForm):
    fecha_nacimiento = forms.DateField(
        input_formats=["%d/%m/%Y"],
        widget=forms.TextInput(
            attrs={"placeholder": "DD/MM/AAAA"}
        ),
        label="Fecha nacimiento",
    )

    fecha_ingreso = forms.DateField(
        input_formats=["%d/%m/%Y"],
        widget=forms.TextInput(
            attrs={"placeholder": "DD/MM/AAAA"}
        ),
        label="Fecha ingreso",
    )

    class Meta:
        model = Residente
        fields = "__all__"


class RevisionPAyVAdminForm(forms.ModelForm):
    class Meta:
        model = RevisionPAyV
        fields = "__all__"

    def clean_responsables(self):
        responsables = self.cleaned_data.get("responsables")

        if not responsables or not responsables.exists():
            raise forms.ValidationError(
                "La revisión debe tener al menos "
                "un profesional responsable."
            )

        return responsables

    def clean(self):
        cleaned_data = super().clean()

        payv = cleaned_data.get("payv")
        acontecimiento = cleaned_data.get("acontecimiento")

        if (
            payv
            and acontecimiento
            and acontecimiento.residente_id != payv.residente_id
        ):
            raise forms.ValidationError(
                "El acontecimiento y el PAyV deben pertenecer "
                "al mismo residente."
            )

        return cleaned_data


class ContenidoInicialPAyVForm(forms.Form):
    seccion = forms.ModelChoiceField(
        label="Sección del PAyV",
        queryset=SeccionPAyV.objects.none(),
    )

    titulo_personalizado = forms.CharField(
        label="Título personalizado",
        required=False,
        max_length=200,
        help_text=(
            "Opcional. Úsalo solo cuando aporte información "
            "útil dentro de la sección."
        ),
    )

    contenido = forms.CharField(
        label="Contenido",
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "style": "width: 100%; max-width: 850px;",
            }
        ),
        help_text=(
            "Redacta la información desde una perspectiva "
            "centrada en la persona."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["seccion"].queryset = (
            SeccionPAyV.objects.filter(
                activa=True
            ).order_by(
                "bloque",
                "orden",
                "titulo",
            )
        )


class ActualizarContenidoRevisionForm(forms.Form):
    nuevo_contenido = forms.CharField(
        label="Nuevo contenido",
        widget=forms.Textarea(
            attrs={
                "rows": 9,
                "style": "width: 100%; max-width: 850px;",
            }
        ),
        help_text=(
            "Escribe cómo debe quedar esta información "
            "en el PAyV actual."
        ),
    )

    motivo = forms.CharField(
        label="Motivo del cambio",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "style": "width: 100%; max-width: 850px;",
            }
        ),
        help_text=(
            "Indica brevemente por qué se crea o modifica "
            "este contenido."
        ),
    )


class CompletarRevisionForm(forms.Form):
    conclusion = forms.CharField(
        label="Conclusión de la revisión",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "style": "width: 100%; max-width: 850px;",
            }
        ),
        help_text=(
            "Resume el resultado de la revisión y los acuerdos "
            "adoptados tras la valoración."
        ),
    )


# ==========================================================
# UNIDADES CONVIVENCIALES
# ==========================================================


@admin.register(UnidadConvivencial)
class UnidadConvivencialAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "activa",
    )

    search_fields = (
        "nombre",
    )

    list_filter = (
        "activa",
    )


# ==========================================================
# PROFESIONALES
# ==========================================================


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "profesion",
        "activo",
    )

    search_fields = (
        "usuario__username",
        "usuario__first_name",
        "usuario__last_name",
    )

    list_filter = (
        "profesion",
        "activo",
    )


# ==========================================================
# RESIDENTES
# ==========================================================


@admin.register(Residente)
class ResidenteAdmin(admin.ModelAdmin):
    form = ResidenteAdminForm

    list_display = (
        "apellidos",
        "nombre",
        "nombre_preferido",
        "unidad",
        "profesional_referencia",
        "estado_payv",
        "activo",
    )

    search_fields = (
        "nombre",
        "apellidos",
        "nombre_preferido",
    )

    list_filter = (
        "unidad",
        "activo",
    )

    @admin.display(description="Estado del PAyV")
    def estado_payv(self, obj):
        try:
            payv = obj.payv

        except PAyV.DoesNotExist:
            return estado_coloreado(
                "Sin PAyV",
                "#666666",
            )

        if payv.revisiones.filter(
            estado=RevisionPAyV.Estado.PENDIENTE
        ).exists():
            return estado_coloreado(
                "Requiere revisión",
                "#c62828",
            )

        if payv.revisiones.filter(
            estado=RevisionPAyV.Estado.EN_REVISION
        ).exists():
            return estado_coloreado(
                "En revisión",
                "#ef6c00",
            )

        if not payv.contenidos.exists():
            return estado_coloreado(
                "Sin contenido",
                "#666666",
            )

        if not payv.elaboracion_inicial_completada:
            return estado_coloreado(
                "En elaboración",
                "#1565c0",
            )

        return estado_coloreado(
            "Actualizado",
            "#2e7d32",
        )


# ==========================================================
# PLANES DE ATENCIÓN Y VIDA
# ==========================================================


@admin.register(PAyV)
class PAyVAdmin(admin.ModelAdmin):
    list_display = (
        "residente",
        "estado_visual",
        "fecha_creacion",
    )

    search_fields = (
        "residente__nombre",
        "residente__apellidos",
        "residente__nombre_preferido",
    )

    list_filter = (
        "residente__unidad",
        "elaboracion_inicial_completada",
    )

    readonly_fields = (
        "fecha_creacion",
        "elaboracion_inicial_completada",
        "fecha_elaboracion_inicial",
        "elaboracion_completada_por",
        "contenidos_agrupados",
    )

    fieldsets = (
        (
            "Datos del PAyV",
            {
                "fields": (
                    "residente",
                    "fecha_creacion",
                )
            },
        ),
        (
            "Elaboración inicial",
            {
                "fields": (
                    "elaboracion_inicial_completada",
                    "fecha_elaboracion_inicial",
                    "elaboracion_completada_por",
                )
            },
        ),
        (
            "Contenido actual del PAyV",
            {
                "fields": (
                    "contenidos_agrupados",
                )
            },
        ),
    )

    actions = (
        "accion_anadir_contenido_inicial",
        "accion_finalizar_elaboracion_inicial",
    )

    @admin.display(description="Estado")
    def estado_visual(self, obj):
        if obj.revisiones.filter(
            estado=RevisionPAyV.Estado.PENDIENTE
        ).exists():
            return estado_coloreado(
                "Requiere revisión",
                "#c62828",
            )

        if obj.revisiones.filter(
            estado=RevisionPAyV.Estado.EN_REVISION
        ).exists():
            return estado_coloreado(
                "En revisión",
                "#ef6c00",
            )

        if not obj.contenidos.exists():
            return estado_coloreado(
                "Sin contenido",
                "#666666",
            )

        if not obj.elaboracion_inicial_completada:
            return estado_coloreado(
                "En elaboración",
                "#1565c0",
            )

        return estado_coloreado(
            "Actualizado",
            "#2e7d32",
        )

    # ------------------------------------------------------
    # PRESENTACIÓN AGRUPADA DEL PAyV
    # ------------------------------------------------------

    @admin.display(description="PAyV actual")
    def contenidos_agrupados(self, obj):
        if obj is None or not obj.pk:
            return "Guarda primero el PAyV para incorporar contenido."

        contenidos = list(
            obj.contenidos.select_related(
                "seccion"
            ).order_by(
                "seccion__orden",
                "orden",
                "id",
            )
        )

        bloques_html = []

        for codigo_bloque, nombre_bloque in (
            SeccionPAyV.Bloque.choices
        ):
            contenidos_bloque = [
                contenido
                for contenido in contenidos
                if contenido.seccion.bloque == codigo_bloque
            ]

            elementos_html = []
            categoria_anterior = None

            for contenido in contenidos_bloque:
                categoria = (
                    contenido.seccion.categoria.strip()
                    if contenido.seccion.categoria
                    else ""
                )

                if (
                    categoria
                    and categoria != categoria_anterior
                ):
                    elementos_html.append(
                        format_html(
                            (
                                '<h4 class="iagon-payv-categoria">'
                                "{}</h4>"
                            ),
                            categoria,
                        )
                    )

                categoria_anterior = categoria

                titulo = (
                    contenido.titulo_personalizado.strip()
                    if contenido.titulo_personalizado
                    else contenido.seccion.titulo
                )

                elementos_html.append(
                    format_html(
                        (
                            '<div class="iagon-payv-item">'
                            '<div class="iagon-payv-titulo">'
                            "{}</div>"
                            '<div class="iagon-payv-contenido">'
                            "{}</div>"
                            "</div>"
                        ),
                        titulo,
                        contenido.contenido,
                    )
                )

            if elementos_html:
                cuerpo_bloque = format_html_join(
                    "",
                    "{}",
                    (
                        (elemento,)
                        for elemento in elementos_html
                    ),
                )

            else:
                cuerpo_bloque = format_html(
                    (
                        '<p class="iagon-payv-vacio">'
                        "{}</p>"
                    ),
                    "Sin contenido registrado.",
                )

            bloques_html.append(
                format_html(
                    (
                        '<section class="iagon-payv-bloque">'
                        '<h3 class="iagon-payv-bloque-titulo">'
                        "{}</h3>"
                        "{}"
                        "</section>"
                    ),
                    nombre_bloque,
                    cuerpo_bloque,
                )
            )

        return format_html_join(
            "",
            "{}",
            (
                (bloque,)
                for bloque in bloques_html
            ),
        )

    # ------------------------------------------------------
    # AÑADIR CONTENIDO INICIAL
    # ------------------------------------------------------

    @admin.action(
        description="Añadir contenido inicial al PAyV",
        permissions=["view"],
    )
    def accion_anadir_contenido_inicial(
        self,
        request,
        queryset,
    ):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecciona exactamente un PAyV.",
                level=messages.WARNING,
            )
            return

        payv = queryset.first()

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is None:
            self.message_user(
                request,
                "Tu usuario no tiene asociado "
                "un perfil profesional.",
                level=messages.ERROR,
            )
            return

        if payv.elaboracion_inicial_completada:
            self.message_user(
                request,
                "La elaboración inicial de este PAyV "
                "ya está completada. Los cambios posteriores "
                "deben realizarse mediante una revisión.",
                level=messages.ERROR,
            )
            return

        if request.POST.get(
            "confirmar_contenido_inicial"
        ) == "1":
            form = ContenidoInicialPAyVForm(
                request.POST
            )

            if form.is_valid():
                try:
                    guardar_contenido_inicial(
                        payv=payv,
                        seccion=form.cleaned_data["seccion"],
                        contenido=form.cleaned_data["contenido"],
                        profesional=profesional,
                        titulo_personalizado=(
                            form.cleaned_data[
                                "titulo_personalizado"
                            ]
                        ),
                    )

                except ValidationError as error:
                    form.add_error(
                        None,
                        error,
                    )

                else:
                    self.message_user(
                        request,
                        "El contenido inicial se ha guardado "
                        "y su trazabilidad ha quedado registrada.",
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        "admin:gestion_payv_changelist"
                    )

        else:
            form = ContenidoInicialPAyVForm()

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Añadir contenido inicial al PAyV",
            "opts": self.model._meta,
            "payv": payv,
            "form": form,
        }

        return TemplateResponse(
            request,
            (
                "admin/gestion/payv/"
                "anadir_contenido_inicial.html"
            ),
            contexto,
        )

    # ------------------------------------------------------
    # FINALIZAR ELABORACIÓN INICIAL
    # ------------------------------------------------------

    @admin.action(
        description="Finalizar elaboración inicial",
        permissions=["view"],
    )
    def accion_finalizar_elaboracion_inicial(
        self,
        request,
        queryset,
    ):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecciona exactamente un PAyV.",
                level=messages.WARNING,
            )
            return

        payv = queryset.first()

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is None:
            self.message_user(
                request,
                "Tu usuario no tiene asociado "
                "un perfil profesional.",
                level=messages.ERROR,
            )
            return

        if payv.elaboracion_inicial_completada:
            self.message_user(
                request,
                "La elaboración inicial de este PAyV "
                "ya está completada.",
                level=messages.WARNING,
            )
            return

        if request.POST.get(
            "confirmar_finalizacion"
        ) == "1":
            try:
                finalizar_elaboracion_inicial(
                    payv=payv,
                    profesional=profesional,
                )

            except ValidationError as error:
                self.message_user(
                    request,
                    str(error),
                    level=messages.ERROR,
                )

                return redirect(
                    "admin:gestion_payv_changelist"
                )

            self.message_user(
                request,
                "La elaboración inicial del PAyV "
                "se ha completado correctamente.",
                level=messages.SUCCESS,
            )

            return redirect(
                "admin:gestion_payv_changelist"
            )

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Finalizar elaboración inicial",
            "opts": self.model._meta,
            "payv": payv,
        }

        return TemplateResponse(
            request,
            (
                "admin/gestion/payv/"
                "finalizar_elaboracion_inicial.html"
            ),
            contexto,
        )


# ==========================================================
# SECCIONES DEL PAyV
# ==========================================================


@admin.register(SeccionPAyV)
class SeccionPAyVAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "bloque",
        "categoria",
        "titulo",
        "orden",
        "permite_multiples",
        "activa",
    )

    search_fields = (
        "codigo",
        "categoria",
        "titulo",
    )

    list_filter = (
        "bloque",
        "permite_multiples",
        "activa",
    )


# ==========================================================
# ACONTECIMIENTOS
# ==========================================================


@admin.register(Acontecimiento)
class AcontecimientoAdmin(admin.ModelAdmin):
    list_display = (
        "residente",
        "tipo",
        "fecha_hora",
        "hora_aproximada",
        "registrado_por",
        "fecha_hora_registro",
    )

    search_fields = (
        "residente__nombre",
        "residente__apellidos",
        "descripcion",
    )

    list_filter = (
        "tipo",
        "hora_aproximada",
        "residente__unidad",
    )

    date_hierarchy = "fecha_hora"

    def get_readonly_fields(self, request, obj=None):
        return (
            "fecha_hora_registro",
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(
            request,
            obj,
            **kwargs,
        )

        if request.user.is_superuser:
            return form

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is not None:
            campo = form.base_fields.get(
                "registrado_por"
            )

            if campo is not None:
                campo.queryset = Profesional.objects.filter(
                    pk=profesional.pk
                )

                campo.initial = profesional.pk
                campo.disabled = True

        return form

    def has_add_permission(self, request):
        permiso_base = super().has_add_permission(
            request
        )

        if not permiso_base:
            return False

        if request.user.is_superuser:
            return True

        return (
            obtener_profesional_usuario(request.user)
            is not None
        )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        if not request.user.is_superuser:
            profesional = obtener_profesional_usuario(
                request.user
            )

            if profesional is None:
                raise PermissionDenied(
                    "El usuario no tiene asociado "
                    "un perfil profesional."
                )

            obj.registrado_por = profesional

        super().save_model(
            request,
            obj,
            form,
            change,
        )


# ==========================================================
# REVISIONES DEL PAyV
# ==========================================================


@admin.register(RevisionPAyV)
class RevisionPAyVAdmin(admin.ModelAdmin):
    form = RevisionPAyVAdminForm

    list_display = (
        "payv",
        "seccion",
        "estado_visual",
        "acontecimiento",
        "fecha_creacion",
    )

    search_fields = (
        "payv__residente__nombre",
        "payv__residente__apellidos",
        "motivo",
        "conclusion",
    )

    list_filter = (
        "estado",
        "seccion__bloque",
        "payv__residente__unidad",
    )

    filter_horizontal = (
        "responsables",
    )

    actions = (
        "accion_iniciar_revision",
        "accion_actualizar_contenido",
        "accion_completar_revision",
    )

    @admin.action(
        description="Iniciar revisión seleccionada",
        permissions=["view"],
    )
    def accion_iniciar_revision(
        self,
        request,
        queryset,
    ):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecciona exactamente una revisión "
                "para iniciarla.",
                level=messages.WARNING,
            )
            return

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is None:
            self.message_user(
                request,
                "Tu usuario no tiene asociado "
                "un perfil profesional.",
                level=messages.ERROR,
            )
            return

        revision = queryset.first()

        try:
            iniciar_revision(
                revision,
                profesional,
            )

        except ValidationError as error:
            self.message_user(
                request,
                str(error),
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            "La revisión se ha iniciado correctamente.",
            level=messages.SUCCESS,
        )

    @admin.action(
        description="Actualizar contenido del PAyV",
        permissions=["view"],
    )
    def accion_actualizar_contenido(
        self,
        request,
        queryset,
    ):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecciona exactamente una revisión.",
                level=messages.WARNING,
            )
            return

        revision = queryset.first()

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is None:
            self.message_user(
                request,
                "Tu usuario no tiene asociado "
                "un perfil profesional.",
                level=messages.ERROR,
            )
            return

        if (
            revision.estado
            != RevisionPAyV.Estado.EN_REVISION
        ):
            self.message_user(
                request,
                "Solo se puede actualizar el PAyV desde "
                "una revisión que esté en estado "
                "'En revisión'.",
                level=messages.ERROR,
            )
            return

        if not revision.responsables.filter(
            pk=profesional.pk
        ).exists():
            self.message_user(
                request,
                "No estás asignado como responsable "
                "de esta revisión.",
                level=messages.ERROR,
            )
            return

        contenidos = list(
            ContenidoPAyV.objects.filter(
                payv=revision.payv,
                seccion=revision.seccion,
            ).order_by(
                "orden",
                "id",
            )
        )

        if len(contenidos) > 1:
            self.message_user(
                request,
                "Esta sección tiene varios contenidos. "
                "IA-GON no puede decidir automáticamente "
                "cuál debe modificarse.",
                level=messages.ERROR,
            )
            return

        contenido_actual = (
            contenidos[0]
            if contenidos
            else None
        )

        if request.POST.get(
            "confirmar_actualizacion"
        ) == "1":
            form = ActualizarContenidoRevisionForm(
                request.POST
            )

            if form.is_valid():
                try:
                    contenido, modificacion, creado = (
                        guardar_contenido_revision(
                            revision=revision,
                            nuevo_contenido=(
                                form.cleaned_data[
                                    "nuevo_contenido"
                                ]
                            ),
                            profesional=profesional,
                            motivo=(
                                form.cleaned_data[
                                    "motivo"
                                ]
                            ),
                        )
                    )

                except ValidationError as error:
                    form.add_error(
                        None,
                        error,
                    )

                else:
                    if creado:
                        mensaje = (
                            "El contenido se ha creado "
                            "correctamente y se ha registrado "
                            "su trazabilidad."
                        )
                    else:
                        mensaje = (
                            "El contenido se ha actualizado "
                            "correctamente y se ha registrado "
                            "su trazabilidad."
                        )

                    self.message_user(
                        request,
                        mensaje,
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        "admin:"
                        "gestion_revisionpayv_changelist"
                    )

        else:
            valores_iniciales = {
                "motivo": revision.motivo,
            }

            if contenido_actual is not None:
                valores_iniciales[
                    "nuevo_contenido"
                ] = contenido_actual.contenido

            form = ActualizarContenidoRevisionForm(
                initial=valores_iniciales
            )

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Actualizar contenido del PAyV",
            "opts": self.model._meta,
            "revision": revision,
            "contenido_actual": contenido_actual,
            "form": form,
        }

        return TemplateResponse(
            request,
            (
                "admin/gestion/revision_payv/"
                "actualizar_contenido.html"
            ),
            contexto,
        )

    @admin.action(
        description="Completar revisión seleccionada",
        permissions=["view"],
    )
    def accion_completar_revision(
        self,
        request,
        queryset,
    ):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecciona exactamente una revisión.",
                level=messages.WARNING,
            )
            return

        revision = queryset.first()

        profesional = obtener_profesional_usuario(
            request.user
        )

        if profesional is None:
            self.message_user(
                request,
                "Tu usuario no tiene asociado "
                "un perfil profesional.",
                level=messages.ERROR,
            )
            return

        if (
            revision.estado
            != RevisionPAyV.Estado.EN_REVISION
        ):
            self.message_user(
                request,
                "Solo se puede completar una revisión "
                "que esté en estado 'En revisión'.",
                level=messages.ERROR,
            )
            return

        if not revision.responsables.filter(
            pk=profesional.pk
        ).exists():
            self.message_user(
                request,
                "No estás asignado como responsable "
                "de esta revisión.",
                level=messages.ERROR,
            )
            return

        if request.POST.get(
            "confirmar_completado"
        ) == "1":
            form = CompletarRevisionForm(
                request.POST
            )

            if form.is_valid():
                try:
                    completar_revision(
                        revision,
                        profesional,
                        form.cleaned_data["conclusion"],
                    )

                except ValidationError as error:
                    form.add_error(
                        None,
                        error,
                    )

                else:
                    self.message_user(
                        request,
                        "La revisión se ha completado "
                        "correctamente.",
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        "admin:"
                        "gestion_revisionpayv_changelist"
                    )

        else:
            form = CompletarRevisionForm()

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Completar revisión del PAyV",
            "opts": self.model._meta,
            "revision": revision,
            "form": form,
        }

        return TemplateResponse(
            request,
            (
                "admin/gestion/revision_payv/"
                "completar_revision.html"
            ),
            contexto,
        )

    def get_fields(
        self,
        request,
        obj=None,
    ):
        if request.user.is_superuser:
            return (
                "payv",
                "seccion",
                "acontecimiento",
                "motivo",
                "estado",
                "responsables",
                "creada_por",
                "fecha_creacion",
                "iniciada_por",
                "fecha_inicio",
                "completada_por",
                "fecha_completada",
                "conclusion",
            )

        if obj is None:
            return (
                "payv",
                "seccion",
                "acontecimiento",
                "motivo",
                "responsables",
            )

        return (
            "payv",
            "seccion",
            "acontecimiento",
            "motivo",
            "estado",
            "responsables",
            "creada_por",
            "fecha_creacion",
            "iniciada_por",
            "fecha_inicio",
            "completada_por",
            "fecha_completada",
            "conclusion",
        )

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        if request.user.is_superuser:
            return (
                "fecha_creacion",
                "iniciada_por",
                "completada_por",
            )

        if obj is None:
            return ()

        return (
            "payv",
            "seccion",
            "acontecimiento",
            "motivo",
            "estado",
            "responsables",
            "creada_por",
            "fecha_creacion",
            "iniciada_por",
            "fecha_inicio",
            "completada_por",
            "fecha_completada",
            "conclusion",
        )

    def has_add_permission(
        self,
        request,
    ):
        permiso_base = super().has_add_permission(
            request
        )

        if not permiso_base:
            return False

        if request.user.is_superuser:
            return True

        return (
            obtener_profesional_usuario(request.user)
            is not None
        )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        if not request.user.is_superuser:
            profesional = obtener_profesional_usuario(
                request.user
            )

            if profesional is None:
                raise PermissionDenied(
                    "El usuario no tiene asociado "
                    "un perfil profesional."
                )

            if change:
                raise PermissionDenied(
                    "Las revisiones no pueden modificarse "
                    "directamente."
                )

            obj.creada_por = profesional
            obj.estado = RevisionPAyV.Estado.PENDIENTE

            obj.iniciada_por = None
            obj.fecha_inicio = None

            obj.completada_por = None
            obj.fecha_completada = None

            obj.conclusion = ""

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.display(description="Estado")
    def estado_visual(
        self,
        obj,
    ):
        if obj.estado == RevisionPAyV.Estado.COMPLETADA:
            return estado_coloreado(
                "Completada",
                "#2e7d32",
            )

        if obj.estado == RevisionPAyV.Estado.EN_REVISION:
            return estado_coloreado(
                "En revisión",
                "#ef6c00",
            )

        return estado_coloreado(
            "Pendiente",
            "#c62828",
        )


# ==========================================================
# HISTORIAL DE MODIFICACIONES
# ==========================================================


@admin.register(ModificacionPAyV)
class ModificacionPAyVAdmin(admin.ModelAdmin):
    list_display = (
        "contenido_payv",
        "profesional",
        "revision",
        "fecha_hora",
    )

    search_fields = (
        "contenido_payv__payv__residente__nombre",
        "contenido_payv__payv__residente__apellidos",
        "contenido_anterior",
        "contenido_nuevo",
        "motivo",
    )

    list_filter = (
        "contenido_payv__seccion__bloque",
        "profesional__profesion",
    )

    date_hierarchy = "fecha_hora"

    readonly_fields = (
        "contenido_payv",
        "revision",
        "profesional",
        "contenido_anterior",
        "contenido_nuevo",
        "motivo",
        "fecha_hora",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False