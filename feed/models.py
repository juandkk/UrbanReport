from django.db import models
from django.conf import settings


class Publicacion(models.Model):
    class EstadoIncidencia(models.TextChoices):
        REPORTADO = 'REPORTADO', 'Reportado'
        EN_PROCESO = 'EN_PROCESO', 'En Proceso'
        RESUELTA = 'RESUELTA', 'Resuelta'
        DECLINADO = 'DECLINADO', 'Declinado'

    class MotivoDeclinacion(models.TextChoices):
        DUPLICADO = 'DUPLICADO', 'Reporte duplicado (ya fue radicado anteriormente)'
        FUERA_COMPETENCIA = 'FUERA_COMPETENCIA', 'Fuera de competencia municipal'
        EVIDENCIA_INSUFICIENTE = 'EVIDENCIA_INSUFICIENTE', 'Información o evidencia insuficiente / imprecisa'
        UBICACION_INEXACTA = 'UBICACION_INEXACTA', 'Ubicación inexacta o no verificable en terreno'
        NO_PROCEDE = 'NO_PROCEDE', 'Incidencia falsa, inexistente o improcedente'
        OTRO = 'OTRO', 'Otro motivo administrativo'

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
    dislikes = models.PositiveIntegerField(default=0)
    censurado = models.BooleanField(default=False)
    motivo_censura = models.CharField(max_length=255, blank=True, default='')
    motivo_declinacion = models.CharField(max_length=255, blank=True, default='')
    estado_incidencia = models.CharField(
        max_length=20,
        choices=EstadoIncidencia.choices,
        default=EstadoIncidencia.REPORTADO
    )
    class Categoria(models.TextChoices):
        VIAS = 'VIAS', 'Vías'
        ALUMBRADO = 'ALUMBRADO', 'Alumbrado'
        PARQUES = 'PARQUES', 'Parques'
        INFRAESTRUCTURA = 'INFRAESTRUCTURA', 'Infraestructura'
        REDES = 'REDES', 'Redes eléctricas y telecomunicaciones'
        ASEO = 'ASEO', 'Aseo y basuras'
        ACUEDUCTO = 'ACUEDUCTO', 'Acueducto y alcantarillado'
        OTROS = 'OTROS', 'Otros'

    titulo = models.CharField(max_length=200, blank=True, default='')
    categoria = models.CharField(
        max_length=30,
        choices=Categoria.choices,
        default=Categoria.VIAS,
        blank=True
    )
    ubicacion = models.CharField(max_length=200, blank=True, null=True)
    latitud = models.DecimalField(
        max_digits=10, decimal_places=7, blank=True, null=True,
        help_text="Latitud geográfica del incidente"
    )
    longitud = models.DecimalField(
        max_digits=10, decimal_places=7, blank=True, null=True,
        help_text="Longitud geográfica del incidente"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Publicación'
        verbose_name_plural = 'Publicaciones'

    def __str__(self):
        return f"{self.autor_nombre or self.autor.username}: {self.contenido[:40]}..."

    @property
    def nombre_autor(self):
        """
        Nombre a mostrar del autor SIEMPRE actualizado: se toma del usuario
        relacionado (first_name/last_name o username). Solo cae a la copia
        `autor_nombre` si la publicación no tiene autor (datos de demo).
        """
        if self.autor_id and self.autor:
            return f"{self.autor.first_name} {self.autor.last_name}".strip() or self.autor.username
        return self.autor_nombre

    @property
    def total_comentarios(self):
        if hasattr(self, '_total_comentarios'):
            return self._total_comentarios
        if '_prefetched_objects_cache' in getattr(self, '__dict__', {}) and 'comentarios' in self._prefetched_objects_cache:
            return len(self._prefetched_objects_cache['comentarios'])
        return self.comentarios.count()

    @property
    def tiempo_relativo(self):
        from django.utils.timesince import timesince
        return timesince(self.fecha_creacion).replace(', ', ',').replace(',', ', ')

    def comentarios_principales(self):
        """Retorna solo comentarios raíz (sin padre) para estructurar el hilo."""
        if '_prefetched_objects_cache' in getattr(self, '__dict__', {}) and 'comentarios' in self._prefetched_objects_cache:
            return [c for c in self._prefetched_objects_cache['comentarios'] if c.padre_id is None]
        return self.comentarios.filter(padre__isnull=True).prefetch_related('respuestas')

    @property
    def total_reposteos(self):
        if hasattr(self, '_total_reposteos'):
            return self._total_reposteos
        if '_prefetched_objects_cache' in getattr(self, '__dict__', {}) and 'reposteos' in self._prefetched_objects_cache:
            return len(self._prefetched_objects_cache['reposteos'])
        return self.reposteos.count()


class Comentario(models.Model):
    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        related_name='comentarios'
    )
    padre = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='respuestas'
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    autor_nombre = models.CharField(max_length=100)
    texto = models.TextField(blank=True, default='')
    imagen = models.ImageField(upload_to='comentarios/', blank=True, null=True)
    likes = models.PositiveIntegerField(default=0)
    dislikes = models.PositiveIntegerField(default=0)
    censurado = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_creacion']
        verbose_name = 'Comentario'
        verbose_name_plural = 'Comentarios'

    def __str__(self):
        if self.padre:
            return f"Respuesta de {self.autor_nombre} a #{self.padre_id}"
        return f"{self.autor_nombre} en #{self.publicacion_id}"

    @property
    def nombre_autor(self):
        """Nombre a mostrar del autor del comentario, siempre actualizado."""
        if self.autor_id and self.autor:
            return f"{self.autor.first_name} {self.autor.last_name}".strip() or self.autor.username
        return self.autor_nombre

    @property
    def total_respuestas(self):
        if '_prefetched_objects_cache' in getattr(self, '__dict__', {}) and 'respuestas' in self._prefetched_objects_cache:
            return len(self._prefetched_objects_cache['respuestas'])
        return self.respuestas.count()

    @property
    def tiempo_relativo(self):
        from django.utils.timesince import timesince
        return timesince(self.fecha_creacion).replace(', ', ',').replace(',', ', ')


