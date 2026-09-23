from django.db import models
from django.conf import settings


class Publicacion(models.Model):
    class EstadoIncidencia(models.TextChoices):
        REPORTADO = 'REPORTADO', 'Reportado'
        EN_PROCESO = 'EN_PROCESO', 'En Proceso'
        RESUELTA = 'RESUELTA', 'Resuelta'

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='publicaciones'
    )
    autor_nombre = models.CharField(max_length=150, blank=True)
    contenido = models.TextField()
    imagen = models.ImageField(upload_to='publicaciones/', blank=True, null=True)
    imagen_url = models.CharField(max_length=500, blank=True, null=True, help_text="URL estática o externa opcional")
    likes = models.PositiveIntegerField(default=0)
    estado_incidencia = models.CharField(
        max_length=20,
        choices=EstadoIncidencia.choices,
        default=EstadoIncidencia.REPORTADO
    )
    ubicacion = models.CharField(max_length=200, blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Publicación'
        verbose_name_plural = 'Publicaciones'

    def __str__(self):
        return f"{self.autor_nombre or self.autor.username}: {self.contenido[:40]}..."

    @property
    def total_comentarios(self):
        return self.comentarios.count()


class Comentario(models.Model):
    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        related_name='comentarios'
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    autor_nombre = models.CharField(max_length=100)
    texto = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_creacion']
        verbose_name = 'Comentario'
        verbose_name_plural = 'Comentarios'

    def __str__(self):
        return f"{self.autor_nombre} en {self.publicacion.id}"


class TrendingTopic(models.Model):
    categoria = models.CharField(max_length=50) # e.g. TRÁFICO, SERVICIOS, COMUNIDAD
    hashtag = models.CharField(max_length=100) # e.g. #CorteAvenidaSur
    detalle = models.CharField(max_length=150) # e.g. 45 reportes en la última hora
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = 'Trending Topic'
        verbose_name_plural = 'Trending Topics'

    def __str__(self):
        return f"{self.categoria} - {self.hashtag}"


class ActividadReciente(models.Model):
    TIPO_CHOICES = (
        ('incidente', 'Nuevo Incidente'),
        ('resuelta', 'Incidencia Resuelta'),
        ('aviso', 'Aviso General'),
    )
    titulo = models.CharField(max_length=255)
    tiempo = models.CharField(max_length=50) # e.g. Hace 2 min, Hace 15 min
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='incidente')
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = 'Actividad Reciente'
        verbose_name_plural = 'Actividades Recientes'

    def __str__(self):
        return f"{self.titulo} ({self.tiempo})"
