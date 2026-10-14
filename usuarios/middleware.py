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
