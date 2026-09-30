from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    ContenidoPAyV,
    ModificacionPAyV,
    PAyV,
    Profesional,
    Residente,
    RevisionPAyV,
    SeccionPAyV,
    UnidadConvivencial,
)

from .services import (
    completar_revision,
    finalizar_elaboracion_inicial,
    guardar_contenido_inicial,
    guardar_contenido_revision,
    iniciar_revision,
)


class IA_GONServicesTest(TestCase):

    def setUp(self):
        # --------------------------------------------------
        # UNIDAD
        # --------------------------------------------------

        self.unidad = UnidadConvivencial.objects.create(
            nombre="Haritza Test"
        )

        # --------------------------------------------------
        # PROFESIONALES
        # --------------------------------------------------

        usuario_ane = User.objects.create_user(
            username="ane.test",
            password="Test_Ane_2026!",
            first_name="Ane",
            last_name="López",
        )

        self.ane = Profesional.objects.create(
            usuario=usuario_ane,
            profesion=Profesional.Profesion.GEROCULTOR,
        )

        usuario_jon = User.objects.create_user(
            username="jon.test",
            password="Test_Jon_2026!",
            first_name="Jon",
            last_name="Pérez",
        )

        self.jon = Profesional.objects.create(
            usuario=usuario_jon,
            profesion=Profesional.Profesion.FISIOTERAPIA,
        )

        usuario_maria = User.objects.create_user(
            username="maria.test",
            password="Test_Maria_2026!",
            first_name="María",
            last_name="Santos",
        )

        self.otro_profesional = Profesional.objects.create(
            usuario=usuario_maria,
            profesion=Profesional.Profesion.ENFERMERIA,
        )

        # --------------------------------------------------
        # RESIDENTE
        # --------------------------------------------------

        self.residente = Residente.objects.create(
            nombre="Carmen",
            apellidos="García López",
            nombre_preferido="Carmen",
            fecha_nacimiento=date(1942, 4, 18),
            fecha_ingreso=date(2026, 6, 1),
            idioma_preferente="Castellano",
            unidad=self.unidad,
            profesional_referencia=self.ane,
        )

        # --------------------------------------------------
        # PAyV
        # --------------------------------------------------

        self.payv = PAyV.objects.create(
            residente=self.residente
        )

        # --------------------------------------------------
        # SECCIÓN
        # --------------------------------------------------

        self.seccion = SeccionPAyV.objects.create(
            codigo="TEST_APOYO_DESPLAZAMIENTOS",
            bloque=SeccionPAyV.Bloque.COMO_QUIERO,
            categoria="Pasar el día",
            titulo="Necesito apoyo en",
            orden=1,
            permite_multiples=False,
            activa=True,
        )

    # ======================================================
    # FUNCIONES AUXILIARES DE TEST
    # ======================================================

    def crear_contenido_inicial(self):
        return guardar_contenido_inicial(
            payv=self.payv,
            seccion=self.seccion,
            contenido=(
                "Necesito apoyo en algunos desplazamientos "
                "por la unidad."
            ),
            profesional=self.ane,
        )

    def preparar_payv_finalizado(self):
        self.crear_contenido_inicial()

        finalizar_elaboracion_inicial(
            payv=self.payv,
            profesional=self.ane,
        )

        self.payv.refresh_from_db()

    # ======================================================
    # TEST 1
    # ELABORACIÓN INICIAL
    # ======================================================

    def test_guardar_contenido_inicial_genera_trazabilidad(self):
        contenido, modificacion = (
            self.crear_contenido_inicial()
        )

        self.assertEqual(
            ContenidoPAyV.objects.count(),
            1,
        )

        self.assertEqual(
            ModificacionPAyV.objects.count(),
            1,
        )

        self.assertEqual(
            modificacion.profesional,
            self.ane,
        )

        self.assertIsNone(
            modificacion.revision
        )

        self.assertEqual(
            modificacion.contenido_anterior,
            "",
        )

        self.assertEqual(
            modificacion.contenido_nuevo,
            contenido.contenido,
        )

        self.assertEqual(
            modificacion.motivo,
            "Elaboración inicial del PAyV",
        )

    # ======================================================
    # TEST 2
    # NO FINALIZAR UN PAyV VACÍO
    # ======================================================

    def test_no_se_puede_finalizar_payv_sin_contenido(self):
        with self.assertRaises(ValidationError):
            finalizar_elaboracion_inicial(
                payv=self.payv,
                profesional=self.ane,
            )

        self.payv.refresh_from_db()

        self.assertFalse(
            self.payv.elaboracion_inicial_completada
        )

    # ======================================================
    # TEST 3
    # BLOQUEO DE ELABORACIÓN TRAS FINALIZAR
    # ======================================================

    def test_no_se_puede_anadir_contenido_inicial_tras_finalizar(self):
        self.preparar_payv_finalizado()

        self.assertTrue(
            self.payv.elaboracion_inicial_completada
        )

        self.assertEqual(
            self.payv.elaboracion_completada_por,
            self.ane,
        )

        self.assertIsNotNone(
            self.payv.fecha_elaboracion_inicial
        )

        with self.assertRaises(ValidationError):
            guardar_contenido_inicial(
                payv=self.payv,
                seccion=self.seccion,
                contenido="Nuevo contenido no permitido.",
                profesional=self.ane,
            )

    # ======================================================
    # TEST 4
    # PROFESIONAL NO RESPONSABLE
    # ======================================================

    def test_profesional_no_responsable_no_puede_iniciar_revision(self):
        self.preparar_payv_finalizado()

        revision = RevisionPAyV.objects.create(
            payv=self.payv,
            seccion=self.seccion,
            motivo="Revisar necesidades de apoyo.",
            creada_por=self.jon,
        )

        revision.responsables.add(
            self.jon
        )

        with self.assertRaises(ValidationError):
            iniciar_revision(
                revision,
                self.otro_profesional,
            )

        revision.refresh_from_db()

        self.assertEqual(
            revision.estado,
            RevisionPAyV.Estado.PENDIENTE,
        )

        self.assertIsNone(
            revision.iniciada_por
        )

    # ======================================================
    # TEST 5
    # TRAZABILIDAD MULTIPROFESIONAL COMPLETA
    # ======================================================

    def test_flujo_revision_multiprofesional_completo(self):
        self.preparar_payv_finalizado()

        revision = RevisionPAyV.objects.create(
            payv=self.payv,
            seccion=self.seccion,
            motivo=(
                "Revisar el apoyo durante "
                "los desplazamientos."
            ),
            creada_por=self.jon,
        )

        revision.responsables.add(
            self.jon,
            self.ane,
        )

        # Jon inicia la revisión
        iniciar_revision(
            revision,
            self.jon,
        )

        revision.refresh_from_db()

        self.assertEqual(
            revision.estado,
            RevisionPAyV.Estado.EN_REVISION,
        )

        self.assertEqual(
            revision.iniciada_por,
            self.jon,
        )

        self.assertIsNotNone(
            revision.fecha_inicio
        )

        # Ane modifica el contenido
        contenido, modificacion, creado = (
            guardar_contenido_revision(
                revision=revision,
                nuevo_contenido=(
                    "Necesito apoyo en algunos desplazamientos "
                    "y prefiero disponer de tiempo para "
                    "incorporarme antes de caminar."
                ),
                profesional=self.ane,
                motivo=(
                    "Se incorpora la preferencia expresada "
                    "por la persona."
                ),
            )
        )

        self.assertFalse(
            creado
        )

        self.assertEqual(
            modificacion.profesional,
            self.ane,
        )

        self.assertEqual(
            modificacion.revision,
            revision,
        )

        self.assertIn(
            "algunos desplazamientos",
            modificacion.contenido_anterior,
        )

        self.assertIn(
            "disponer de tiempo",
            modificacion.contenido_nuevo,
        )

        # Ane completa la revisión
        completar_revision(
            revision,
            self.ane,
            (
                "Tras la valoración compartida se acuerda "
                "actualizar el apoyo durante los desplazamientos."
            ),
        )

        revision.refresh_from_db()

        self.assertEqual(
            revision.estado,
            RevisionPAyV.Estado.COMPLETADA,
        )

        self.assertEqual(
            revision.creada_por,
            self.jon,
        )

        self.assertEqual(
            revision.iniciada_por,
            self.jon,
        )

        self.assertEqual(
            revision.completada_por,
            self.ane,
        )

        self.assertIsNotNone(
            revision.fecha_completada
        )

        self.assertTrue(
            revision.conclusion
        )

    # ======================================================
    # TEST 6
    # SOLO RESPONSABLES PUEDEN COMPLETAR
    # ======================================================

    def test_profesional_no_responsable_no_puede_completar_revision(self):
        self.preparar_payv_finalizado()

        revision = RevisionPAyV.objects.create(
            payv=self.payv,
            seccion=self.seccion,
            motivo="Revisión de prueba.",
            creada_por=self.jon,
        )

        revision.responsables.add(
            self.jon
        )

        iniciar_revision(
            revision,
            self.jon,
        )

        with self.assertRaises(ValidationError):
            completar_revision(
                revision,
                self.otro_profesional,
                "Conclusión no autorizada.",
            )

        revision.refresh_from_db()

        self.assertEqual(
            revision.estado,
            RevisionPAyV.Estado.EN_REVISION,
        )

        self.assertIsNone(
            revision.completada_por
        )