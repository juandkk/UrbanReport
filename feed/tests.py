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
            'titulo': 'Bache en El Poblado',
            'categoria': 'REDES',
            'contenido': 'Caja de telecomunicaciones sin tapa',
            'ubicacion': 'Calle 10, El Poblado',
            'latitud': '6.2090000',
            'longitud': '-75.5700000',
            'ubicacion_fijada': '1',
        }, status=200)
        self.assertEqual(d['incidente']['categoria'], 'REDES')

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
    Sección "Ciudadanos activos" del Panel + indicador de presencia.
    Verifica acceso por rol, dirección, cálculo de actividad y privacidad.
    """

    def setUp(self):
        from django.utils import timezone
        self.ahora = timezone.now()

    def test_admin_ve_seccion_ciudadanos_en_panel(self):
        """El administrador ve la sección 'Ciudadanos activos' dentro del Panel."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse('panel_administrador'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Ciudadanos activos', html)
        self.assertIn('ciudadanosTbody', html)
        # La tabla usa usuarios REALES: aparece el ciudadano de prueba.
        self.assertIn('@ciudadano', html)

    def test_ciudadano_no_accede_al_panel(self):
        """Un ciudadano no puede ver el Panel (403), por tanto tampoco la tabla."""
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse('panel_administrador')).status_code, 403)

    def test_endpoint_presencia_solo_admin(self):
        """El endpoint JSON de presencia es exclusivo de administradores."""
        # Ciudadano -> 403, sin datos
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse('api_presencia_ciudadanos')).status_code, 403)
        # Admin -> 200 con datos
        self.client.force_login(self.admin)
        r = self.client.get(reverse('api_presencia_ciudadanos'))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['status'], 'ok')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in d['ciudadanos']))

    def test_direccion_real_o_no_registrada(self):
        """La columna Dirección muestra el campo real; si está vacío, 'No registrada'."""
        from feed.views import _listar_ciudadanos_presencia
        # El ciudadano de prueba tiene direccion en PERFIL_COMPLETO.
        self.ciudadano.direccion = 'Calle 123 # 45-67'
        self.ciudadano.save(update_fields=['direccion'])
        # Un ciudadano sin dirección:
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
        # Con barrio y finca
        self.ciudadano.barrio_vereda = 'Laureles'
        self.ciudadano.numero_finca = '12'
        self.ciudadano.save(update_fields=['barrio_vereda', 'numero_finca'])
        # Con barrio pero SIN finca
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
        # Activo: actividad hace 30 segundos (dentro de la ventana de 60s)
        self.ciudadano.ultima_actividad = self.ahora - timedelta(seconds=30)
        self.ciudadano.save(update_fields=['ultima_actividad'])
        self.assertTrue(self.ciudadano.esta_en_linea())
        # Inactivo: actividad hace 5 minutos (fuera de la ventana de 60s)
        self.ciudadano.ultima_actividad = self.ahora - timedelta(minutes=5)
        self.ciudadano.save(update_fields=['ultima_actividad'])
        self.assertFalse(self.ciudadano.esta_en_linea())
        # Sin registro
        self.ciudadano.ultima_actividad = None
        self.ciudadano.save(update_fields=['ultima_actividad'])
        self.assertFalse(self.ciudadano.esta_en_linea())

    def test_busqueda_ciudadanos_por_nombre_y_correo(self):
        """El filtro de la tabla encuentra por nombre de perfil, usuario o correo."""
        from feed.views import _listar_ciudadanos_presencia
        # Por username
        r = _listar_ciudadanos_presencia(busqueda='ciudadano')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        # Por correo (el ciudadano tiene email c@test.co)
        r = _listar_ciudadanos_presencia(busqueda='c@test.co')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        # Por nombre (first_name 'Ciu')
        r = _listar_ciudadanos_presencia(busqueda='Ciu')
        self.assertTrue(any(c['username'] == 'ciudadano' for c in r))
        # Búsqueda sin coincidencias -> lista vacía
        self.assertEqual(_listar_ciudadanos_presencia(busqueda='zzzznoexiste'), [])

    def test_endpoint_presencia_acepta_busqueda(self):
        """El endpoint admin filtra por el parámetro q."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse('api_presencia_ciudadanos') + '?q=ciudadano')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(all('ciudadano' in c['username'].lower()
                            or 'ciudadano' in c['nombre'].lower() for c in d['ciudadanos']))

    def test_estado_presencia_por_usuario(self):
        """El endpoint de presencia individual devuelve solo el booleano en_linea."""
        from datetime import timedelta
        self.client.force_login(self.ciudadano)
        # En línea
        Usuario.objects.filter(pk=self.otro.pk).update(ultima_actividad=self.ahora - timedelta(seconds=10))
        r = self.client.get(reverse('api_estado_presencia', args=['otro']))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['en_linea'])
        # No debe exponer datos sensibles: solo status y en_linea
        self.assertEqual(set(d.keys()), {'status', 'en_linea'})
        # Fuera de línea
        Usuario.objects.filter(pk=self.otro.pk).update(ultima_actividad=self.ahora - timedelta(minutes=10))
        d = self.client.get(reverse('api_estado_presencia', args=['otro'])).json()
        self.assertFalse(d['en_linea'])
        # Requiere autenticación
        self.client.logout()
        self.assertNotEqual(self.client.get(reverse('api_estado_presencia', args=['otro'])).status_code, 200)

    def test_heartbeat_marca_actividad_y_requiere_login(self):
        """El heartbeat actualiza la actividad del propio usuario; exige sesión y POST."""
        # Sin sesión -> redirige a login (no 200)
        self.assertNotEqual(self.client.post(reverse('api_heartbeat')).status_code, 200)
        # Autenticado -> 200 y actualiza ultima_actividad
        Usuario.objects.filter(pk=self.ciudadano.pk).update(ultima_actividad=None)
        self.client.force_login(self.ciudadano)
        r = self.client.post(reverse('api_heartbeat'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')
        self.assertIsNotNone(Usuario.objects.get(pk=self.ciudadano.pk).ultima_actividad)
        # El heartbeat no acepta GET
        self.assertEqual(self.client.get(reverse('api_heartbeat')).status_code, 405)

    def test_tiempo_relativo_y_sin_registro(self):
        """_tiempo_relativo cubre 'Ahora mismo', minutos/horas/días y 'Sin registro'."""
        from datetime import timedelta
        from feed.views import _tiempo_relativo, _listar_ciudadanos_presencia
        self.assertEqual(_tiempo_relativo(None), 'Sin registro')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(seconds=10), self.ahora), 'Ahora mismo')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(minutes=5), self.ahora), 'Hace 5 min')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(hours=1), self.ahora), 'Hace 1 h')
        self.assertEqual(_tiempo_relativo(self.ahora - timedelta(days=4), self.ahora), 'Hace 4 d')
        # Usuario sin actividad -> 'Sin registro' en la tabla, sin fecha absoluta.
        self.ciudadano.ultima_actividad = None
        self.ciudadano.save(update_fields=['ultima_actividad'])
        fila = next(c for c in _listar_ciudadanos_presencia() if c['username'] == 'ciudadano')
        self.assertEqual(fila['ultima_rel'], 'Sin registro')
        self.assertEqual(fila['ultima_abs'], '')

    def test_middleware_actualiza_actividad(self):
        """Una solicitud autenticada registra ultima_actividad del usuario."""
        self.assertIsNone(Usuario.objects.get(pk=self.ciudadano.pk).ultima_actividad)
        self.client.force_login(self.ciudadano)
        self.client.get(reverse('feed_comunitario'))
        self.assertIsNotNone(Usuario.objects.get(pk=self.ciudadano.pk).ultima_actividad)

    def test_indicador_presencia_en_feed_por_estado(self):
        """El círculo verde aparece si el autor está en línea y desaparece si no."""
        from datetime import timedelta
        # Autor del post (ciudadano) EN LÍNEA -> aparece el dot.
        self.ciudadano.ultima_actividad = self.ahora - timedelta(seconds=30)
        self.ciudadano.save(update_fields=['ultima_actividad'])
        self.client.force_login(self.admin)  # quien ve el feed no afecta el dot del autor
        html = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertIn('presence-dot', html)
        # Autor INACTIVO -> no aparece.
        self.ciudadano.ultima_actividad = self.ahora - timedelta(hours=2)
        self.ciudadano.save(update_fields=['ultima_actividad'])
        # El admin tampoco debe tener actividad reciente para esta comprobación.
        Usuario.objects.filter(pk=self.admin.pk).update(ultima_actividad=self.ahora - timedelta(hours=2))
        html2 = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('presence-dot', html2)

    def test_direccion_no_se_expone_en_feed(self):
        """La dirección de residencia no debe aparecer en el feed (solo en la tabla admin)."""
        self.ciudadano.direccion = 'Calle Secreta 999'
        self.ciudadano.save(update_fields=['direccion'])
        self.client.force_login(self.ciudadano)
        html = self.client.get(reverse('feed_comunitario')).content.decode()
        self.assertNotIn('Calle Secreta 999', html)


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
        # Petición de "calentamiento": deja que ActividadUsuarioMiddleware registre
        # la actividad y quede throttled (vía la sesión), para que la medición real
        # no incluya esa escritura puntual O(1) y siga detectando cualquier N+1.
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
