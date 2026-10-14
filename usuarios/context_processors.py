from django.conf import settings


def sso_flags(request):
    """
    Expone a las plantillas si cada proveedor de SSO está configurado,
    para habilitar/deshabilitar los botones de login social.
    """
    return {
        'google_sso_habilitado': getattr(settings, 'GOOGLE_SSO_HABILITADO', False),
        'facebook_sso_habilitado': getattr(settings, 'FACEBOOK_SSO_HABILITADO', False),
    }


def es_admin(request):
    """
    Expone `es_admin` a todas las plantillas con un criterio ÚNICO y consistente:
    un usuario es administrador si su rol es ADMINISTRADOR, o si es staff/superuser.
    Así el sidebar y demás plantillas no dependen solo de `user.rol`.
    """
    user = getattr(request, 'user', None)
    valor = False
    if user is not None and user.is_authenticated:
        valor = bool(
            getattr(user, 'rol', None) == 'ADMINISTRADOR'
            or user.is_staff
            or user.is_superuser
        )
    return {'es_admin': valor}
