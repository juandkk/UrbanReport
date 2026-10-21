from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import Usuario, ConfiguracionSistema


import re
import unicodedata


# ── Lista base de términos prohibidos en el nombre de perfil ──
# Se comparan sobre una versión normalizada del nombre (minúsculas, sin tildes y
# con sustituciones leet comunes), de modo que variantes como "P3ndejo", "péndejo"
# o "p e n d e j o" también se detectan.
_PALABRAS_PROHIBIDAS = {
    # ── Insultos / groserías (español) ──
    'puta', 'puto', 'putas', 'putos', 'putita', 'putito', 'putear', 'puton',
    'perra', 'perro hp', 'perrahp', 'hp', 'hpta', 'hijueputa', 'hijueputas',
    'hijuputa', 'ijueputa', 'hijuepucha', 'hijodeputa', 'hijadeputa',
    'hijo de puta', 'hija de puta', 'hijo de perra', 'joputa', 'jueputa',
    'gonorrea', 'gonorriento', 'gonorrienta',
    'malparido', 'malparida', 'malparidos', 'malnacido', 'malnacida',
    'marica', 'maricas', 'maricon', 'maricona', 'maricones', 'mariconazo',
    'marikon', 'marik', 'maricca', 'puñal', 'puñeta', 'puñetero',
    'verga', 'vergas', 'vergazo', 'vergota', 'bergas',
    'pendejo', 'pendeja', 'pendejos', 'pendejas', 'pendejada',
    'imbecil', 'imbeciles', 'idiota', 'idiotas', 'estupido', 'estupida',
    'estupidos', 'tarado', 'tarada', 'retrasado', 'retrasada', 'mongolico',
    'mongolica', 'subnormal', 'baboso', 'babosa', 'bobo hp',
    'cabron', 'cabrona', 'cabrones', 'coño', 'cono', 'conazo',
    'mierda', 'mierdas', 'mrd', 'mierdero', 'carajo', 'carajos',
    'culero', 'culera', 'culiao', 'culiada', 'culiado', 'culiao', 'culicagado',
    'zorra', 'zorras', 'zorro', 'ramera', 'rameras', 'puta madre', 'putamadre',
    'prostituta', 'prostitutas', 'prostituto', 'prepago', 'perra maldita',
    'pirobo', 'piroba', 'pirobos', 'pirobas', 'gamin', 'gonorreo',
    'guevon', 'guevon', 'gueon', 'huevon', 'huevones', 'guevonazo',
    'mamaguevo', 'mamahuevo', 'mamawebo', 'mamaguevos', 'mamona', 'mamon',
    'chupapollas', 'chupapolla', 'chupaverga', 'chimba', 'chucha', 'chimbo',
    'cagada', 'cagon', 'cagona', 'careverga', 'carepicha', 'carechimba',
    'maldito', 'maldita', 'malditos', 'desgraciado', 'desgraciada',
    # ── Sexual / anatomía (indebido como nombre) ──
    'pene', 'penes', 'picha', 'pichula', 'polla', 'pollas', 'pija', 'pito',
    'pipi', 'pipis', 'chimbita', 'penecito',
    'vagina', 'vaginas', 'cuca', 'cuchara', 'crica', 'panocha', 'concha',
    'conchatumadre', 'ctm', 'teta', 'tetas', 'tetona', 'culo', 'culos',
    'culote', 'nalga', 'nalgas', 'nalgon', 'nalgona', 'ano', 'orto',
    'sexo', 'sexual', 'porno', 'pornografia', 'xxx', 'orgia', 'follar',
    'coger', 'tirar sexo', 'masturba', 'masturbacion', 'semen', 'esperma',
    'violador', 'violacion', 'pedofilo', 'pederasta', 'zoofilia',
    # ── Términos sobre orientación/identidad usados como insulto ──
    # Nota: se restringen como nombre de perfil por ser objeto frecuente de abuso.
    'gay', 'gays', 'lesbiana', 'lesbianas', 'lesbico', 'lesbica', 'tortillera',
    'marimacha', 'travesti', 'transexual', 'maricón', 'joto', 'jota',
    'puñal', 'volteado', 'camionera',
    # ── Insultos / vulgaridades (inglés) ──
    'fuck', 'fucker', 'fucking', 'fuk', 'fck', 'shit', 'shite', 'bullshit',
    'bitch', 'bitches', 'asshole', 'ass', 'dick', 'dickhead', 'cunt',
    'bastard', 'whore', 'slut', 'nigger', 'nigga', 'faggot', 'fag',
    'motherfucker', 'pussy', 'cock', 'cocksucker', 'wanker', 'twat',
    'retard', 'rape', 'rapist', 'pedo', 'porn', 'penis', 'boobs', 'tits',
    # ── Suplantación de identidad / cuentas de sistema ──
    'admin', 'administrador', 'administrator', 'moderador', 'moderator',
    'soporte', 'support', 'root', 'superuser', 'sistema', 'system',
    'urbanreport', 'staff', 'oficial', 'official', 'webmaster', 'owner',
}

