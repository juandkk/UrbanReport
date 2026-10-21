"""
Pruebas de humo (smoke tests) de UrbanReport.

Recorren TODAS las páginas y los endpoints AJAX principales como ciudadano y
como administrador, y verifican que el número de consultas SQL del feed no
crezca con la cantidad de publicaciones (sin N+1).

Ejecutar SIEMPRE con la configuración aislada (SQLite en memoria):
    python manage.py test --settings=config.settings_test
"""
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from usuarios.models import Usuario, Seguimiento
from .models import (
    Publicacion, Comentario, Reposteo, ReaccionPublicacion, Notificacion,
)

PERFIL_COMPLETO = {
    'telefono': '3000000000',
    'direccion': 'Calle 1 # 2-3',
    'barrio_vereda': 'Medellín - Laureles',
    'codigo_postal': '050001',
}


def crear_publicaciones(autor, otros, n, con_comentarios=True):
    """Crea n publicaciones con comentarios, respuestas, reposteos y reacciones."""
    pubs = []
    for i in range(n):
        p = Publicacion.objects.create(
            autor=autor, autor_nombre=autor.username,
            titulo=f'Reporte {i} #Prueba', contenido=f'Contenido {i}',
            categoria=Publicacion.Categoria.VIAS,
            latitud=6.25, longitud=-75.57, ubicacion='Medellín',
            estado_incidencia=(
                Publicacion.EstadoIncidencia.RESUELTA if i % 3 == 0
                else Publicacion.EstadoIncidencia.REPORTADO
            ),
        )
        if con_comentarios:
            for o in otros:
                c = Comentario.objects.create(publicacion=p, autor=o, autor_nombre=o.username, texto='Comentario')
                Comentario.objects.create(publicacion=p, padre=c, autor=autor, autor_nombre=autor.username, texto='Respuesta')
                Reposteo.objects.create(usuario=o, publicacion=p)
                ReaccionPublicacion.objects.create(publicacion=p, usuario=o, tipo='LIKE')
        pubs.append(p)
    return pubs


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseUrbanReportTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ciudadano = Usuario.objects.create_user(
            username='ciudadano', email='c@test.co', password='x', first_name='Ciu', last_name='Dadano',
            **PERFIL_COMPLETO,
        )
        cls.otro = Usuario.objects.create_user(
            username='otro', email='o@test.co', password='x', **PERFIL_COMPLETO,
        )
        cls.admin = Usuario.objects.create_user(
            username='admin', email='a@test.co', password='x',
            rol=Usuario.Rol.ADMINISTRADOR, **PERFIL_COMPLETO,
        )
        Seguimiento.objects.create(seguidor=cls.otro, seguido=cls.ciudadano)
        cls.pubs = crear_publicaciones(cls.ciudadano, [cls.otro, cls.admin], 4)
        cls.pub = cls.pubs[0]
        cls.comentario = cls.pub.comentarios.filter(padre__isnull=True).first()


