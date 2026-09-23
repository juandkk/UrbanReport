from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        CIUDADANO = 'CIUDADANO', 'Ciudadano'
        ADMINISTRADOR = 'ADMINISTRADOR', 'Administrador'

    email = models.EmailField(unique=True)
    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.CIUDADANO
    )
    telefono = models.CharField('Número de teléfono', max_length=25, blank=True, null=True)
    direccion = models.CharField('Dirección', max_length=255, blank=True, null=True)
    barrio_vereda = models.CharField('Barrio o vereda', max_length=150, blank=True, null=True)
    numero_finca = models.CharField('Número de finca', max_length=50, blank=True, null=True)
    codigo_postal = models.CharField('Código postal', max_length=20, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"