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

    # ── Preferencias de notificaciones (Configuración del perfil) ──
    # True  = el usuario recibe las notificaciones correspondientes (interruptor "apagado"
    #         en la UI, es decir, NO suspendidas).
    # False = el usuario suspende esas notificaciones (interruptor "encendido" en la UI).
    # Son preferencias independientes entre sí. Guardar la preferencia NO implica que
    # exista todavía un sistema de envío de notificaciones; solo deja el estado persistido.
    notif_feed = models.BooleanField(
        'Notificaciones del Feed comunitario',
        default=True,
    )
    notif_reportes = models.BooleanField(
        'Notificaciones de reportes',
        default=True,
    )

    # Usuarios que este usuario sigue (relación dirigida a través de Seguimiento)
    seguidos = models.ManyToManyField(
        'self',
        through='Seguimiento',
        through_fields=('seguidor', 'seguido'),
        symmetrical=False,
        related_name='seguidores',
    )

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

    def perfil_incompleto(self):
        """
        True si al usuario le faltan datos obligatorios de contacto/ubicación.
        Se usa sobre todo para usuarios que entraron por SSO (Google/Facebook),
        que no pasaron por el formulario de registro y llegan sin estos campos.
        Los superusuarios/staff quedan exentos (acceso administrativo).
        """
        if self.is_superuser or self.is_staff:
            return False
        requeridos = [self.telefono, self.direccion, self.barrio_vereda, self.codigo_postal]
        return any(not (c or '').strip() for c in requeridos)

    @property
    def total_seguidores(self):
        """Cuántos usuarios siguen a este usuario."""
        return self.seguidores.count()

    @property
    def total_seguidos(self):
        """A cuántos usuarios sigue este usuario."""
        return self.seguidos.count()

    def sigue_a(self, otro_usuario):
        """Devuelve True si este usuario sigue a otro_usuario."""
        if not otro_usuario:
            return False
        return Seguimiento.objects.filter(seguidor=self, seguido=otro_usuario).exists()

    def nivel_confianza(self, total=None, resueltos=None):
        """
        Calcula el nivel de confianza del usuario a partir de su historial de
        reportes: cuántos ha hecho y qué proporción se ha resuelto. Un mayor
        volumen de reportes válidos (resueltos) implica más confianza.

        Devuelve un dict con:
          - 'nivel': etiqueta ('Nuevo' | 'Bajo' | 'Medio' | 'Alto')
          - 'total': total de reportes hechos
          - 'resueltos': reportes marcados como resueltos
          - 'tasa': porcentaje de resolución (0-100)
        """
        if total is None or resueltos is None:
            # Import local para evitar dependencia circular entre apps
            from feed.models import Publicacion

            agregados = Publicacion.objects.filter(autor=self).aggregate(
                total=models.Count('id'),
                resueltos=models.Count(
                    'id',
                    filter=models.Q(estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA),
                ),
            )
            total = agregados['total'] or 0
            resueltos = agregados['resueltos'] or 0

        tasa = round((resueltos / total) * 100) if total else 0

        if total == 0:
            nivel = 'Nuevo'
        elif resueltos >= 5 and tasa >= 60:
            nivel = 'Alto'
        elif resueltos >= 2 or tasa >= 40:
            nivel = 'Medio'
        else:
            nivel = 'Bajo'

        return {
            'nivel': nivel,
            'total': total,
            'resueltos': resueltos,
            'tasa': tasa,
        }


class Seguimiento(models.Model):
    """Relación dirigida: 'seguidor' sigue a 'seguido'."""
    seguidor = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='relaciones_siguiendo',
    )
    seguido = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='relaciones_seguidores',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Un usuario no puede seguir dos veces al mismo
        unique_together = ('seguidor', 'seguido')
        verbose_name = 'Seguimiento'
        verbose_name_plural = 'Seguimientos'
        constraints = [
            # Evita que un usuario se siga a sí mismo
            models.CheckConstraint(
                condition=~models.Q(seguidor=models.F('seguido')),
                name='no_autoseguimiento',
            ),
        ]

    def __str__(self):
        return f"{self.seguidor.username} sigue a {self.seguido.username}"
