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


class RendimientoTest(TestCase):
    """El número de consultas no debe crecer con la cantidad de publicaciones (sin N+1)."""

    @classmethod
    def setUpTestData(cls):
        cls.u = Usuario.objects.create_user(username='u', email='u@t.co', password='x', **PERFIL_COMPLETO)
        cls.o1 = Usuario.objects.create_user(username='o1', email='o1@t.co', password='x', **PERFIL_COMPLETO)
        cls.o2 = Usuario.objects.create_user(username='o2', email='o2@t.co', password='x', **PERFIL_COMPLETO)

    def _contar(self, url):
        self.client.force_login(self.u)
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return ctx.captured_queries

    def _assert_constante(self, url):
        crear_publicaciones(self.u, [self.o1, self.o2], 2)
        q_pocas = self._contar(url)
        pocas = len(q_pocas)
        crear_publicaciones(self.u, [self.o1, self.o2], 8)
        q_muchas = self._contar(url)
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