class PaginasTest(BaseUrbanReportTest):
    """Todas las páginas responden 200 (o redirección esperada)."""

    def _get_ok(self, url, status=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, status, f'{url} -> {r.status_code}')
        return r

    def test_paginas_anonimas(self):
        self._get_ok(reverse('login'))
        self._get_ok(reverse('registro'))
        self._get_ok(reverse('recuperar_contrasena'))
        # Protegidas: redirigen al login
        self._get_ok(reverse('feed_comunitario'), status=302)

    def test_paginas_ciudadano(self):
        self.client.force_login(self.ciudadano)
        for name, args in [
            ('feed_comunitario', []),
            ('detalle_publicacion', [self.pub.id]),
            ('estadisticas', []),
            ('ayuda', []),
            ('guia_ciudadano', []),
            ('mapa', []),
            ('notificaciones', []),
            ('perfil', []),
            ('perfil_usuario', ['otro']),
            ('configuracion', []),
        ]:
            self._get_ok(reverse(name, args=args))
        self._get_ok(reverse('perfil') + '?tab=reposteos')
        # Vistas de admin: 403 para ciudadanos
        for name in ('panel_administrador', 'incidentes', 'manual_administrador'):
            self._get_ok(reverse(name), status=403)

    def test_paginas_admin(self):
        self.client.force_login(self.admin)
        for name in ('panel_administrador', 'incidentes', 'manual_administrador', 'estadisticas'):
            self._get_ok(reverse(name))
        self._get_ok(reverse('estadisticas') + '?rango=todo')
        self._get_ok(reverse('incidentes') + '?q=Reporte&estado=REPORTADO')
        r = self._get_ok(reverse('exportar_incidentes'))
        self.assertIn('text/csv', r['Content-Type'])

    def test_feed_muestra_datos_reales_sin_hardcode(self):
        """El feed no debe inventar imágenes, avatares ni tiempos según el nombre."""
        Publicacion.objects.create(
            autor=self.otro, autor_nombre='Ana Prueba', contenido='Hay un bache enorme',
        )
        self.client.force_login(self.ciudadano)
        html = self._get_ok(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('img/bache.jpg', html)
        self.assertNotIn('Hace 15 min', html)
        self.assertNotIn('Hace 2 horas', html)

    def test_no_se_siembran_datos_demo(self):
        """Visitar vistas con la BD vacía NO debe crear usuarios/publicaciones/notificaciones falsas."""
        Publicacion.objects.all().delete()
        usuarios_antes = Usuario.objects.count()
        self.client.force_login(self.admin)
        for name in ('feed_comunitario', 'estadisticas', 'panel_administrador', 'incidentes', 'notificaciones'):
            self._get_ok(reverse(name))
        self.assertEqual(Publicacion.objects.count(), 0)
        self.assertEqual(Usuario.objects.count(), usuarios_antes)
        self.assertFalse(Notificacion.objects.filter(actor__isnull=True).exists())


class ApiTest(BaseUrbanReportTest):
    """Endpoints AJAX/JSON principales."""

    def setUp(self):
        self.client.force_login(self.ciudadano)

    def _json(self, url, method='get', data=None, status=200):
        r = getattr(self.client, method)(url, data or {})
        self.assertEqual(r.status_code, status, f'{url} -> {r.status_code}: {r.content[:200]}')
        return r.json()

    def test_apis_lectura(self):
        d = self._json(reverse('api_incidentes_mapa'))
        self.assertEqual(len(d['incidentes']), 4)
        self.assertIn('comentarios', d['incidentes'][0])
        self.assertIn('censurado', d['incidentes'][0])
        self.assertIn('motivo_censura', d['incidentes'][0])
        self._json(reverse('api_incidentes_mapa') + '?estado=RESUELTA')
        d = self._json(reverse('render_post_card_ajax', args=[self.pub.id]))
        self.assertIn('post-card', d['html'])
        self._json(reverse('api_feed_actualizado'))
        self._json(reverse('api_actividad_reciente'))
        d = self._json(reverse('api_trending_topics'))
        self.assertTrue(d['trending_topics'])
        self._json(reverse('api_notificaciones_no_leidas'))
        d = self._json(reverse('api_buscar_publicaciones') + '?q=reporte')
        self.assertGreater(d['count'], 0)
        d = self._json(reverse('lista_seguidores', args=['ciudadano']))
        self.assertEqual(len(d['usuarios']), 1)
        self.assertEqual(d['usuarios'][0]['perfil_url'], reverse('perfil_usuario', args=['otro']))
        self._json(reverse('lista_seguidos', args=['otro']))

    def test_apis_escritura(self):
        pid = self.pubs[1].id
        d = self._json(reverse('reaccionar_publicacion_ajax', args=[pid]), 'post', {'tipo': 'LIKE'})
        self.assertEqual(d['user_reaction'], 'LIKE')
        d = self._json(reverse('agregar_comentario_ajax', args=[pid]), 'post', {'texto': 'hola'})
        self.assertEqual(d['status'], 'ok')
        d = self._json(reverse('toggle_repost_ajax', args=[pid]), 'post')
        self.assertTrue(d['reposteado'])
        d = self._json(reverse('editar_publicacion_ajax', args=[pid]), 'post', {'titulo': 'T', 'contenido': 'C'})
        self.assertEqual(d['status'], 'ok')
        d = self._json(reverse('toggle_seguir', args=['otro']), 'post')
        self.assertTrue(d['siguiendo'])
        # Ciudadano no puede cambiar estado
        self._json(reverse('cambiar_estado_incidencia_ajax', args=[pid]), 'post', {'estado': 'RESUELTA'}, status=403)

    def test_admin_cambia_estado(self):
        self.client.force_login(self.admin)
        d = self._json(reverse('cambiar_estado_incidencia_ajax', args=[self.pubs[1].id]), 'post', {'estado': 'RESUELTA'})
        self.assertTrue(d['es_resuelta'])

    def test_admin_declina_reporte_con_motivo_y_notifica_al_autor(self):
        target_pub = self.pubs[1]
        url = reverse('cambiar_estado_incidencia_ajax', args=[target_pub.id])

        # Un ciudadano no puede declinar
        self.client.force_login(self.ciudadano)
        self._json(url, 'post', {'estado': 'DECLINADO', 'motivo': 'DUPLICADO'}, status=403)

        # El administrador declina con motivo predeterminado + observación
        self.client.force_login(self.admin)
        d = self._json(url, 'post', {
            'estado': 'DECLINADO',
            'motivo': 'DUPLICADO',
            'detalle': 'Ya existe el radicado #1 en atención',
        }, status=200)
        self.assertEqual(d['estado'], 'DECLINADO')
        self.assertTrue(d['es_declinada'])
        self.assertIn('Reporte duplicado', d['motivo_declinacion'])
        self.assertIn('Ya existe el radicado #1', d['motivo_declinacion'])

        target_pub.refresh_from_db()
        self.assertEqual(target_pub.estado_incidencia, Publicacion.EstadoIncidencia.DECLINADO)
        self.assertIn('Reporte duplicado', target_pub.motivo_declinacion)

        # Verificar que el dueño del reporte recibió la notificación con el motivo
        notif = Notificacion.objects.filter(
            destinatario=self.ciudadano,
            publicacion=target_pub,
            tipo=Notificacion.Tipo.CAMBIO_ESTADO,
        ).order_by('-id').first()
        self.assertIsNotNone(notif)
        self.assertIn('Declinado', notif.extra)
        self.assertIn('Reporte duplicado', notif.extra)

        # Si el admin reabre a EN_PROCESO, se limpia el motivo de declinación
        d_reopen = self._json(url, 'post', {'estado': 'EN_PROCESO'}, status=200)
        self.assertEqual(d_reopen['estado'], 'EN_PROCESO')
        target_pub.refresh_from_db()
        self.assertEqual(target_pub.motivo_declinacion, '')

    def test_seguridad_censurar_comentario_solo_admin(self):
        """Un ciudadano (incluso autor) no puede censurar comentarios (403); un admin sí puede (200)."""
        comentario = Comentario.objects.filter(publicacion=self.pubs[0]).first()
        url = reverse('moderar_comentario_ajax', args=[comentario.id])

        # Ciudadano no puede censurar
        self.client.force_login(self.ciudadano)
        self._json(url, 'post', {'accion': 'CENSURAR'}, status=403)
        comentario.refresh_from_db()
        self.assertFalse(comentario.censurado)

        # Admin sí puede censurar
        self.client.force_login(self.admin)
        d = self._json(url, 'post', {'accion': 'CENSURAR'}, status=200)
        self.assertTrue(d['censurado'])
        comentario.refresh_from_db()
        self.assertTrue(comentario.censurado)

        # Moderar publicación: censurar post con imagen y verificar plantilla
        self.pub.imagen_url = 'https://example.com/evidencia.jpg'
        self.pub.save(update_fields=['imagen_url'])
        pub_url = reverse('moderar_publicacion_ajax', args=[self.pub.id])
        dp = self._json(pub_url, 'post', {'accion': 'CENSURAR'}, status=200)
        self.assertTrue(dp['censurado'])
        self.pub.refresh_from_db()
        self.assertTrue(self.pub.censurado)

        # La tarjeta renderizada debe incluir clases de censura reforzada
        rendered = self._json(reverse('render_post_card_ajax', args=[self.pub.id]))
        self.assertIn('is-censored-card', rendered['html'])
        self.assertIn('is-censored-media', rendered['html'])
        self.assertIn('censor-media-shield', rendered['html'])
        self.assertNotIn('is-expandable-media', rendered['html'])



    def test_radicar_incidencia_valida_limites_medellin_y_sanitiza_imagen(self):
        """radicar_incidencia_ajax rechaza coordenadas fuera de Medellín y redimensiona imágenes grandes."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        import io
        from feed.views import sanitizar_imagen, ImagenInvalida

        self.client.force_login(self.ciudadano)
        url = reverse('radicar_incidencia_ajax')

        # Coordenadas en Bogotá -> debe ser rechazado (400)
        self._json(url, 'post', {
            'titulo': 'Fuera de rango',
            'categoria': 'VIAS',
            'contenido': 'Prueba fuera de Medellín',
            'ubicacion': 'Bogotá',
            'latitud': '4.6097100',
            'longitud': '-74.0817500',
            'ubicacion_fijada': '1',
        }, status=400)

        # Coordenadas válidas en Medellín (El Poblado) -> aceptado (200)
        d = self._json(url, 'post', {
            'titulo': 'Fuga de agua en El Poblado',
            'categoria': 'ACUEDUCTO',
            'contenido': 'Tubería rota sobre la vía principal',
            'ubicacion': 'Calle 10, El Poblado',
            'latitud': '6.2090000',
            'longitud': '-75.5700000',
            'ubicacion_fijada': '1',
        }, status=200)
        self.assertEqual(d['incidente']['categoria'], 'ACUEDUCTO')
        self.assertEqual(d['incidente']['categoria_display'], 'Acueducto y alcantarillado')

        # Sanitización: rechaza archivo corrupto y redimensiona imagen > 1600px
        with self.assertRaises(ImagenInvalida):
            sanitizar_imagen(SimpleUploadedFile('falso.jpg', b'no es una imagen', content_type='image/jpeg'))

        buf = io.BytesIO()
        Image.new('RGB', (2400, 1800), (10, 20, 30)).save(buf, format='JPEG')
        archivo_grande = SimpleUploadedFile('grande.jpg', buf.getvalue(), content_type='image/jpeg')
        limpia = sanitizar_imagen(archivo_grande)
        with Image.open(limpia) as img_out:
            self.assertLessEqual(img_out.width, 1600)
            self.assertLessEqual(img_out.height, 1600)

    def test_plantillas_sin_cache_busting_dinamico_ni_ids_duplicados(self):
        """Las plantillas no deben incluir ?v=<timestamp> ni duplicar id='urbanToast'."""
        self.client.force_login(self.ciudadano)
        r = self.client.get(reverse('feed_comunitario'))
        html = r.content.decode('utf-8')
        self.assertNotIn('.css?v=', html)
        self.assertNotIn('.js?v=', html)
        self.assertEqual(html.count('id="urbanToast"'), 1)



class ModeracionLenguajeTest(BaseUrbanReportTest):
    """
    Verifica el filtro de lenguaje inapropiado (feed/moderacion.py) integrado en
    los puntos de entrada de publicaciones y comentarios.
    """

    def setUp(self):
        self.client.force_login(self.ciudadano)

    def _json(self, url, data=None, status=200):
        r = self.client.post(url, data or {})
        self.assertEqual(r.status_code, status, f'{url} -> {r.status_code}: {r.content[:200]}')
        return r.json()

    # ── Pruebas directas del módulo de moderación ──
    def test_modulo_detecta_y_permite(self):
        from feed.moderacion import contiene_lenguaje_inapropiado as c
        # Permitido
        self.assertFalse(c('Hay un bache enorme en la Avenida Oriental'))
        self.assertFalse(c('El alumbrado del parque está dañado'))
        self.assertFalse(c(''))
        # Prohibido (español, mayúsculas, tildes, leet, separado)
        self.assertTrue(c('eres un gonorrea'))
        self.assertTrue(c('MARICA'))
        self.assertTrue(c('hijueputa'))
        self.assertTrue(c('p3nd3j0'))
        self.assertTrue(c('p u t a'))

    def test_sin_falsos_positivos(self):
        """Palabras legítimas que contienen subcadenas sensibles no deben bloquearse."""
        from feed.moderacion import contiene_lenguaje_inapropiado as c
        for texto in [
            'Carlos Vergara reportó el daño',   # "Vergara" contiene "verga"
            'La administración municipal respondió',
            'Hay basura acumulada en la esquina',
            'El semáforo de la calle 50 no sirve',
        ]:
            self.assertFalse(c(texto), f'Falso positivo con: {texto}')

    # ── 1. Publicación con lenguaje permitido se guarda ──
    def test_publicacion_limpia_se_guarda(self):
        url = reverse('radicar_incidencia_ajax')
        antes = Publicacion.objects.count()
        d = self._json(url, {
            'titulo': 'Hueco peligroso',
            'categoria': 'VIAS',
            'contenido': 'Hay un hueco grande en la vía',
            'ubicacion': 'Calle 10, El Poblado',
            'latitud': '6.2090000', 'longitud': '-75.5700000', 'ubicacion_fijada': '1',
        }, status=200)
        self.assertEqual(d['status'], 'ok')
        self.assertEqual(Publicacion.objects.count(), antes + 1)

    # ── 2. Publicación con palabras prohibidas se rechaza ──
    def test_publicacion_inapropiada_se_rechaza(self):
        url = reverse('radicar_incidencia_ajax')
        antes = Publicacion.objects.count()
        d = self._json(url, {
            'titulo': 'Reporte',
            'categoria': 'VIAS',
            'contenido': 'el alcalde es un gonorrea malparido',
            'ubicacion': 'Calle 10, El Poblado',
            'latitud': '6.2090000', 'longitud': '-75.5700000', 'ubicacion_fijada': '1',
        }, status=400)
        self.assertEqual(d['status'], 'error')
        self.assertIn('inapropiada', d['message'].lower())
        self.assertEqual(Publicacion.objects.count(), antes, 'No debe guardarse la publicación rechazada.')

    # ── 3. Comentario con lenguaje permitido se guarda ──
    def test_comentario_limpio_se_guarda(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        d = self._json(url, {'texto': 'Gracias por reportar, muy útil'}, status=200)
        self.assertEqual(d['status'], 'ok')

    # ── 4. Comentario con lenguaje inapropiado se rechaza ──
    def test_comentario_inapropiado_se_rechaza(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        total_antes = self.pub.comentarios.count()
        d = self._json(url, {'texto': 'no sea pendejo'}, status=400)
        self.assertEqual(d['status'], 'error')
        self.assertEqual(self.pub.comentarios.count(), total_antes, 'No debe guardarse el comentario rechazado.')

    # ── 5. Edición: también se valida al editar ──
    def test_editar_publicacion_valida(self):
        url = reverse('editar_publicacion_ajax', args=[self.pub.id])
        # Edición válida
        d = self._json(url, {'titulo': 'Título corregido', 'contenido': 'Descripción válida'}, status=200)
        self.assertEqual(d['status'], 'ok')
        # Edición con groseria -> rechazada y sin persistir
        d = self._json(url, {'titulo': 'Título', 'contenido': 'eres un hijueputa'}, status=400)
        self.pub.refresh_from_db()
        self.assertNotIn('hijueputa', self.pub.contenido.lower())

    def test_editar_comentario_valida(self):
        # Comentario propio del ciudadano (puede editarlo).
        propio = Comentario.objects.create(
            publicacion=self.pub, autor=self.ciudadano,
            autor_nombre=self.ciudadano.username, texto='Comentario inicial',
        )
        url = reverse('editar_comentario_ajax', args=[propio.id])
        d = self._json(url, {'texto': 'Comentario corregido y limpio'}, status=200)
        self.assertEqual(d['status'], 'ok')
        d = self._json(url, {'texto': 'malparido'}, status=400)
        propio.refresh_from_db()
        self.assertNotEqual(propio.texto, 'malparido')

    # ── 6. Las rutas AJAX conservan su formato esperado ──
    def test_formato_respuesta_ajax(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        d = self._json(url, {'texto': 'coño'}, status=400)
        self.assertIn('status', d)
        self.assertIn('message', d)
        self.assertEqual(d['status'], 'error')


class PresenciaYCiudadanosTest(BaseUrbanReportTest):
    """
    Módulo "Ciudadanos registrados" del Panel (exclusivo para superusuarios,
    sin estado de actividad ni última sesión, con edición de nombre y dirección)
    + indicador de presencia en Feed/Perfil.
    """

    def setUp(self):
        from django.utils import timezone
        self.ahora = timezone.now()
        self.superadmin = Usuario.objects.create_user(
            username='superadmin_panel', email='superpanel@t.co', password='x',
            rol=Usuario.Rol.ADMINISTRADOR, is_staff=True, is_superuser=True,
            **PERFIL_COMPLETO,
        )

    def test_solo_superusuario_ve_seccion_ciudadanos_en_panel_sin_actividad(self):
        """
        El administrador normal NO ve el módulo de ciudadanos en el Panel.
        El superusuario SÍ ve 'Ciudadanos registrados', pero SIN última conexión
        ni estado en línea/inactivo.
        """
        # Admin normal (is_superuser=False) -> ve el Panel pero NO la tabla de ciudadanos
        self.client.force_login(self.admin)
        r_admin = self.client.get(reverse('panel_administrador'))
        self.assertEqual(r_admin.status_code, 200)
        html_admin = r_admin.content.decode()
        self.assertNotIn('ciudadanosTbody', html_admin)
        self.assertNotIn('Ciudadanos registrados', html_admin)

        # Superusuario (is_superuser=True) -> ve 'Ciudadanos registrados' sin actividad ni última sesión
        self.client.force_login(self.superadmin)
        r_super = self.client.get(reverse('panel_administrador'))
        self.assertEqual(r_super.status_code, 200)
        html_super = r_super.content.decode()
        self.assertIn('Ciudadanos registrados', html_super)
        self.assertIn('ciudadanosTbody', html_super)
        self.assertIn('@ciudadano', html_super)
        self.assertNotIn('Última conexión', html_super)
        self.assertNotIn('En línea', html_super)
        self.assertNotIn('Inactivo', html_super)

    def test_ciudadano_no_accede_al_panel(self):
        """Un ciudadano no puede ver el Panel (403), por tanto tampoco la tabla."""
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse('panel_administrador')).status_code, 403)

    def test_endpoint_ciudadanos_solo_superusuario_y_sin_datos_sesion(self):
        """El endpoint JSON de ciudadanos en el Panel es exclusivo de superusuarios y no expone actividad."""
        # Ciudadano -> 403
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse('api_presencia_ciudadanos')).status_code, 403)
        # Admin normal (no superusuario) -> 403
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('api_presencia_ciudadanos')).status_code, 403)
        # Superusuario -> 200 con datos de registro pero SIN en_linea ni ultima_rel/ultima_abs
        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('api_presencia_ciudadanos'))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['status'], 'ok')
        self.assertNotIn('en_linea_count', d)
        fila = next(c for c in d['ciudadanos'] if c['username'] == 'ciudadano')
        self.assertNotIn('en_linea', fila)
        self.assertNotIn('ultima_rel', fila)
        self.assertNotIn('ultima_abs', fila)

    def test_superusuario_edita_nombre_y_direcciones_de_ciudadano(self):
        """Solo un superusuario puede editar el nombre y las direcciones de un ciudadano registrado."""
        url = reverse('editar_ciudadano_panel_ajax', args=[self.ciudadano.id])

        # Ciudadano -> 403
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.post(url, {'nombre': 'Nuevo Nombre', 'direccion': 'Cra 10 #20-30'}).status_code, 403)

        # Admin normal -> 403
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url, {'nombre': 'Nuevo Nombre', 'direccion': 'Cra 10 #20-30'}).status_code, 403)

        # Superusuario -> 200 y actualiza nombre y direcciones en BD
        self.client.force_login(self.superadmin)
        r = self.client.post(url, {
            'nombre': 'Carlos Andrés Pérez',
            'direccion': 'Circular 4 # 70-12',
            'barrio_vereda': 'Laureles',
            'numero_finca': '45B',
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['ciudadano']['nombre'], 'Carlos Andrés Pérez')
        self.assertEqual(data['ciudadano']['direccion'], 'Circular 4 # 70-12')
        self.assertEqual(data['ciudadano']['barrio_vereda'], 'Laureles')
        self.assertEqual(data['ciudadano']['numero_finca'], '45B')

        self.ciudadano.refresh_from_db()
        self.assertEqual(self.ciudadano.first_name, 'Carlos')
        self.assertEqual(self.ciudadano.last_name, 'Andrés Pérez')
        self.assertEqual(self.ciudadano.direccion, 'Circular 4 # 70-12')
        self.assertEqual(self.ciudadano.barrio_vereda, 'Laureles')
        self.assertEqual(self.ciudadano.numero_finca, '45B')

        # Validación: rechaza dirección vacía o nombre inapropiado
        r_vacio = self.client.post(url, {'nombre': 'Carlos Pérez', 'direccion': '   '})
        self.assertEqual(r_vacio.status_code, 400)
        r_groseria = self.client.post(url, {'nombre': 'malparido', 'direccion': 'Circular 4 # 70-12'})
        self.assertEqual(r_groseria.status_code, 400)

    def test_direccion_real_o_no_registrada(self):
        """La columna Dirección muestra el campo real; si está vacío, 'No registrada'."""
        from feed.views import _listar_ciudadanos_presencia
        self.ciudadano.direccion = 'Calle 123 # 45-67'
        self.ciudadano.save(update_fields=['direccion'])
        sin_dir = Usuario.objects.create_user(
            username='sindir', email='sindir@t.co', password='x', rol=Usuario.Rol.CIUDADANO,
        )
        sin_dir.direccion = ''
        sin_dir.save(update_fields=['direccion'])

        filas = {c['username']: c for c in _listar_ciudadanos_presencia()}
        self.assertEqual(filas['ciudadano']['direccion'], 'Calle 123 # 45-67')
        self.assertEqual(filas['sindir']['direccion'], 'No registrada')

    def test_barrio_y_numero_finca_en_tabla(self):
        """La fila incluye barrio/vereda y número de finca según lo registrado."""
        from feed.views import _listar_ciudadanos_presencia
        self.ciudadano.barrio_vereda = 'Laureles'
        self.ciudadano.numero_finca = '12'
        self.ciudadano.save(update_fields=['barrio_vereda', 'numero_finca'])
        sin_finca = Usuario.objects.create_user(
            username='sinfinca', email='sf@t.co', password='x', rol=Usuario.Rol.CIUDADANO,
        )
        sin_finca.barrio_vereda = 'Belén'
        sin_finca.numero_finca = ''
        sin_finca.save(update_fields=['barrio_vereda', 'numero_finca'])

        filas = {c['username']: c for c in _listar_ciudadanos_presencia()}
        self.assertEqual(filas['ciudadano']['barrio_vereda'], 'Laureles')
        self.assertEqual(filas['ciudadano']['numero_finca'], '12')
        self.assertEqual(filas['sinfinca']['barrio_vereda'], 'Belén')
        self.assertEqual(filas['sinfinca']['numero_finca'], '')

    def test_calculo_actividad_en_linea_e_inactivo(self):
        """esta_en_linea(): activo dentro de la ventana, inactivo fuera; sin registro = inactivo."""
        from datetime import timedelta
        self.ciudadano.last_login = self.ahora - timedelta(seconds=30)
        self.ciudadano.save(update_fields=['last_login'])
        self.assertTrue(self.ciudadano.esta_en_linea())
        self.ciudadano.last_login = self.ahora - timedelta(minutes=5)
        self.ciudadano.save(update_fields=['last_login'])
        self.assertFalse(self.ciudadano.esta_en_linea())
        self.ciudadano.last_login = None
        self.ciudadano.save(update_fields=['last_login'])
        self.assertFalse(self.ciudadano.esta_en_linea())

    def test_busqueda_ciudadanos_por_nombre_y_correo(self):
        """El filtro de la tabla encuentra por nombre de perfil, usuario o correo."""
        from feed.views import _listar_ciudadanos_presencia
        r = _listar_ciudadanos_presencia(busqueda='ciudadano')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        r = _listar_ciudadanos_presencia(busqueda='c@test.co')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        r = _listar_ciudadanos_presencia(busqueda='Ciu')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        self.assertEqual(_listar_ciudadanos_presencia(busqueda='zzzznoexiste'), [])

    def test_endpoint_presencia_acepta_busqueda(self):
        """El endpoint superadmin filtra por el parámetro q."""
        self.client.force_login(self.superadmin)
        r = self.client.get(reverse('api_presencia_ciudadanos') + '?q=ciudadano')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(all('ciudadano' in c['username'].lower()
                            or 'ciudadano' in c['nombre'].lower() for c in d['ciudadanos']))

    def test_estado_presencia_por_usuario_exige_seguimiento_mutuo_y_preferencia_activa(self):
        """
        El punto verde solo es visible entre personas que se siguen mutuamente
        y cuando ambas tienen `mostrar_estado_actividad=True` (estilo Instagram/Facebook).
        """
        from datetime import timedelta
        from usuarios.models import Seguimiento
        self.client.force_login(self.ciudadano)
        Usuario.objects.filter(pk=self.otro.pk).update(last_login=self.ahora - timedelta(seconds=10))

        Seguimiento.objects.filter(
            seguidor__in=[self.ciudadano, self.otro],
            seguido__in=[self.ciudadano, self.otro],
        ).delete()

        # 1. Sin seguimiento mutuo -> en_linea es False aunque esté activo
        d_sin_seguir = self.client.get(reverse('api_estado_presencia', args=['otro'])).json()
        self.assertFalse(d_sin_seguir['en_linea'])

        # 2. Seguimiento en una sola dirección -> sigue siendo False
        Seguimiento.objects.create(seguidor=self.ciudadano, seguido=self.otro)
        d_unilateral = self.client.get(reverse('api_estado_presencia', args=['otro'])).json()
        self.assertFalse(d_unilateral['en_linea'])

        # 3. Seguimiento mutuo -> ahora SÍ es True
        Seguimiento.objects.create(seguidor=self.otro, seguido=self.ciudadano)
        r = self.client.get(reverse('api_estado_presencia', args=['otro']))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['en_linea'])
        self.assertEqual(set(d.keys()), {'status', 'en_linea'})

        # 4. Si el otro usuario desactiva su estado de actividad -> False
        Usuario.objects.filter(pk=self.otro.pk).update(mostrar_estado_actividad=False)
        self.assertFalse(self.client.get(reverse('api_estado_presencia', args=['otro'])).json()['en_linea'])
        Usuario.objects.filter(pk=self.otro.pk).update(mostrar_estado_actividad=True)

        # 5. Reciprocidad: si quien mira desactiva su propio estado de actividad -> tampoco ve el del otro
        Usuario.objects.filter(pk=self.ciudadano.pk).update(mostrar_estado_actividad=False)
        self.assertFalse(self.client.get(reverse('api_estado_presencia', args=['otro'])).json()['en_linea'])
        Usuario.objects.filter(pk=self.ciudadano.pk).update(mostrar_estado_actividad=True)

        # 6. Fuera de línea por tiempo -> False
        Usuario.objects.filter(pk=self.otro.pk).update(last_login=self.ahora - timedelta(minutes=10))
        d = self.client.get(reverse('api_estado_presencia', args=['otro'])).json()
        self.assertFalse(d['en_linea'])
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse('api_estado_presencia', args=['otro'])).status_code, 200)

    def test_heartbeat_marca_actividad_y_requiere_login(self):
        """El heartbeat actualiza la actividad del propio usuario; exige sesión y POST."""
        from datetime import timedelta
        self.assertNotEqual(self.client.post(reverse('api_heartbeat')).status_code, 200)
        self.client.force_login(self.ciudadano)
        viejo = self.ahora - timedelta(hours=3)
        Usuario.objects.filter(pk=self.ciudadano.pk).update(last_login=viejo)
        r = self.client.post(reverse('api_heartbeat'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')
        refrescado = Usuario.objects.get(pk=self.ciudadano.pk).last_login
        self.assertGreater(refrescado, viejo)
        self.assertEqual(self.client.get(reverse('api_heartbeat')).status_code, 405)

    def test_tiempo_relativo_y_sin_registro(self):
        """_tiempo_relativo cubre 'Ahora mismo', minutos/horas/días y 'Sin registro'."""
        from datetime import timedelta
        from feed.views import _tiempo_relativo
        self.assertEqual(_tiempo_relativo(None), 'Sin registro')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(seconds=10), self.ahora), 'Ahora mismo')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(minutes=5), self.ahora), 'Hace 5 min')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(hours=1), self.ahora), 'Hace 1 h')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(days=4), self.ahora), 'Hace 4 d')

    def test_middleware_actualiza_actividad(self):
        """Una solicitud autenticada refresca last_login del usuario (throttle 30s)."""
        from datetime import timedelta
        self.client.force_login(self.ciudadano)
        viejo = self.ahora - timedelta(hours=3)
        Usuario.objects.filter(pk=self.ciudadano.pk).update(last_login=viejo)
        self.client.get(reverse('feed_comunitario'))
        self.assertGreater(Usuario.objects.get(pk=self.ciudadano.pk).last_login, viejo)

    def test_indicador_presencia_en_feed_por_estado(self):
        """El círculo verde aparece en el feed solo si hay seguimiento mutuo, preferencia activa y está en línea."""
        from datetime import timedelta
        from usuarios.models import Seguimiento
        espectador = Usuario.objects.create_user(
            username='espectador', email='esp@t.co', password='x',
            rol=Usuario.Rol.ADMINISTRADOR, **PERFIL_COMPLETO,
        )
        self.client.force_login(espectador)

        def poner_todos_inactivos():
            Usuario.objects.exclude(pk=espectador.pk).update(
                last_login=self.ahora - timedelta(hours=2)
            )

        poner_todos_inactivos()
        Usuario.objects.filter(pk=self.ciudadano.pk).update(
            last_login=self.ahora - timedelta(seconds=30)
        )
        # Sin seguimiento mutuo -> NO aparece el punto verde
        html_sin_mutuo = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('presence-dot', html_sin_mutuo)

        # Con seguimiento mutuo -> SÍ aparece el punto verde
        Seguimiento.objects.create(seguidor=espectador, seguido=self.ciudadano)
        Seguimiento.objects.create(seguidor=self.ciudadano, seguido=espectador)
        html = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertIn('presence-dot', html)

        poner_todos_inactivos()
        html2 = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('presence-dot', html2)

    def test_menciones_en_publicaciones_y_comentarios(self):
        """Mencionar con @username en publicaciones y comentarios crea enlace al perfil y notifica al usuario."""
        self.client.force_login(self.ciudadano)

        # 1. Endpoint de autocompletado de menciones
        r_sug = self.client.get(reverse('api_sugerir_menciones') + '?q=otr')
        self.assertEqual(r_sug.status_code, 200)
        sug_data = r_sug.json()
        self.assertEqual(sug_data['status'], 'ok')
        self.assertTrue(any(u['username'] == 'otro' for u in sug_data['usuarios']))

        # 2. Mención en comentario notifica al usuario mencionado (tercero) con tipo MENCION
        tercero = Usuario.objects.create_user(
            username='carlos_m', email='carlos@t.co', password='x', **PERFIL_COMPLETO
        )
        r_com = self.client.post(
            reverse('agregar_comentario_ajax', args=[self.pub.id]),
            {'texto': 'Hola @carlos_m revisa este reporte por favor (correo@test.co)'},
        )
        self.assertEqual(r_com.status_code, 200)
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=tercero,
                actor=self.ciudadano,
                tipo=Notificacion.Tipo.MENCION,
            ).exists()
        )

        # 3. Mención al autor de la publicación en comentario: debe recibir notificación MENCION
        # (no solo COMENTARIO genérico)
        self.client.force_login(tercero)
        r_com2 = self.client.post(
            reverse('agregar_comentario_ajax', args=[self.pub.id]),
            {'texto': f'Oye @{self.ciudadano.username} qué opinas de esto?'},
        )
        self.assertEqual(r_com2.status_code, 200)
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=self.ciudadano,
                actor=tercero,
                tipo=Notificacion.Tipo.MENCION,
            ).exists()
        )

        # 4. Mención al editar comentario: debe crear notificación MENCION al nuevo usuario nombrado
        cuarto = Usuario.objects.create_user(
            username='diana_p', email='diana@t.co', password='x', **PERFIL_COMPLETO
        )
        com_id = r_com2.json()['comentario']['id']
        r_edit_com = self.client.post(
            reverse('editar_comentario_ajax', args=[com_id]),
            {'texto': 'Actualizado con mención a @diana_p'},
        )
        self.assertEqual(r_edit_com.status_code, 200)
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=cuarto,
                actor=tercero,
                tipo=Notificacion.Tipo.MENCION,
            ).exists()
        )

        # 5. Mención al editar publicación: notifica al usuario nombrado
        self.client.force_login(self.ciudadano)
        r_edit_pub = self.client.post(
            reverse('editar_publicacion_ajax', args=[self.pub.id]),
            {'titulo': 'Incidencia actualizada', 'contenido': 'Mencionando a @diana_p en el reporte', 'categoria': 'VIAS'},
        )
        self.assertEqual(r_edit_pub.status_code, 200)
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=cuarto,
                actor=self.ciudadano,
                tipo=Notificacion.Tipo.MENCION,
            ).exists()
        )

        # 6. Verificar que en el HTML se renderiza el enlace @carlos_m pero NO @test.co del correo
        html_det = self.client.get(reverse('detalle_publicacion', args=[self.pub.id])).content.decode()
        self.assertIn('href="/perfil/carlos_m/"', html_det)
        self.assertNotIn('href="/perfil/test.co/"', html_det)

        # 7. Sidebar incluye enlace y badge de notificaciones
        html_feed = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertIn('id="sidebarNotifBadge"', html_feed)

    def test_sidebar_avisa_otras_notificaciones(self):
        """El sidebar y la API avisan no solo menciones sino también otras notificaciones (likes, comentarios, estados)."""
        self.client.force_login(self.ciudadano)
        
        # 1. Al inicio, sin notificaciones no leídas
        r_api = self.client.get(reverse('api_notificaciones_no_leidas'))
        self.assertEqual(r_api.status_code, 200)
        self.assertEqual(r_api.json()['total_no_leidas'], 0)

        # 2. Generar otra notificación: un usuario nuevo da LIKE a publicación de self.ciudadano
        fan = Usuario.objects.create_user(
            username='fan_1', email='fan@test.co', password='x', **PERFIL_COMPLETO
        )
        self.client.force_login(fan)
        self.client.post(reverse('reaccionar_publicacion_ajax', args=[self.pub.id]), {'tipo': 'LIKE'})

        # 3. self.ciudadano consulta API y verifica que el badge y ultima_notificacion avisan del LIKE
        self.client.force_login(self.ciudadano)
        r_api2 = self.client.get(reverse('api_notificaciones_no_leidas'))
        data = r_api2.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['total_no_leidas'], 1)
        self.assertIsNotNone(data['ultima_notificacion'])
        self.assertEqual(data['ultima_notificacion']['tipo'], 'LIKE')

        # 4. En el HTML de cualquier vista (ej. mapa o feed), el badge del sidebar ya se renderiza
        html_mapa = self.client.get(reverse('mapa')).content.decode()
        self.assertIn('id="sidebarNotifBadge"', html_mapa)
        self.assertIn('id="mobileNavBadge"', html_mapa)

    def test_mapa_limite_20_por_estado_y_busqueda(self):
        """
        El mapa solo debe mostrar hasta 20 incidencias resueltas, 20 en revisión y 20 pendientes.
        No debe mostrar declinadas ni censuradas.
        La búsqueda permite encontrar incidencias específicas que salieron de la cola de 20.
        """
        self.client.force_login(self.ciudadano)

        # 1. Crear 25 incidencias de cada estado permitido (75 en total)
        for i in range(25):
            Publicacion.objects.create(
                autor=self.ciudadano,
                titulo=f'Reportado {i}',
                contenido=f'Contenido pendiente {i}',
                categoria='VIAS',
                latitud=6.24 + (i * 0.001),
                longitud=-75.58 + (i * 0.001),
                estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
            )
            Publicacion.objects.create(
                autor=self.ciudadano,
                titulo=f'EnProceso {i}',
                contenido=f'Contenido en proceso {i}',
                categoria='VIAS',
                latitud=6.24 + (i * 0.001),
                longitud=-75.58 + (i * 0.001),
                estado_incidencia=Publicacion.EstadoIncidencia.EN_PROCESO,
            )
            Publicacion.objects.create(
                autor=self.ciudadano,
                titulo=f'Resuelta {i}',
                contenido=f'Contenido resuelta {i}',
                categoria='VIAS',
                latitud=6.24 + (i * 0.001),
                longitud=-75.58 + (i * 0.001),
                estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA,
            )

        # Crear incidencias declinadas y censuradas (no deben salir NUNCA)
        pub_declinada = Publicacion.objects.create(
            autor=self.ciudadano,
            titulo='Incidencia Declinada Especial',
            contenido='No debe mostrarse',
            categoria='VIAS',
            latitud=6.25,
            longitud=-75.58,
            estado_incidencia=Publicacion.EstadoIncidencia.DECLINADO,
        )
        pub_censurada = Publicacion.objects.create(
            autor=self.ciudadano,
            titulo='Incidencia Censurada Especial',
            contenido='Tampoco debe mostrarse',
            categoria='VIAS',
            latitud=6.25,
            longitud=-75.58,
            estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
            censurado=True,
        )

        # Incidencia antigua con texto único que sale de la cola base de 20 (Reportado 0 es la más antigua)
        inc_antigua = Publicacion.objects.filter(
            estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
            censurado=False,
            latitud__isnull=False,
        ).order_by('fecha_creacion').first()
        inc_antigua.titulo = 'Bache historico en Guayabal'
        inc_antigua.save(update_fields=['titulo'])

        # 2. Consultar mapa base (sin búsqueda)
        r_base = self.client.get(reverse('api_incidentes_mapa'))
        self.assertEqual(r_base.status_code, 200)
        base_data = r_base.json()
        base_ids = [inc['id'] for inc in base_data['incidentes']]

        # Verificar que ni declinada ni censurada están en el mapa base
        self.assertNotIn(pub_declinada.id, base_ids)
        self.assertNotIn(pub_censurada.id, base_ids)

        # Contar por cada estado en el mapa base: máximo 20 por estado
        conteo_reportado = sum(1 for inc in base_data['incidentes'] if inc['estado'] == 'REPORTADO')
        conteo_en_proceso = sum(1 for inc in base_data['incidentes'] if inc['estado'] == 'EN_PROCESO')
        conteo_resuelta = sum(1 for inc in base_data['incidentes'] if inc['estado'] == 'RESUELTA')

        self.assertLessEqual(conteo_reportado, 20)
        self.assertLessEqual(conteo_en_proceso, 20)
        self.assertLessEqual(conteo_resuelta, 20)

        # La incidencia más antigua salió de la cola base de 20
        self.assertNotIn(inc_antigua.id, base_ids)

        # 3. Consultar filtro de solo RESUELTA: máx 20
        r_resueltas = self.client.get(reverse('api_incidentes_mapa') + '?estado=RESUELTA')
        self.assertEqual(r_resueltas.status_code, 200)
        resueltas_data = r_resueltas.json()
        self.assertEqual(len(resueltas_data['incidentes']), 20)
        self.assertTrue(all(inc['estado'] == 'RESUELTA' for inc in resueltas_data['incidentes']))

        # 4. Búsqueda explícita de la incidencia antigua por texto: la encuentra fuera de la cola de 20
        r_search = self.client.get(reverse('api_incidentes_mapa') + '?q=Guayabal')
        self.assertEqual(r_search.status_code, 200)
        search_ids = [inc['id'] for inc in r_search.json()['incidentes']]
        self.assertIn(inc_antigua.id, search_ids)

        # 5. Búsqueda directa por ID específico (?incidente_id=)
        r_id = self.client.get(reverse('api_incidentes_mapa') + f'?incidente_id={inc_antigua.id}')
        self.assertEqual(r_id.status_code, 200)
        id_results = r_id.json()['incidentes']
        self.assertEqual(len(id_results), 1)
        self.assertEqual(id_results[0]['id'], inc_antigua.id)

        # 6. Intentar buscar incidencia declinada o censurada: NUNCA se devuelven
        r_search_dec = self.client.get(reverse('api_incidentes_mapa') + '?q=Declinada')
        self.assertEqual(len(r_search_dec.json()['incidentes']), 0)

        r_search_cen = self.client.get(reverse('api_incidentes_mapa') + '?q=Censurada')
        self.assertEqual(len(r_search_cen.json()['incidentes']), 0)

    def test_direccion_no_se_expone_en_feed(self):
        """La dirección de residencia no debe aparecer en el feed."""
        self.ciudadano.direccion = 'Calle Secreta 999'
        self.ciudadano.save(update_fields=['direccion'])
        self.client.force_login(self.ciudadano)
        html = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('Calle Secreta 999', html)


class ComentariosConImagenTest(BaseUrbanReportTest):
    """Pruebas de creación, validación y censura de comentarios y respuestas con imágenes."""

    def setUp(self):
        self.client.force_login(self.otro)

    @staticmethod
    def _crear_png_prueba( nombre='evidencia.png'):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = BytesIO()
        img = Image.new('RGB', (64, 64), color=(30, 144, 255))
        img.save(buf, format='PNG')
        buf.seek(0)
        return SimpleUploadedFile(nombre, buf.read(), content_type='image/png')

    def test_comentario_con_texto_e_imagen(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        r = self.client.post(url, {
            'texto': 'Adjunto evidencia del estado actual',
            'imagen': self._crear_png_prueba(),
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['comentario']['imagen_url'])
        com = Comentario.objects.get(id=data['comentario']['id'])
        self.assertTrue(bool(com.imagen))
        if com.imagen:
            com.imagen.delete(save=False)

    def test_comentario_solo_imagen_sin_texto(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        r = self.client.post(url, {
            'texto': '',
            'imagen': self._crear_png_prueba('solo_foto.png'),
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['comentario']['texto'], '')
        self.assertTrue(data['comentario']['imagen_url'])
        com = Comentario.objects.get(id=data['comentario']['id'])
        notif = Notificacion.objects.filter(comentario=com).first()
        self.assertIsNotNone(notif)
        self.assertIn('Imagen adjunta', notif.extra)
        if com.imagen:
            com.imagen.delete(save=False)

    def test_respuesta_anidada_con_imagen(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        r = self.client.post(url, {
            'texto': 'Respuesta con foto',
            'padre_id': self.comentario.id,
            'imagen': self._crear_png_prueba('respuesta.png'),
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['comentario']['padre_id'], self.comentario.id)
        self.assertTrue(data['comentario']['imagen_url'])
        com = Comentario.objects.get(id=data['comentario']['id'])
        if com.imagen:
            com.imagen.delete(save=False)

    def test_comentario_vacio_sin_imagen_se_rechaza(self):
        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        r = self.client.post(url, {'texto': '   '})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['status'], 'error')

    def test_comentario_con_archivo_invalido_se_rechaza(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = reverse('agregar_comentario_ajax', args=[self.pub.id])
        archivo_falso = SimpleUploadedFile('malicioso.png', b'no es una imagen real', content_type='image/png')
        r = self.client.post(url, {'texto': 'Intento inválido', 'imagen': archivo_falso})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['status'], 'error')

    def test_comentario_con_imagen_censurado_renderiza_escudo(self):
        com = Comentario.objects.create(
            publicacion=self.pub,
            autor=self.otro,
            autor_nombre=self.otro.username,
            texto='Foto censurada',
            imagen=self._crear_png_prueba('censurada.png'),
            censurado=True,
        )
        try:
            r = self.client.get(reverse('detalle_publicacion', args=[self.pub.id]))
            self.assertEqual(r.status_code, 200)
            html = r.content.decode()
            self.assertIn(f'id="comment-media-{com.id}"', html)
            self.assertIn('censor-comment-shield', html)
        finally:
            if com.imagen:
                com.imagen.delete(save=False)


class RendimientoTest(TestCase):
    """El número de consultas no debe crecer con la cantidad de publicaciones (sin N+1)."""

    @classmethod
    def setUpTestData(cls):
        cls.u = Usuario.objects.create_user(username='u', email='u@t.co', password='x', **PERFIL_COMPLETO)
        cls.admin = Usuario.objects.create_user(
            username='admin_perf', email='ap@t.co', password='x',
            rol=Usuario.Rol.ADMINISTRADOR, **PERFIL_COMPLETO,
        )
        cls.o1 = Usuario.objects.create_user(username='o1', email='o1@t.co', password='x', **PERFIL_COMPLETO)
        cls.o2 = Usuario.objects.create_user(username='o2', email='o2@t.co', password='x', **PERFIL_COMPLETO)

    def _contar(self, url, user=None):
        self.client.force_login(user or self.u)
        # Petición de "calentamiento": deja que el middleware refresque last_login
        # y quede throttled, para que la medición real no incluya esa escritura
        # puntual O(1) y siga detectando cualquier N+1.
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return ctx.captured_queries

    def _assert_constante(self, url, user=None):
        crear_publicaciones(self.u, [self.o1, self.o2], 2)
        q_pocas = self._contar(url, user=user)
        pocas = len(q_pocas)
        crear_publicaciones(self.u, [self.o1, self.o2], 8)
        q_muchas = self._contar(url, user=user)
        muchas = len(q_muchas)
        print(f'\n  {url}: {pocas} consultas (2 pubs) -> {muchas} consultas (10 pubs)')
        if pocas != muchas:
            print("--- QUERIES IN POCAS ---")
            for i, q in enumerate(q_pocas):
                print(f"[{i}] {q['sql']}")
            print("--- QUERIES IN MUCHAS ---")
            for i, q in enumerate(q_muchas):
                print(f"[{i}] {q['sql']}")
        self.assertEqual(pocas, muchas, f'N+1 en {url}: {pocas} -> {muchas}')

    def test_feed_sin_n_mas_1(self):
        self._assert_constante(reverse('feed_comunitario'))

    def test_perfil_sin_n_mas_1(self):
        self._assert_constante(reverse('perfil'))

    def test_mapa_api_sin_n_mas_1(self):
        self._assert_constante(reverse('api_incidentes_mapa'))

    def test_busqueda_sin_n_mas_1(self):
        self._assert_constante(reverse('api_buscar_publicaciones') + '?q=reporte')

    def test_estadisticas_y_panel_admin_sin_n_mas_1(self):
        """Estadísticas y Panel Admin deben mantener un número constante y reducido de consultas."""
        self._assert_constante(reverse('estadisticas'), user=self.admin)
        queries_panel = self._contar(reverse('panel_administrador'), user=self.admin)
        self.assertLessEqual(len(queries_panel), 10)

    def test_lista_seguidores_sin_n_mas_1(self):
        """La lista de seguidores no debe ejecutar una consulta extra por cada seguidor."""
        from usuarios.models import Seguimiento
        Seg = [
            Usuario.objects.create_user(username=f'seg_{i}', email=f's{i}@t.co', password='x', **PERFIL_COMPLETO)
            for i in range(6)
        ]
        for s in Seg[:2]:
            Seguimiento.objects.create(seguidor=s, seguido=self.u)
        q_2 = len(self._contar(reverse('lista_seguidores', args=[self.u.username])))
        for s in Seg[2:]:
            Seguimiento.objects.create(seguidor=s, seguido=self.u)
        q_6 = len(self._contar(reverse('lista_seguidores', args=[self.u.username])))
        self.assertEqual(q_2, q_6)


class TerminosServicioTests(TestCase):
    """Pruebas para la vista de Términos de Servicio, Ley Colombiana, ISO/IEC 25010, Render y Supabase."""

    def setUp(self):
        self.user = Usuario.objects.create_user(
            username='ciudadano_tos',
            email='tos@test.com',
            password='Password123',
            **PERFIL_COMPLETO,
        )

    def test_terminos_accesible_publicamente_sin_login(self):
        """Cualquier visitante desde Login/Registro puede consultar los Términos de Servicio."""
        url = reverse('terminos_servicio')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['base_template'], 'layouts/public_doc_base.html')
        html = res.content.decode('utf-8')
        self.assertIn('Ley Estatutaria 1581 de 2012', html)
        self.assertIn('Ley 1273 de 2009', html)
        self.assertIn('Ley 527 de 1999', html)
        self.assertIn('ISO/IEC 25010', html)
        self.assertIn('Adecuación Funcional', html)
        self.assertIn('Eficiencia de Desempeño', html)
        self.assertIn('Render', html)
        self.assertIn('Supabase', html)

    def test_terminos_en_modo_portal_para_usuario_autenticado(self):
        """Un usuario autenticado con perfil completo ve los Términos integrados en el portal."""
        self.client.force_login(self.user)
        res = self.client.get(reverse('terminos_servicio'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['base_template'], 'layouts/portal_base.html')
        self.assertTrue(res.context['mostrar_menu_portal'])

    def test_terminos_accesible_con_perfil_incompleto_y_mantenimiento(self):
        """Ni el perfil incompleto ni el modo mantenimiento bloquean la lectura de los Términos."""
        from usuarios.models import ConfiguracionSistema
        incompleto = Usuario.objects.create_user(
            username='sso_incompleto',
            email='incompleto@test.com',
            password='Password123',
        )
        self.client.force_login(incompleto)
        res1 = self.client.get(reverse('terminos_servicio'))
        self.assertEqual(res1.status_code, 200)

        cfg = ConfiguracionSistema.obtener()
        cfg.modo_mantenimiento = True
        cfg.save()
        res2 = self.client.get(reverse('terminos_servicio'))
        self.assertEqual(res2.status_code, 200)

    def test_enlaces_terminos_en_login_y_registro(self):
        """Las páginas de login y registro enlazan a la ruta real de Términos de Servicio."""
        url_tos = reverse('terminos_servicio')
        res_login = self.client.get(reverse('login'))
        res_reg = self.client.get(reverse('registro'))
        self.assertContains(res_login, url_tos)
        self.assertContains(res_reg, url_tos)

