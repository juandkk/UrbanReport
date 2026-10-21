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
    También expone `total_notificaciones_no_leidas` para que el badge de notificaciones
    en el sidebar se renderice inmediatamente en cualquier vista sin depender de JavaScript.
    """
    user = getattr(request, 'user', None)
    valor = False
    total_notif = 0
    if user is not None and user.is_authenticated:
        valor = bool(
            getattr(user, 'rol', None) == 'ADMINISTRADOR'
            or user.is_staff
            or user.is_superuser
        )
        notif_rel = getattr(user, 'notificaciones', None)
        if notif_rel is not None:
            total_notif = notif_rel.filter(leido=False).count()

    return {
        'es_admin': valor,
        'total_notificaciones_no_leidas': total_notif,
    }
