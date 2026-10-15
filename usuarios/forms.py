from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import Usuario


def validar_telefono_colombiano(valor):
    """
    Valida un número de teléfono colombiano: exactamente 10 dígitos, sin
    espacios, signos ni letras. Devuelve el número normalizado (solo dígitos).
    Lanza ValidationError si no cumple.
    """
    telefono = (valor or '').strip()
    if not telefono:
        raise ValidationError('El número de teléfono es obligatorio.')
    if not telefono.isdigit():
        raise ValidationError('El teléfono solo puede contener números (sin espacios, signos ni letras).')
    if len(telefono) != 10:
        raise ValidationError('El teléfono debe tener exactamente 10 dígitos.')
    return telefono


class LoginForm(forms.Form):
    ROLES = [
        ('CIUDADANO', 'Ciudadano'),
        ('ADMINISTRADOR', 'Administrador'),
    ]

    email_or_username = forms.CharField(
        label='Correo Electrónico',
        widget=forms.TextInput(attrs={
            'class': 'auth-input',
            'placeholder': 'ejemplo@correo.com',
            'autocomplete': 'email',
            'required': True,
        })
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'auth-input',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'required': True,
        })
    )

    recordarme = forms.BooleanField(
        required=False,
        label='Recordarme',
        widget=forms.CheckboxInput(attrs={
            'class': 'auth-checkbox',
        })
    )


class RegistroForm(forms.ModelForm):
    password = forms.CharField(
        label='Contraseña*',
        widget=forms.PasswordInput(attrs={
            'class': 'auth-input',
            'placeholder': '••••••••',
            'autocomplete': 'new-password',
            'required': True,
        })
    )

    class Meta:
        model = Usuario
        fields = [
            'username',
            'email',
            'telefono',
            'direccion',
            'barrio_vereda',
            'numero_finca',
            'codigo_postal',
            'password',
        ]
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': 'Nombre de usuario',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'class': 'auth-input',
                'placeholder': 'ejemplo@correo.com',
                'required': True,
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': '300 0000000',
                'required': True,
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': 'KR 0 #00-00',
                'required': True,
            }),
            'barrio_vereda': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': 'Ej: La Esperanza',
                'required': True,
            }),
            'numero_finca': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': 'Ej: 12',
            }),
            'codigo_postal': forms.TextInput(attrs={
                'class': 'auth-input',
                'placeholder': '002000',
                'required': True,
            }),
        }

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        # El correo debe terminar en .com (requisito del sistema)
        if not email.lower().endswith('.com'):
            raise ValidationError('El correo electrónico debe terminar en «.com».')
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError('Este correo electrónico ya está registrado.')
        return email

    def clean_telefono(self):
        return validar_telefono_colombiano(self.cleaned_data.get('telefono'))

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        # Mínimo 8 caracteres
        if len(password) < 8:
            raise ValidationError('La contraseña debe tener al menos 8 caracteres.')
        # Alfanumérica: al menos una letra y al menos un número
        if not any(c.isalpha() for c in password):
            raise ValidationError('La contraseña debe incluir al menos una letra.')
        if not any(c.isdigit() for c in password):
            raise ValidationError('La contraseña debe incluir al menos un número.')
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.rol = Usuario.Rol.CIUDADANO
        if commit:
            user.save()
        return user


class CompletarPerfilForm(forms.ModelForm):
    """
    Formulario para que los usuarios que entraron por SSO (Google/Facebook)
    completen los datos obligatorios que no pide el proveedor.
    """
    class Meta:
        model = Usuario
        fields = ['telefono', 'direccion', 'barrio_vereda', 'numero_finca', 'codigo_postal']
        widgets = {
            'telefono': forms.TextInput(attrs={
                'class': 'auth-input', 'placeholder': '300 0000000', 'required': True,
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'auth-input', 'placeholder': 'KR 0 #00-00', 'required': True,
            }),
            'barrio_vereda': forms.TextInput(attrs={
                'class': 'auth-input', 'placeholder': 'Ej: La Esperanza', 'required': True,
            }),
            'numero_finca': forms.TextInput(attrs={
                'class': 'auth-input', 'placeholder': 'Ej: 12',
            }),
            'codigo_postal': forms.TextInput(attrs={
                'class': 'auth-input', 'placeholder': '002000', 'required': True,
            }),
        }

    def clean_telefono(self):
        return validar_telefono_colombiano(self.cleaned_data.get('telefono'))

    def clean(self):
        cleaned = super().clean()
        # Estos tres son obligatorios (numero_finca es opcional; telefono ya se
        # valida en clean_telefono con el formato de 10 dígitos).
        for campo in ['direccion', 'barrio_vereda', 'codigo_postal']:
            if not (cleaned.get(campo) or '').strip():
                self.add_error(campo, 'Este campo es obligatorio.')
        return cleaned