# Sustituciones "leet" habituales para evadir filtros (3->e, 0->o, etc.)
_LEET = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a',
    '$': 's', '!': 'i',
})


def _normalizar_nombre(texto):
    """
    Normaliza un texto para la comparación anti-groserías:
      - minúsculas
      - sin tildes/acentos
      - sustituciones leet (3->e, 0->o, ...)
    Devuelve el texto normalizado.
    """
    t = (texto or '').lower()
    # Quitar acentos/diacríticos
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    # Sustituciones leet
    t = t.translate(_LEET)
    return t


def validar_nombre_perfil(valor):
    """
    Valida que el nombre de perfil no contenga lenguaje obsceno/indebido ni intente
    suplantar cuentas de sistema. Lanza ValidationError si detecta algo prohibido.
    Devuelve el nombre (con espacios colapsados) si es válido.

    Estrategia de detección:
      1. Normaliza (minúsculas, sin tildes, anti-leet).
      2. Revisa palabra por palabra (coincidencia exacta de token).
      3. Revisa la versión "sin separadores" (p. ej. "p-u-t-a" -> "puta") contra
         los términos prohibidos como subcadena, para atrapar evasiones.
    """
    nombre = re.sub(r'\s+', ' ', (valor or '').strip())
    if not nombre:
        raise ValidationError('El nombre no puede estar vacío.')

    norm = _normalizar_nombre(nombre)

    # 2. Coincidencia por token (palabra completa). Atrapa cualquier término
    #    prohibido que aparezca como palabra suelta, incluso con leet o tildes.
    tokens = set(re.split(r'[^a-z]+', norm))
    for prohibida in _PALABRAS_PROHIBIDAS:
        if ' ' not in prohibida and prohibida in tokens:
            raise ValidationError('El nombre contiene lenguaje no permitido. Elige otro.')
        # Frases prohibidas (con espacio): buscar como subcadena en el texto normalizado
        if ' ' in prohibida and prohibida in norm:
            raise ValidationError('El nombre contiene lenguaje no permitido. Elige otro.')

    # 3. Coincidencia por subcadena sobre el texto compactado (sin separadores),
    #    para atrapar evasiones tipo "p-u-t-a" o "f u c k". Se limita a una lista
    #    de términos INEQUÍVOCOS para no generar falsos positivos con apellidos
    #    legítimos (p. ej. "Vergara" contiene "verga", "Escobar" no aplica, etc.).
    _INEQUIVOCAS = {
        'hijueputa', 'hijuputa', 'hijodeputa', 'hijadeputa', 'malparido',
        'malparida', 'malnacido', 'gonorrea', 'gonorriento', 'maricon',
        'mariconazo', 'mamaguevo', 'mamahuevo', 'mamawebo', 'motherfucker',
        'hijuepucha', 'chupapollas', 'chupaverga', 'conchatumadre',
        'prostituta', 'pirobo', 'piroba', 'cabron', 'desgraciado',
        'fuck', 'shit', 'bitch', 'asshole', 'nigger', 'faggot', 'cocksucker',
        'puta', 'puto', 'mierda', 'pendejo', 'pendeja', 'estupido', 'imbecil',
        'lesbiana', 'prepago', 'violador', 'pedofilo', 'pederasta',
    }
    compacto = re.sub(r'[^a-z]', '', norm)
    for clave in _INEQUIVOCAS:
        if len(clave) >= 4 and clave in compacto:
            raise ValidationError('El nombre contiene lenguaje no permitido. Elige otro.')

    # 4. Evasión por "letras sueltas": secuencias de 3+ caracteres separados uno a
    #    uno (p. ej. "p e n e", "p-u-t-a", "g.a.y"). Ese patrón NO ocurre en nombres
    #    reales, así que al detectarlo compactamos los tramos y comparamos contra
    #    TODA la lista de prohibidas (incluidos términos cortos como "pene"/"gay").
    tramos_sueltos = re.findall(r'(?:\b[a-z]\W+){2,}[a-z]\b', norm)
    for tramo in tramos_sueltos:
        compacto_tramo = re.sub(r'[^a-z]', '', tramo)
        for prohibida in _PALABRAS_PROHIBIDAS:
            clave = prohibida.replace(' ', '')
            if len(clave) >= 3 and clave in compacto_tramo:
                raise ValidationError('El nombre contiene lenguaje no permitido. Elige otro.')

    return nombre


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
            'mostrar_estado_actividad',
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
        # Pueden no existir en subclases (p. ej. AdminConfiguracionForm los excluye).
        for campo_notif in ('notif_feed', 'notif_reportes', 'mostrar_estado_actividad'):
            if campo_notif in self.fields:
                self.fields[campo_notif].required = False

    def clean_nombre_completo(self):
        nombre = (self.cleaned_data.get('nombre_completo') or '').strip()
        if not nombre:
            raise ValidationError('El nombre completo es obligatorio.')
        # Rechaza lenguaje obsceno/indebido o suplantación de cuentas de sistema.
        return validar_nombre_perfil(nombre)

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


