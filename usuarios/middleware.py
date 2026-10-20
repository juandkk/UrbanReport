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
            # Throttle de 30s: menor que la ventana de presencia (60s) y que el
            # heartbeat del navegador (25s), para que el estado "en línea" se
            # mantenga fresco sin añadir una escritura en cada petición.
            if not user.last_login or (ahora - user.last_login).total_seconds() >= 30:
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
