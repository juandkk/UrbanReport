from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from feed.models import Publicacion
from usuarios.models import Seguimiento, Usuario


class UsuariosModelAndMiddlewareTest(TestCase):
    """Pruebas unitarias y de integración para el módulo de usuarios."""

    def setUp(self):
        self.user_incompleto = Usuario.objects.create_user(
            username='sso_user',
            email='sso@test.com',
            password='Password123',
        )
        self.user_completo = Usuario.objects.create_user(
            username='ciudadano_ok',
            email='ok@test.com',
            password='Password123',
            telefono='3001234567',
            direccion='Calle 10 # 40-20',
            barrio_vereda='El Poblado',
            codigo_postal='050021',
        )

    def test_middleware_redirige_perfil_incompleto(self):
        """Un usuario con perfil incompleto (ej. SSO nuevo) es redirigido a completar_perfil."""
        self.assertTrue(self.user_incompleto.perfil_incompleto())
        self.client.force_login(self.user_incompleto)
        resp = self.client.get(reverse('feed_comunitario'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('completar_perfil'), resp['Location'])

    def test_nivel_confianza_progresion(self):
        """nivel_confianza evoluciona de Nuevo -> Bajo -> Medio -> Alto según reportes resueltos."""
        self.assertEqual(self.user_completo.nivel_confianza()['nivel'], 'Nuevo')

        # 1 reporte sin resolver -> Bajo
        p1 = Publicacion.objects.create(
            autor=self.user_completo,
            autor_nombre='Ciudadano OK',
            contenido='Reporte 1',
            estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
        )
        self.assertEqual(self.user_completo.nivel_confianza()['nivel'], 'Bajo')

        # Resolver p1 (100% tasa) -> Medio
        p1.estado_incidencia = Publicacion.EstadoIncidencia.RESUELTA
        p1.save()
        self.assertEqual(self.user_completo.nivel_confianza()['nivel'], 'Medio')

        # 5 resueltos en total -> Alto
        for i in range(4):
            Publicacion.objects.create(
                autor=self.user_completo,
                autor_nombre='Ciudadano OK',
                contenido=f'Reporte resuelto {i}',
                estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA,
            )
        conf = self.user_completo.nivel_confianza()
        self.assertEqual(conf['nivel'], 'Alto')
        self.assertEqual(conf['total'], 5)
        self.assertEqual(conf['resueltos'], 5)
        self.assertEqual(conf['tasa'], 100)

    def test_no_autoseguimiento(self):
        """No se permite seguirse a sí mismo ni por vista AJAX ni por restricción de BD."""
        self.client.force_login(self.user_completo)
        resp = self.client.post(reverse('toggle_seguir', args=[self.user_completo.username]))
        self.assertEqual(resp.status_code, 400)
        with self.assertRaises(IntegrityError):
            Seguimiento.objects.create(seguidor=self.user_completo, seguido=self.user_completo)

    def test_recuperacion_contrasena_deshabilitada_get(self):
        """GET /recuperar-contrasena/ muestra el mensaje de servicio temporalmente fuera de servicio."""
        resp = self.client.get(reverse('recuperar_contrasena'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Servicio temporalmente fuera de servicio')
        # No debe presentar el formulario vulnerable para solicitar restablecimiento
        self.assertNotContains(resp, 'name="email"')

    def test_recuperacion_contrasena_deshabilitada_post(self):
        """POST /recuperar-contrasena/ no genera enlaces de restablecimiento ni envía correos."""
        resp = self.client.post(reverse('recuperar_contrasena'), {'email': 'ok@test.com'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Servicio temporalmente fuera de servicio')
        self.assertIsNone(self.client.session.get('reset_link'))

    def test_rutas_recuperacion_protegidas_y_deshabilitadas(self):
        """Todas las subrutas de reseteo muestran el aviso de servicio deshabilitado."""
        for url in [
            reverse('password_reset_done'),
            reverse('password_reset_confirm', kwargs={'uidb64': 'MQ', 'token': 'dummy-token'}),
            reverse('password_reset_complete'),
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Servicio temporalmente fuera de servicio')

    def test_login_page_incluye_aviso_y_enlace_recuperacion(self):
        """La página de login incluye el identificador del aviso de servicio fuera de servicio."""
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="recoveryDisabledNotice"')
        self.assertContains(resp, 'Servicio temporalmente fuera de servicio')

