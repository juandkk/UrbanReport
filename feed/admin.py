from django.contrib import admin
from .models import Publicacion, Comentario, TrendingTopic, ActividadReciente


class ComentarioInline(admin.TabularInline):
    model = Comentario
    extra = 1


@admin.register(Publicacion)
class PublicacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'autor_nombre', 'contenido_corto', 'likes', 'estado_incidencia', 'fecha_creacion')
    list_filter = ('estado_incidencia', 'fecha_creacion')
    search_fields = ('autor_nombre', 'contenido', 'ubicacion')
    inlines = [ComentarioInline]

    def contenido_corto(self, obj):
        return obj.contenido[:50]
    contenido_corto.short_description = 'Contenido'


@admin.register(TrendingTopic)
class TrendingTopicAdmin(admin.ModelAdmin):
    list_display = ('hashtag', 'categoria', 'detalle', 'orden')
    list_editable = ('orden',)


@admin.register(ActividadReciente)
class ActividadRecienteAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tiempo', 'tipo', 'orden')
    list_editable = ('orden',)
