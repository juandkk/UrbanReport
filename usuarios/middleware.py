from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import ConfiguracionSistema, Usuario


def _usuario_es_admin(user):
    if not user or not user.is_authenticated:
        return False
    return (
        getattr(user, 'rol', None) == Usuario.Rol.ADMINISTRADOR
        or user.is_staff
        or user.is_superuser
    )


class CompletarPerfilMiddleware:
    """
    Middleware principal de control de acceso y actividad de usuarios:
    1. Actualiza la marca de última actividad (`last_login`) de usuarios autenticados
       (con throttle de 60s para no añadir escrituras innecesarias), permitiendo saber
       con exactitud la última conexión y si un administrador está en línea.
    2. Aplica el Modo Mantenimiento global (`ConfiguracionSistema.modo_mantenimiento`):
       cuando está activo, suspende el acceso público y de ciudadanos mostrando la
       pantalla de mantenimiento (503), permitiendo operar únicamente a administradores
       y manteniendo abiertas las rutas de login/logout/archivos estáticos.
    3. Redirige a `completar_perfil` si un ciudadano autenticado (p. ej. vía SSO)
       tiene campos obligatorios pendientes.
    """

    # Vistas (por nombre de URL) que NO deben redirigirse a completar_perfil.
    NOMBRES_PERMITIDOS = {'completar_perfil', 'logout', 'login'}
    # Vistas siempre accesibles durante modo mantenimiento (para poder autenticarse/salir).
    NOMBRES_MANTENIMIENTO_PERMITIDOS = {'login', 'logout'}
    # Prefijos de ruta siempre permitidos (auth social, admin, estáticos, media).
    PREFIJOS_PERMITIDOS = ('/accounts/', '/admin/', '/static/', '/media/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path.startswith(self.PREFIJOS_PERMITIDOS):
            return None

        user = getattr(request, 'user', None)
        autenticado = bool(user is not None and user.is_authenticated)
        es_admin = _usuario_es_admin(user)
        match = getattr(request, 'resolver_match', None)
        url_name = match.url_name if match is not None else None

        # 1. Refrescar marca de última actividad (cada >= 60 s) si no está cerrando sesión
        if autenticado and url_name != 'logout':
            ahora = timezone.now()
            if not user.last_login or (ahora - user.last_login).total_seconds() >= 60:
                Usuario.objects.filter(pk=user.pk).update(last_login=ahora)
                user.last_login = ahora

        # 2. Verificar Modo Mantenimiento (los administradores nunca son bloqueados)
        if not es_admin and url_name not in self.NOMBRES_MANTENIMIENTO_PERMITIDOS:
            if ConfiguracionSistema.esta_en_mantenimiento():
                es_ajax = (
                    request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    or request.path.startswith('/feed/api/')
                )
                if es_ajax:
                    return JsonResponse({
                        'status': 'error',
                        'modo_mantenimiento': True,
                        'message': 'El sistema se encuentra temporalmente en mantenimiento.',
                    }, status=503)
                return render(request, 'usuarios/mantenimiento.html', status=503)

        # 3. Verificar perfil completo para ciudadanos autenticados
        if not autenticado or es_admin:
            return None
        if not user.perfil_incompleto():
            return None
        if url_name in self.NOMBRES_PERMITIDOS:
            return None
        return redirect('completar_perfil')


class ActividadUsuarioMiddleware:
    """
    Actualiza la marca `ultima_actividad` del usuario autenticado para estimar su
    presencia ("en línea"), de forma EFICIENTE: escribe en la base de datos como
    máximo una vez por minuto por usuario, no en cada petición.

    Para lograr el "throttling" sin escrituras extra, guarda en la sesión del
    usuario (ya existente) la hora de la última escritura y solo vuelve a escribir
    cuando ha pasado el intervalo mínimo. Usa update() para tocar únicamente esa
    columna, sin disparar señales ni reescribir toda la fila.

    No guarda contraseñas, tokens ni datos sensibles: solo una fecha/hora.
    """

    # Cada cuánto, como mínimo, se vuelve a escribir en la base de datos (segundos).
    # Debe ser menor que PRESENCIA_VENTANA_SEGUNDOS y que el intervalo del heartbeat
    # del frontend (25s) para que la presencia se mantenga fresca sin escrituras de más.
    INTERVALO_MINIMO = 20

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._actualizar_actividad(request)
        return self.get_response(request)

    def _actualizar_actividad(self, request):
        from django.utils import timezone
        from .models import Usuario
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return

        ahora = timezone.now()
        marca_sesion = request.session.get('_ultima_actividad_ts')

        # Si escribimos hace menos del intervalo, no tocar la base de datos.
        if marca_sesion is not None:
            try:
                transcurrido = ahora.timestamp() - float(marca_sesion)
                if transcurrido < self.INTERVALO_MINIMO:
                    return
            except (TypeError, ValueError):
                pass

        # Actualización mínima y directa de una sola columna (sin señales ni full save).
        # Usamos el modelo Usuario explícito (request.user es un SimpleLazyObject).
        Usuario.objects.filter(pk=user.pk).update(ultima_actividad=ahora)
        request.session['_ultima_actividad_ts'] = ahora.timestamp()