class Reposteo(models.Model):
    """Un usuario republica (repostea) una publicación. Es una relación, no una copia."""
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reposteos'
    )
    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        related_name='reposteos'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'publicacion')
        ordering = ['-fecha_creacion']
        verbose_name = 'Reposteo'
        verbose_name_plural = 'Reposteos'

    def __str__(self):
        return f"{self.usuario.username} reposteó Post #{self.publicacion_id}"


class ReaccionPublicacion(models.Model):
    class TipoReaccion(models.TextChoices):
        LIKE = 'LIKE', 'Like'
        DISLIKE = 'DISLIKE', 'Dislike'

    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        related_name='reacciones'
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reacciones_publicaciones'
    )
    tipo = models.CharField(max_length=10, choices=TipoReaccion.choices)
    fecha_creacion = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('publicacion', 'usuario')
        verbose_name = 'Reacción a Publicación'
        verbose_name_plural = 'Reacciones a Publicaciones'

    def __str__(self):
        return f"{self.usuario.username} -> {self.tipo} en Post #{self.publicacion_id}"


class ReaccionComentario(models.Model):
    class TipoReaccion(models.TextChoices):
        LIKE = 'LIKE', 'Like'
        DISLIKE = 'DISLIKE', 'Dislike'

    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        related_name='reacciones'
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reacciones_comentarios'
    )
    tipo = models.CharField(max_length=10, choices=TipoReaccion.choices)
    fecha_creacion = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('comentario', 'usuario')
        verbose_name = 'Reacción a Comentario'
        verbose_name_plural = 'Reacciones a Comentarios'

    def __str__(self):
        return f"{self.usuario.username} -> {self.tipo} en Comentario #{self.comentario_id}"


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


class ReporteContenido(models.Model):
    class Motivo(models.TextChoices):
        SPAM = 'SPAM', 'Spam o publicidad no deseada'
        OFENSIVO = 'OFENSIVO', 'Contenido ofensivo o acoso'
        FALSO = 'FALSO', 'Información falsa o engañosa'
        INAPROPIADO = 'INAPROPIADO', 'Contenido inapropiado para la comunidad'
        OTRO = 'OTRO', 'Otro motivo'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reportes_enviados'
    )
    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reportes'
    )
    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reportes'
    )
    motivo = models.CharField(
        max_length=20,
        choices=Motivo.choices,
        default=Motivo.INAPROPIADO
    )
    descripcion = models.TextField(blank=True, default='')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Reporte de Contenido'
        verbose_name_plural = 'Reportes de Contenido'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'publicacion'],
                condition=models.Q(publicacion__isnull=False),
                name='unique_user_reporte_publicacion'
            ),
            models.UniqueConstraint(
                fields=['usuario', 'comentario'],
                condition=models.Q(comentario__isnull=False),
                name='unique_user_reporte_comentario'
            ),
        ]

    def __str__(self):
        obj = f"Post #{self.publicacion_id}" if self.publicacion else f"Comentario #{self.comentario_id}"
        return f"Reporte de {self.usuario.username} sobre {obj} ({self.get_motivo_display()})"


class Notificacion(models.Model):
    """
    Notificación dirigida a un usuario (destinatario) generada por la actividad
    de otro (actor) sobre su contenido: comentarios, reacciones o cambios de
    estado de sus reportes.
    """
    class Tipo(models.TextChoices):
        COMENTARIO = 'COMENTARIO', 'Comentó en tu publicación'
        RESPUESTA = 'RESPUESTA', 'Respondió a tu comentario'
        LIKE = 'LIKE', 'Le dio Me Gusta a tu publicación'
        CAMBIO_ESTADO = 'CAMBIO_ESTADO', 'Tu reporte cambió de estado'
        SEGUIDOR = 'SEGUIDOR', 'Comenzó a seguirte'
        REPORTE_CONTENIDO = 'REPORTE_CONTENIDO', 'Reportó contenido para moderación'

    # Categoría para el filtro de la vista: publicaciones, reportes o social
    class Categoria(models.TextChoices):
        PUBLICACION = 'PUBLICACION', 'Publicación'
        REPORTE = 'REPORTE', 'Reporte'
        SOCIAL = 'SOCIAL', 'Social'

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notificaciones'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notificaciones_generadas'
    )
    actor_nombre = models.CharField(max_length=150, blank=True, default='')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    categoria = models.CharField(
        max_length=20,
        choices=Categoria.choices,
        default=Categoria.PUBLICACION
    )
    publicacion = models.ForeignKey(
        Publicacion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notificaciones'
    )
    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notificaciones'
    )
    # Texto extra: fragmento del comentario, estado nuevo, motivo del reporte, etc.
    extra = models.CharField(max_length=255, blank=True, default='')
    leido = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'

    def __str__(self):
        return f"Para {self.destinatario.username}: {self.get_tipo_display()} ({self.actor_nombre})"

    @property
    def nombre_actor(self):
        """
        Nombre a mostrar del actor SIEMPRE actualizado: se toma del usuario
        relacionado (first_name/last_name o username). Solo cae a la copia
        `actor_nombre` si la notificación no tiene actor (datos de sistema/demo).
        Así, si el usuario cambia su nombre, las notificaciones ya creadas
        reflejan el nombre nuevo.
        """
        if self.actor_id and self.actor:
            return f"{self.actor.first_name} {self.actor.last_name}".strip() or self.actor.username
        return self.actor_nombre

