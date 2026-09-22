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

    def __str__(self):
        return self.username