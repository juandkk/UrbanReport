"""
Settings para ejecutar la suite de pruebas de forma AISLADA.

El .env local apunta a la base de datos remota (Supabase). Las pruebas NUNCA
deben tocarla, así que aquí se fuerza SQLite en memoria y almacenamiento local.

Uso:
    python manage.py test --settings=config.settings_test
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Hash de contraseñas rápido: acelera la creación de usuarios en los tests.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Sin redirección HTTPS en el cliente de pruebas.
SECURE_SSL_REDIRECT = False

ALLOWED_HOSTS = ['*']
