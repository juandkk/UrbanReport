from django.shortcuts import redirect


class CompletarPerfilMiddleware:
    """
    Si un usuario autenticado tiene el perfil incompleto (típicamente los que
    entraron por SSO sin pasar por el formulario de registro), lo redirige a la
    página para completar sus datos.

    Deja pasar sin redirigir: la propia página de completar perfil, el login,
    el logout, las rutas de autenticación social (/accounts/), el admin de
    Django y los archivos estáticos/media, para no crear bucles.

    Usa process_view (no __call__) porque ahí ya está resuelta la URL y podemos
    identificar la vista por su nombre, sin depender de la ruta exacta (la misma
    vista puede estar montada con y sin prefijo).
    """

    # Vistas (por nombre de URL) que NO deben redirigirse, para evitar bucles.
    NOMBRES_PERMITIDOS = {'completar_perfil', 'logout', 'login'}
    # Prefijos de ruta siempre permitidos (auth social, admin, estáticos, media).
    PREFIJOS_PERMITIDOS = ('/accounts/', '/admin/', '/static/', '/media/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        if not user.perfil_incompleto():
            return None
        if request.path.startswith(self.PREFIJOS_PERMITIDOS):
            return None
        match = getattr(request, 'resolver_match', None)
        if match is not None and match.url_name in self.NOMBRES_PERMITIDOS:
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
