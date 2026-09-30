from datetime import date, timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gestion.models import (
    Acontecimiento,
    ContenidoPAyV,
    ModificacionPAyV,
    PAyV,
    Profesional,
    Residente,
    RevisionPAyV,
    SeccionPAyV,
    UnidadConvivencial,
)

from gestion.services import (
    completar_revision,
    guardar_contenido_revision,
    iniciar_revision,
)


class Command(BaseCommand):
    help = (
        "Carga un conjunto de datos sintéticos de demostración "
        "para IA-GON."
    )

    PASSWORD_DEMO = "IaGon_Demo_2026!"

    # ======================================================
    # UTILIDADES
    # ======================================================

    def buscar_seccion(self, titulo, categoria=None):
        queryset = SeccionPAyV.objects.filter(
            titulo=titulo,
            activa=True,
        )

        if categoria is not None:
            queryset = queryset.filter(
                categoria=categoria
            )

        seccion = queryset.order_by(
            "orden",
            "id",
        ).first()

        if seccion is None:
            detalle = titulo

            if categoria:
                detalle += f" / {categoria}"

            raise CommandError(
                f"No se ha encontrado la sección: {detalle}. "
                "Ejecuta antes: "
                "python manage.py loaddata secciones_payv"
            )

        return seccion

    def crear_usuario_profesional(
        self,
        *,
        username,
        nombre,
        apellidos,
        profesion,
        grupo,
    ):
        usuario, creado = User.objects.update_or_create(
            username=username,
            defaults={
                "first_name": nombre,
                "last_name": apellidos,
                "email": f"{username}@example.com",
                "is_active": True,
                "is_staff": True,
                "is_superuser": False,
            },
        )

        # No sobrescribimos contraseñas de usuarios que ya existían.
        if creado:
            usuario.set_password(
                self.PASSWORD_DEMO
            )
            usuario.save(
                update_fields=["password"]
            )

        usuario.groups.add(grupo)

        profesional, _ = Profesional.objects.update_or_create(
            usuario=usuario,
            defaults={
                "profesion": profesion,
                "activo": True,
            },
        )

        return profesional, creado

    def crear_residente(
        self,
        *,
        nombre,
        apellidos,
        nombre_preferido,
        nacimiento,
        ingreso,
        unidad,
        profesional_referencia,
    ):
        residente, _ = Residente.objects.update_or_create(
            nombre=nombre,
            apellidos=apellidos,
            defaults={
                "nombre_preferido": nombre_preferido,
                "fecha_nacimiento": nacimiento,
                "fecha_ingreso": ingreso,
                "idioma_preferente": "Castellano",
                "unidad": unidad,
                "profesional_referencia": (
                    profesional_referencia
                ),
                "activo": True,
            },
        )

        payv, payv_creado = PAyV.objects.get_or_create(
            residente=residente
        )

        return residente, payv, payv_creado

    def asegurar_contenido(
        self,
        *,
        payv,
        seccion,
        texto,
        profesional,
    ):
        contenido = (
            ContenidoPAyV.objects.filter(
                payv=payv,
                seccion=seccion,
            )
            .order_by("orden", "id")
            .first()
        )

        if contenido is not None:
            return contenido

        contenido = ContenidoPAyV.objects.create(
            payv=payv,
            seccion=seccion,
            contenido=texto,
            orden=1,
        )

        ModificacionPAyV.objects.create(
            contenido_payv=contenido,
            revision=None,
            profesional=profesional,
            contenido_anterior="",
            contenido_nuevo=texto,
            motivo="Elaboración inicial del PAyV",
        )

        return contenido

    def finalizar_demo_si_procede(
        self,
        *,
        payv,
        profesional,
    ):
        """
        Completa la elaboración inicial únicamente si todavía
        no estaba cerrada.

        Esto evita inventar de nuevo trazabilidad histórica
        en ejecuciones posteriores.
        """

        if payv.elaboracion_inicial_completada:
            return

        if not payv.contenidos.exists():
            return

        payv.elaboracion_inicial_completada = True

        payv.fecha_elaboracion_inicial = (
            timezone.now()
            - timedelta(days=30)
        )

        payv.elaboracion_completada_por = profesional

        payv.save(
            update_fields=[
                "elaboracion_inicial_completada",
                "fecha_elaboracion_inicial",
                "elaboracion_completada_por",
            ]
        )

    def crear_acontecimiento(
        self,
        *,
        residente,
        tipo,
        descripcion,
        profesional,
        dias_atras=1,
    ):
        acontecimiento = (
            Acontecimiento.objects.filter(
                residente=residente,
                tipo=tipo,
                descripcion=descripcion,
            )
            .order_by("id")
            .first()
        )

        if acontecimiento is not None:
            return acontecimiento

        return Acontecimiento.objects.create(
            residente=residente,
            tipo=tipo,
            fecha_hora=(
                timezone.now()
                - timedelta(days=dias_atras)
            ),
            hora_aproximada=False,
            descripcion=descripcion,
            registrado_por=profesional,
        )

    # ======================================================
    # COMANDO
    # ======================================================

    @transaction.atomic
    def handle(self, *args, **options):

        # --------------------------------------------------
        # COMPROBAR CATÁLOGO DEL PAyV
        # --------------------------------------------------

        if not SeccionPAyV.objects.exists():
            raise CommandError(
                "No existen secciones de PAyV. "
                "Ejecuta primero:\n"
                "python manage.py loaddata secciones_payv"
            )

        seccion_historia = self.buscar_seccion(
            "Mi historia"
        )

        seccion_apoyo = self.buscar_seccion(
            "Necesito apoyo en",
            "Pasar el día",
        )

        seccion_rutina = self.buscar_seccion(
            "Mi rutina",
            "Empezar el día",
        )

        # --------------------------------------------------
        # GRUPO Y PERMISOS
        # --------------------------------------------------

        grupo, _ = Group.objects.get_or_create(
            name="Profesionales IA-GON"
        )

        codenames = [
            "add_acontecimiento",
            "view_acontecimiento",
            "view_contenidopayv",
            "view_modificacionpayv",
            "view_payv",
            "view_profesional",
            "view_residente",
            "add_revisionpayv",
            "view_revisionpayv",
            "view_seccionpayv",
            "view_unidadconvivencial",
        ]

        permisos = Permission.objects.filter(
            content_type__app_label="gestion",
            codename__in=codenames,
        )

        grupo.permissions.add(*permisos)

        # --------------------------------------------------
        # UNIDADES
        # --------------------------------------------------

        unidades = {}

        for nombre in (
            "Haritza",
            "Itsasargi",
            "Lurberri",
        ):
            unidad, _ = (
                UnidadConvivencial.objects.update_or_create(
                    nombre=nombre,
                    defaults={
                        "descripcion": (
                            f"Unidad convivencial {nombre}"
                        ),
                        "activa": True,
                    },
                )
            )

            unidades[nombre] = unidad

        # --------------------------------------------------
        # PROFESIONALES
        # --------------------------------------------------

        profesionales_datos = [
            {
                "username": "ane.demo",
                "nombre": "Ane",
                "apellidos": "López",
                "profesion": (
                    Profesional.Profesion.GEROCULTOR
                ),
            },
            {
                "username": "jon.demo",
                "nombre": "Jon",
                "apellidos": "Pérez",
                "profesion": (
                    Profesional.Profesion.FISIOTERAPIA
                ),
            },
            {
                "username": "maite.demo",
                "nombre": "Maite",
                "apellidos": "Etxebarria",
                "profesion": (
                    Profesional.Profesion.ENFERMERIA
                ),
            },
            {
                "username": "iker.demo",
                "nombre": "Iker",
                "apellidos": "Alonso",
                "profesion": (
                    Profesional.Profesion.PSICOLOGIA
                ),
            },
            {
                "username": "leire.demo",
                "nombre": "Leire",
                "apellidos": "Martín",
                "profesion": (
                    Profesional.Profesion.TRABAJO_SOCIAL
                ),
            },
            {
                "username": "nerea.demo",
                "nombre": "Nerea",
                "apellidos": "Aguirre",
                "profesion": (
                    Profesional.Profesion.TERAPIA_OCUPACIONAL
                ),
            },
            {
                "username": "unai.demo",
                "nombre": "Unai",
                "apellidos": "Gómez",
                "profesion": (
                    Profesional.Profesion.EDUCACION_SOCIAL
                ),
            },
            {
                "username": "mikel.demo",
                "nombre": "Mikel",
                "apellidos": "Arana",
                "profesion": (
                    Profesional.Profesion.MEDICINA
                ),
            },
        ]

        profesionales = {}
        usuarios_nuevos = []

        for datos in profesionales_datos:
            profesional, usuario_creado = (
                self.crear_usuario_profesional(
                    grupo=grupo,
                    **datos,
                )
            )

            profesionales[
                datos["username"]
            ] = profesional

            if usuario_creado:
                usuarios_nuevos.append(
                    datos["username"]
                )

        # --------------------------------------------------
        # RESIDENTES
        # --------------------------------------------------

        residentes_datos = [
            {
                "nombre": "Carmen",
                "apellidos": "García López",
                "nombre_preferido": "Carmen",
                "nacimiento": date(1942, 4, 18),
                "ingreso": date(2026, 6, 1),
                "unidad": "Haritza",
                "referencia": "ane.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "María",
                "apellidos": "Fernández Ruiz",
                "nombre_preferido": "María",
                "nacimiento": date(1946, 11, 3),
                "ingreso": date(2026, 8, 15),
                "unidad": "Haritza",
                "referencia": "jon.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "José Antonio",
                "apellidos": "Martín Sanz",
                "nombre_preferido": "José",
                "nacimiento": date(1939, 7, 21),
                "ingreso": date(2025, 10, 8),
                "unidad": "Haritza",
                "referencia": "maite.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Teresa",
                "apellidos": "Aguirre Bilbao",
                "nombre_preferido": "Teresa",
                "nacimiento": date(1941, 2, 12),
                "ingreso": date(2026, 1, 16),
                "unidad": "Haritza",
                "referencia": "iker.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Pilar",
                "apellidos": "López Etxeberria",
                "nombre_preferido": "Pilar",
                "nacimiento": date(1944, 9, 9),
                "ingreso": date(2025, 12, 2),
                "unidad": "Itsasargi",
                "referencia": "leire.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Manuel",
                "apellidos": "Etxebarria Ruiz",
                "nombre_preferido": "Manu",
                "nacimiento": date(1938, 5, 30),
                "ingreso": date(2026, 3, 11),
                "unidad": "Itsasargi",
                "referencia": "nerea.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Rosa",
                "apellidos": "Martínez Gómez",
                "nombre_preferido": "Rosa",
                "nacimiento": date(1947, 1, 25),
                "ingreso": date(2026, 5, 6),
                "unidad": "Itsasargi",
                "referencia": "unai.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Antonio",
                "apellidos": "González Pérez",
                "nombre_preferido": "Antonio",
                "nacimiento": date(1940, 12, 14),
                "ingreso": date(2025, 11, 20),
                "unidad": "Itsasargi",
                "referencia": "mikel.demo",
                "estado_demo": "ACTUALIZADO",
            },
            {
                "nombre": "Elena",
                "apellidos": "Ruiz Arana",
                "nombre_preferido": "Elena",
                "nacimiento": date(1945, 3, 6),
                "ingreso": date(2026, 4, 2),
                "unidad": "Lurberri",
                "referencia": "ane.demo",
                "estado_demo": "PENDIENTE",
            },
            {
                "nombre": "Francisco",
                "apellidos": "Arana López",
                "nombre_preferido": "Paco",
                "nacimiento": date(1937, 8, 19),
                "ingreso": date(2026, 2, 10),
                "unidad": "Lurberri",
                "referencia": "jon.demo",
                "estado_demo": "EN_REVISION",
            },
            {
                "nombre": "Isabel",
                "apellidos": "Gómez Martín",
                "nombre_preferido": "Isabel",
                "nacimiento": date(1948, 6, 4),
                "ingreso": date(2026, 9, 2),
                "unidad": "Lurberri",
                "referencia": "maite.demo",
                "estado_demo": "EN_ELABORACION",
            },
            {
                "nombre": "Miguel",
                "apellidos": "Santos García",
                "nombre_preferido": "Miguel",
                "nacimiento": date(1943, 10, 28),
                "ingreso": date(2026, 9, 10),
                "unidad": "Lurberri",
                "referencia": "nerea.demo",
                "estado_demo": "SIN_CONTENIDO",
            },
        ]

        residentes = {}
        payvs = {}

        for datos in residentes_datos:
            residente, payv, _ = (
                self.crear_residente(
                    nombre=datos["nombre"],
                    apellidos=datos["apellidos"],
                    nombre_preferido=(
                        datos["nombre_preferido"]
                    ),
                    nacimiento=datos["nacimiento"],
                    ingreso=datos["ingreso"],
                    unidad=unidades[
                        datos["unidad"]
                    ],
                    profesional_referencia=(
                        profesionales[
                            datos["referencia"]
                        ]
                    ),
                )
            )

            clave = (
                f"{datos['nombre']} "
                f"{datos['apellidos']}"
            )

            residentes[clave] = residente
            payvs[clave] = payv

        # --------------------------------------------------
        # CONTENIDOS DEL PAyV
        # --------------------------------------------------

        contenidos_demo = {
            "Carmen García López": [
                (
                    seccion_historia,
                    (
                        "Nací en Dima y he vivido siempre "
                        "muy vinculada a mi familia y a mi entorno."
                    ),
                ),
                (
                    seccion_rutina,
                    (
                        "Prefiero desayunar antes de realizar "
                        "el aseo y comenzar el día con calma."
                    ),
                ),
            ],
            "María Fernández Ruiz": [
                (
                    seccion_historia,
                    (
                        "He vivido durante muchos años en Bizkaia. "
                        "Mi familia y mis costumbres son importantes "
                        "para mí."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Necesito apoyo en algunos desplazamientos. "
                        "Prefiero que me preguntes antes de ayudarme."
                    ),
                ),
            ],
            "José Antonio Martín Sanz": [
                (
                    seccion_historia,
                    (
                        "He trabajado gran parte de mi vida en "
                        "un taller y disfruto conversando sobre "
                        "mecánica y fútbol."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Agradezco supervisión al caminar por "
                        "espacios que no conozco."
                    ),
                ),
            ],
            "Teresa Aguirre Bilbao": [
                (
                    seccion_historia,
                    (
                        "Me gusta mantener el contacto con mis "
                        "amistades y participar en actividades "
                        "tranquilas."
                    ),
                ),
                (
                    seccion_rutina,
                    (
                        "Prefiero levantarme sin prisas y elegir "
                        "la ropa que voy a ponerme."
                    ),
                ),
            ],
            "Pilar López Etxeberria": [
                (
                    seccion_historia,
                    (
                        "La música y las reuniones familiares "
                        "han sido siempre importantes para mí."
                    ),
                ),
                (
                    seccion_rutina,
                    (
                        "Me gusta comenzar el día tomando café "
                        "mientras escucho la radio."
                    ),
                ),
            ],
            "Manuel Etxebarria Ruiz": [
                (
                    seccion_historia,
                    (
                        "He vivido muchos años cerca del mar y "
                        "disfruto hablando de pesca y de mi pueblo."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Necesito que me recuerden dónde están "
                        "algunos espacios cuando estoy desorientado."
                    ),
                ),
            ],
            "Rosa Martínez Gómez": [
                (
                    seccion_historia,
                    (
                        "Me gusta coser, leer revistas y pasar "
                        "tiempo con mis nietas."
                    ),
                ),
                (
                    seccion_rutina,
                    (
                        "Prefiero desayunar temprano y disponer "
                        "después de un rato tranquilo."
                    ),
                ),
            ],
            "Antonio González Pérez": [
                (
                    seccion_historia,
                    (
                        "He trabajado en el comercio y disfruto "
                        "conversando y manteniéndome activo."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Necesito apoyo puntual para organizar "
                        "algunas actividades del día."
                    ),
                ),
            ],
            "Elena Ruiz Arana": [
                (
                    seccion_historia,
                    (
                        "Valoro especialmente poder decidir sobre "
                        "mi rutina y mantener contacto frecuente "
                        "con mi hija."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Habitualmente camino de forma autónoma "
                        "por la unidad."
                    ),
                ),
            ],
            "Francisco Arana López": [
                (
                    seccion_historia,
                    (
                        "Prefiero que me llamen Paco. Me gusta "
                        "salir al jardín y conversar después de comer."
                    ),
                ),
                (
                    seccion_apoyo,
                    (
                        "Necesito apoyo para algunos desplazamientos "
                        "largos por la unidad."
                    ),
                ),
            ],
            "Isabel Gómez Martín": [
                (
                    seccion_historia,
                    (
                        "Acabo de incorporarme a la residencia. "
                        "Mi familia y mantener mis rutinas habituales "
                        "son muy importantes para mí."
                    ),
                ),
            ],
        }

        for clave, lista_contenidos in (
            contenidos_demo.items()
        ):
            payv = payvs[clave]

            profesional = (
                payv.residente.profesional_referencia
            )

            for seccion, texto in lista_contenidos:
                self.asegurar_contenido(
                    payv=payv,
                    seccion=seccion,
                    texto=texto,
                    profesional=profesional,
                )

        # --------------------------------------------------
        # CERRAR ELABORACIONES QUE CORRESPONDEN
        # --------------------------------------------------

        for datos in residentes_datos:
            if datos["estado_demo"] not in (
                "ACTUALIZADO",
                "PENDIENTE",
                "EN_REVISION",
            ):
                continue

            clave = (
                f"{datos['nombre']} "
                f"{datos['apellidos']}"
            )

            self.finalizar_demo_si_procede(
                payv=payvs[clave],
                profesional=profesionales[
                    datos["referencia"]
                ],
            )

        # --------------------------------------------------
        # REVISIÓN COMPLETADA DE EJEMPLO
        # --------------------------------------------------

        jose = residentes[
            "José Antonio Martín Sanz"
        ]

        payv_jose = payvs[
            "José Antonio Martín Sanz"
        ]

        evento_jose = self.crear_acontecimiento(
            residente=jose,
            tipo=Acontecimiento.Tipo.CAMBIO_SITUACION,
            descripcion=(
                "José refiere mayor inseguridad al caminar "
                "después de periodos prolongados sentado."
            ),
            profesional=profesionales["maite.demo"],
            dias_atras=12,
        )

        motivo_jose = (
            "Revisar el apoyo necesario al iniciar "
            "los desplazamientos."
        )

        revision_jose = (
            RevisionPAyV.objects.filter(
                payv=payv_jose,
                seccion=seccion_apoyo,
                motivo=motivo_jose,
            )
            .order_by("id")
            .first()
        )

        if revision_jose is None:
            revision_jose = RevisionPAyV.objects.create(
                payv=payv_jose,
                seccion=seccion_apoyo,
                acontecimiento=evento_jose,
                motivo=motivo_jose,
                creada_por=profesionales[
                    "maite.demo"
                ],
            )

            revision_jose.responsables.add(
                profesionales["maite.demo"],
                profesionales["jon.demo"],
            )

            iniciar_revision(
                revision_jose,
                profesionales["maite.demo"],
            )

            guardar_contenido_revision(
                revision=revision_jose,
                nuevo_contenido=(
                    "Agradezco apoyo al incorporarme después "
                    "de estar sentado y prefiero comenzar a "
                    "caminar cuando me siento estable."
                ),
                profesional=profesionales["jon.demo"],
                motivo=(
                    "Se incorpora la preferencia expresada "
                    "por José tras la valoración compartida."
                ),
            )

            completar_revision(
                revision_jose,
                profesionales["maite.demo"],
                (
                    "Se acuerda ofrecer apoyo al incorporarse "
                    "y respetar el tiempo que José necesita "
                    "antes de iniciar la marcha."
                ),
            )

        # --------------------------------------------------
        # REVISIÓN PENDIENTE
        # --------------------------------------------------

        elena = residentes[
            "Elena Ruiz Arana"
        ]

        evento_elena = self.crear_acontecimiento(
            residente=elena,
            tipo=Acontecimiento.Tipo.REGRESO_HOSPITALARIO,
            descripcion=(
                "Elena regresa tras una hospitalización "
                "y el equipo considera necesario revisar "
                "sus apoyos cotidianos."
            ),
            profesional=profesionales["ane.demo"],
            dias_atras=1,
        )

        revision_elena, creada = (
            RevisionPAyV.objects.get_or_create(
                payv=payvs["Elena Ruiz Arana"],
                seccion=seccion_apoyo,
                motivo=(
                    "Valorar los apoyos necesarios "
                    "tras el regreso hospitalario."
                ),
                defaults={
                    "acontecimiento": evento_elena,
                    "creada_por": profesionales[
                        "ane.demo"
                    ],
                    "estado": (
                        RevisionPAyV.Estado.PENDIENTE
                    ),
                },
            )
        )

        if creada:
            revision_elena.responsables.add(
                profesionales["ane.demo"],
                profesionales["mikel.demo"],
            )

        # --------------------------------------------------
        # REVISIÓN EN CURSO
        # --------------------------------------------------

        francisco = residentes[
            "Francisco Arana López"
        ]

        evento_francisco = self.crear_acontecimiento(
            residente=francisco,
            tipo=Acontecimiento.Tipo.CAIDA,
            descripcion=(
                "Francisco ha sufrido una caída sin lesión "
                "aparente durante un desplazamiento por la unidad."
            ),
            profesional=profesionales["jon.demo"],
            dias_atras=2,
        )

        revision_francisco, creada = (
            RevisionPAyV.objects.get_or_create(
                payv=payvs["Francisco Arana López"],
                seccion=seccion_apoyo,
                motivo=(
                    "Revisar los apoyos en movilidad "
                    "tras la caída registrada."
                ),
                defaults={
                    "acontecimiento": evento_francisco,
                    "creada_por": profesionales[
                        "jon.demo"
                    ],
                    "estado": (
                        RevisionPAyV.Estado.PENDIENTE
                    ),
                },
            )
        )

        if creada:
            revision_francisco.responsables.add(
                profesionales["jon.demo"],
                profesionales["nerea.demo"],
            )

            iniciar_revision(
                revision_francisco,
                profesionales["jon.demo"],
            )

        # --------------------------------------------------
        # RESUMEN
        # --------------------------------------------------

        estados = {
            "actualizados": 0,
            "requieren_revision": 0,
            "en_revision": 0,
            "en_elaboracion": 0,
            "sin_contenido": 0,
        }

        for payv in PAyV.objects.select_related(
            "residente"
        ):
            if payv.revisiones.filter(
                estado=RevisionPAyV.Estado.PENDIENTE
            ).exists():
                estados[
                    "requieren_revision"
                ] += 1

            elif payv.revisiones.filter(
                estado=RevisionPAyV.Estado.EN_REVISION
            ).exists():
                estados["en_revision"] += 1

            elif not payv.contenidos.exists():
                estados["sin_contenido"] += 1

            elif not payv.elaboracion_inicial_completada:
                estados["en_elaboracion"] += 1

            else:
                estados["actualizados"] += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Datos demo de IA-GON cargados correctamente."
            )
        )

        self.stdout.write("")
        self.stdout.write(
            f"Unidades: {UnidadConvivencial.objects.count()}"
        )

        self.stdout.write(
            f"Profesionales: {Profesional.objects.count()}"
        )

        self.stdout.write(
            f"Residentes: {Residente.objects.count()}"
        )

        self.stdout.write("")
        self.stdout.write("Estado de los PAyV:")

        self.stdout.write(
            f"  Actualizados: "
            f"{estados['actualizados']}"
        )

        self.stdout.write(
            f"  Requieren revisión: "
            f"{estados['requieren_revision']}"
        )

        self.stdout.write(
            f"  En revisión: "
            f"{estados['en_revision']}"
        )

        self.stdout.write(
            f"  En elaboración: "
            f"{estados['en_elaboracion']}"
        )

        self.stdout.write(
            f"  Sin contenido: "
            f"{estados['sin_contenido']}"
        )

        if usuarios_nuevos:
            self.stdout.write("")
            self.stdout.write(
                "Usuarios demo creados:"
            )

            for username in usuarios_nuevos:
                self.stdout.write(
                    f"  {username}"
                )

            self.stdout.write(
                f"Contraseña inicial común: "
                f"{self.PASSWORD_DEMO}"
            )

        self.stdout.write("")
        self.stdout.write(
            "El comando puede volver a ejecutarse "
            "sin duplicar los registros principales."
        )