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

    def test_ciudadano_puede_eliminar_su_cuenta(self):
        """El ciudadano puede eliminar su cuenta desde Configuración confirmando con 'ELIMINAR'."""
        self.client.force_login(self.user_completo)
        Publicacion.objects.create(
            autor=self.user_completo,
            autor_nombre='Ciudadano OK',
            contenido='Reporte antes de borrar cuenta',
        )

        # Sin confirmación válida no borra la cuenta
        resp_fail = self.client.post(
            reverse('eliminar_cuenta'),
            {'confirmacion': 'cancelar'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_fail.status_code, 400)
        self.assertTrue(Usuario.objects.filter(pk=self.user_completo.pk).exists())

        # Con confirmación exacta 'ELIMINAR' borra la cuenta y sus publicaciones y redirige a login
        user_id = self.user_completo.pk
        resp_ok = self.client.post(reverse('eliminar_cuenta'), {'confirmacion': 'ELIMINAR'})
        self.assertEqual(resp_ok.status_code, 302)
        self.assertIn(reverse('login'), resp_ok['Location'])
        self.assertFalse(Usuario.objects.filter(pk=user_id).exists())
        self.assertEqual(Publicacion.objects.filter(autor_id=user_id).count(), 0)

    def test_estado_en_linea_y_ultima_conexion_administradores(self):
        """La tabla de administradores refleja correctamente quién está en línea, desconectado o sin acceso."""
        from django.test import Client

        admin1 = Usuario.objects.create_user(
            username='admin_activo',
            email='admin1@test.com',
            password='Password123',
            rol=Usuario.Rol.ADMINISTRADOR,
            is_staff=True,
            telefono='3001112233',
            direccion='Calle 1',
            barrio_vereda='Centro',
            codigo_postal='050001',
        )
        admin2 = Usuario.objects.create_user(
            username='admin_otro',
            email='admin2@test.com',
            password='Password123',
            rol=Usuario.Rol.ADMINISTRADOR,
            is_staff=True,
            telefono='3001112234',
            direccion='Calle 2',
            barrio_vereda='Centro',
            codigo_postal='050001',
        )
        admin_nuevo = Usuario.objects.create_user(
            username='admin_sin_login',
            email='admin3@test.com',
            password='Password123',
            rol=Usuario.Rol.ADMINISTRADOR,
            is_staff=True,
        )

        client1 = Client()
        client2 = Client()
        client1.force_login(admin1)
        client2.force_login(admin2)

        # Ambos tienen sesión activa y acaban de iniciar sesión -> ambos en línea
        r = client1.get(reverse('estado_administradores'))
        self.assertEqual(r.status_code, 200)
        mapa = {a['username']: a for a in r.json()['administradores']}
        self.assertTrue(mapa['admin_activo']['en_linea'])
        self.assertEqual(mapa['admin_activo']['ultimo_acceso'], 'Ahora mismo')
        self.assertTrue(mapa['admin_otro']['en_linea'])
        self.assertFalse(mapa['admin_sin_login']['en_linea'])
        self.assertEqual(mapa['admin_sin_login']['ultimo_acceso'], 'Nunca')

        # Cuando admin2 cierra sesión, pasa inmediatamente a Inactivo conservando su última conexión
        client2.get(reverse('logout'))
        r2 = client1.get(reverse('estado_administradores'))
        mapa2 = {a['username']: a for a in r2.json()['administradores']}
        self.assertFalse(mapa2['admin_otro']['en_linea'])
        self.assertNotEqual(mapa2['admin_otro']['ultimo_acceso'], 'Nunca')

    def test_modo_mantenimiento_bloquea_ciudadanos_y_permite_admins(self):
        """Cuando modo_mantenimiento está activo, ciudadanos reciben 503 y los admins operan normalmente."""
        from django.test import Client
        from usuarios.models import ConfiguracionSistema

        admin = Usuario.objects.create_user(
            username='admin_maint',
            email='maint@test.com',
            password='Password123',
            rol=Usuario.Rol.ADMINISTRADOR,
            is_staff=True,
            telefono='3009998877',
            direccion='Cra 50',
            barrio_vereda='Laureles',
            codigo_postal='050030',
        )

        admin_client = Client()
        admin_client.force_login(admin)

        # Activar modo mantenimiento vía AJAX
        resp_toggle = admin_client.post(reverse('toggle_modo_mantenimiento'), {'activar': 'on'})
        self.assertEqual(resp_toggle.status_code, 200)
        self.assertTrue(ConfiguracionSistema.esta_en_mantenimiento())

        # Ciudadano autenticado recibe 503 en vistas HTML y JSON en endpoints AJAX
        ciu_client = Client()
        ciu_client.force_login(self.user_completo)
        resp_feed = ciu_client.get(reverse('feed_comunitario'))
        self.assertEqual(resp_feed.status_code, 503)
        self.assertContains(resp_feed, 'Sistema en mantenimiento', status_code=503)

        resp_api = ciu_client.get(reverse('api_incidentes_mapa'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_api.status_code, 503)
        self.assertTrue(resp_api.json().get('modo_mantenimiento'))

        # El administrador sí puede navegar normalmente por el feed y configuración
        self.assertEqual(admin_client.get(reverse('feed_comunitario')).status_code, 200)
        self.assertEqual(admin_client.get(reverse('configuracion_admin')).status_code, 200)

        # Desactivar modo mantenimiento restaura el acceso al ciudadano
        admin_client.post(reverse('toggle_modo_mantenimiento'), {'activar': ''})
        self.assertFalse(ConfiguracionSistema.esta_en_mantenimiento())
        self.assertEqual(ciu_client.get(reverse('feed_comunitario')).status_code, 200)