class ConfiguracionForm(forms.ModelForm):
    """
    Formulario de la vista "Configuración" del perfil.

    - Maneja el nombre completo como un único campo (`nombre_completo`) que se
      descompone en first_name / last_name al guardar (igual criterio que
      editar_perfil_ajax).
    - Reutiliza los campos ya existentes del modelo Usuario para residencia y
      contacto, además de las dos preferencias de notificaciones.
    - Valida en el servidor: email con formato válido, único (excluyendo al propio
      usuario) y terminado en «.com»; teléfono colombiano de 10 dígitos; y los
      campos obligatorios marcados con asterisco en la referencia.

    Los interruptores de notificaciones representan "suspender": si el usuario
    activa "Suspender", la preferencia correspondiente queda en False. Esa
    conversión se hace en la vista; aquí los campos booleanos guardan el valor
    final (True = recibir, False = suspendido).
    """
    nombre_completo = forms.CharField(
        label='Nombre completo',
        required=True,
        max_length=300,
        widget=forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Tu nombre completo'}),
    )

    class Meta:
        model = Usuario
        fields = [
            'email',
            'telefono',
            'direccion',
            'barrio_vereda',
            'numero_finca',
            'codigo_postal',
            'notif_feed',
            'notif_reportes',
        ]
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'cfg-input', 'placeholder': 'ejemplo@correo.com'}),
            'telefono': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': '+57 300 0000000'}),
            'direccion': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Calle, carrera, transversal...'}),
            'barrio_vereda': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Barrio o vereda'}),
            'numero_finca': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Opcional'}),
            'codigo_postal': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Código postal'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Precargar nombre_completo desde first_name + last_name del usuario.
        if self.instance and self.instance.pk:
            nombre = f"{self.instance.first_name} {self.instance.last_name}".strip()
            self.fields['nombre_completo'].initial = nombre
        # Campos obligatorios (asterisco en la referencia). numero_finca es opcional.
        for campo in ['email', 'telefono', 'direccion', 'barrio_vereda', 'codigo_postal']:
            self.fields[campo].required = True
        self.fields['numero_finca'].required = False
        # notif_* no son obligatorios (checkbox); su ausencia significa False.
        self.fields['notif_feed'].required = False
        self.fields['notif_reportes'].required = False

    def clean_nombre_completo(self):
        nombre = (self.cleaned_data.get('nombre_completo') or '').strip()
        if not nombre:
            raise ValidationError('El nombre completo es obligatorio.')
        return nombre

    def clean_email(self):
        # Django ya valida el formato del email por ser un EmailField. Aquí solo
        # añadimos la comprobación de unicidad excluyendo al propio usuario, para
        # permitir "guardar sin cambiar el correo" sin chocar consigo mismo.
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise ValidationError('El correo electrónico es obligatorio.')
        qs = Usuario.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Este correo electrónico ya está registrado por otra cuenta.')
        return email

    def clean_telefono(self):
        return validar_telefono_colombiano(self.cleaned_data.get('telefono'))

    def clean_direccion(self):
        valor = (self.cleaned_data.get('direccion') or '').strip()
        if not valor:
            raise ValidationError('La dirección de residencia es obligatoria.')
        return valor

    def clean_barrio_vereda(self):
        valor = (self.cleaned_data.get('barrio_vereda') or '').strip()
        if not valor:
            raise ValidationError('El barrio o vereda es obligatorio.')
        return valor

    def clean_codigo_postal(self):
        # Se conserva como texto (no se convierte a entero) para preservar ceros iniciales.
        valor = (self.cleaned_data.get('codigo_postal') or '').strip()
        if not valor:
            raise ValidationError('El código postal es obligatorio.')
        if not valor.isdigit():
            raise ValidationError('El código postal solo puede contener dígitos.')
        if not (3 <= len(valor) <= 10):
            raise ValidationError('El código postal debe tener entre 3 y 10 dígitos.')
        return valor

    def save(self, commit=True):
        usuario = super().save(commit=False)
        # Descomponer nombre_completo en first_name / last_name
        nombre = self.cleaned_data['nombre_completo']
        partes = nombre.split()
        usuario.first_name = partes[0][:150]
        usuario.last_name = ' '.join(partes[1:])[:150] if len(partes) > 1 else ''
        if commit:
            usuario.save()
        return usuario


class RecuperarContrasenaForm(forms.Form):
    email = forms.EmailField(
        label='Correo Electrónico',
        widget=forms.EmailInput(attrs={
            'class': 'auth-input with-icon',
            'placeholder': 'admin@ciudad.gov',
            'required': True,
        })
    )
