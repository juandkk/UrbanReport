import uuid

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adapter de allauth para el login social (Google/Facebook).

    Resuelve dos problemas con proveedores que no entregan email (p. ej.
    Facebook cuando no se pide/aprueba el permiso 'email'):
      1. El modelo Usuario exige email único y no nulo; sin email, la creación
         falla con IntegrityError ("Falló la autenticación de terceros").
      2. También puede faltar el username.

    Si falta el email, generamos un placeholder único; el usuario lo corrige
    después en la página de "completar perfil".
    """

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        # Garantizar un username
        if not getattr(user, 'username', None):
            base = (data.get('name') or data.get('first_name') or 'usuario')
            base = ''.join(ch for ch in base.lower() if ch.isalnum()) or 'usuario'
            user.username = f'{base}{uuid.uuid4().hex[:6]}'

        # Garantizar un email (placeholder si el proveedor no lo entregó)
        if not getattr(user, 'email', None):
            proveedor = getattr(sociallogin.account, 'provider', 'social')
            user.email = f'{user.username}@{proveedor}.sin-email.local'

        return user

    def save_user(self, request, sociallogin, form=None):
        # Reasegurar unicidad del username/email justo antes de guardar, por si
        # el placeholder generado ya existiera (muy improbable, pero seguro).
        from .models import Usuario

        user = sociallogin.user
        if not user.username or Usuario.objects.filter(username=user.username).exclude(pk=user.pk).exists():
            user.username = f'usuario{uuid.uuid4().hex[:8]}'
        if not user.email or Usuario.objects.filter(email__iexact=user.email).exclude(pk=user.pk).exists():
            user.email = f'{user.username}@social.sin-email.local'

        return super().save_user(request, sociallogin, form=form)