class AdminConfiguracionForm(ConfiguracionForm):
    """
    Formulario de la vista "Configuración" del ADMINISTRADOR.

    Reutiliza TODA la información personal y de residencia del ConfiguracionForm
    del ciudadano (mismos campos, mismas validaciones). La diferencia es que el
    administrador NO gestiona preferencias de notificaciones del feed/reporte aquí
    (eso es del ciudadano), así que esos campos se excluyen del formulario.
    """
    class Meta(ConfiguracionForm.Meta):
        # Mismos campos que el ciudadano pero SIN las preferencias de notificaciones.
        fields = [
            'email',
            'telefono',
            'direccion',
            'barrio_vereda',
            'numero_finca',
            'codigo_postal',
            'mostrar_estado_actividad',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # notif_feed / notif_reportes no existen en este form; nada que hacer con ellos.


class ParametrosAlertaForm(forms.ModelForm):
    """
    Parámetros de alerta del sistema (umbral crítico de reportes/hora y tiempo
    máximo de respuesta en horas). Opera sobre el singleton ConfiguracionSistema.
    """
    class Meta:
        model = ConfiguracionSistema
        fields = ['umbral_critico_reportes', 'tiempo_max_respuesta_horas']

    def clean_umbral_critico_reportes(self):
        valor = self.cleaned_data.get('umbral_critico_reportes')
        if valor is None or valor < 1:
            raise ValidationError('El umbral crítico debe ser un número mayor o igual a 1.')
        if valor > 100000:
            raise ValidationError('El umbral crítico es demasiado alto.')
        return valor

    def clean_tiempo_max_respuesta_horas(self):
        valor = self.cleaned_data.get('tiempo_max_respuesta_horas')
        if valor is None or valor < 1:
            raise ValidationError('El tiempo máximo de respuesta debe ser de al menos 1 hora.')
        if valor > 8760:  # 1 año en horas
            raise ValidationError('El tiempo máximo de respuesta es demasiado alto.')
        return valor


class NuevoAdminForm(forms.ModelForm):
    """
    Alta de un nuevo administrador. Crea un Usuario con rol ADMINISTRADOR.
    Reutiliza las validaciones de contraseña y teléfono del registro ciudadano.
    """
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'cfg-input', 'placeholder': '••••••••'}),
    )

    class Meta:
        model = Usuario
        fields = ['username', 'email', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'cfg-input', 'placeholder': 'Nombre de usuario'}),
            'email': forms.EmailInput(attrs={'class': 'cfg-input', 'placeholder': 'admin@correo.com'}),
        }

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise ValidationError('El nombre de usuario es obligatorio.')
        if Usuario.objects.filter(username__iexact=username).exists():
            raise ValidationError('Ese nombre de usuario ya está en uso.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise ValidationError('El correo electrónico es obligatorio.')
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError('Ese correo ya está registrado.')
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        if len(password) < 8:
            raise ValidationError('La contraseña debe tener al menos 8 caracteres.')
        if not any(c.isalpha() for c in password):
            raise ValidationError('La contraseña debe incluir al menos una letra.')
        if not any(c.isdigit() for c in password):
            raise ValidationError('La contraseña debe incluir al menos un número.')
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.rol = Usuario.Rol.ADMINISTRADOR
        user.is_staff = True  # acceso al panel admin de Django
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
