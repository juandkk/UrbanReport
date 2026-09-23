from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import Usuario


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
        email = self.cleaned_data.get('email')
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError('Este correo electrónico ya está registrado.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.rol = Usuario.Rol.CIUDADANO
        if commit:
            user.save()
        return user


class RecuperarContrasenaForm(forms.Form):
    email = forms.EmailField(
        label='Correo Electrónico',
        widget=forms.EmailInput(attrs={
            'class': 'auth-input with-icon',
            'placeholder': 'admin@ciudad.gov',
            'required': True,
        })
    )
