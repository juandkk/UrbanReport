from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.utils.timesince import timesince
from django.utils import timezone
from django.db.models import Count, Q
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from datetime import timedelta
from collections import Counter
import io
import re
from PIL import Image, UnidentifiedImageError
from .models import (
    Publicacion, Comentario, TrendingTopic, ActividadReciente,
    ReaccionPublicacion, ReaccionComentario, ReporteContenido, Notificacion, Reposteo
)
from usuarios.models import Usuario


def crear_notificacion(destinatario, actor, tipo, publicacion=None, comentario=None, categoria=None, extra=''):
    """
    Crea una notificación para 'destinatario' generada por 'actor'.
    No hace nada si el actor es el mismo destinatario (no te notificas a ti mismo)
    o si no hay destinatario válido.
    """
    if destinatario is None or actor is None or destinatario == actor:
        return None

    if categoria is None:
        if tipo in (Notificacion.Tipo.CAMBIO_ESTADO, Notificacion.Tipo.REPORTE_CONTENIDO):
            categoria = Notificacion.Categoria.REPORTE
        elif tipo == Notificacion.Tipo.SEGUIDOR:
            categoria = Notificacion.Categoria.SOCIAL
        else:
            categoria = Notificacion.Categoria.PUBLICACION

    actor_nombre = f"{actor.first_name} {actor.last_name}".strip() or actor.username
    return Notificacion.objects.create(
        destinatario=destinatario,
        actor=actor,
        actor_nombre=actor_nombre,
        tipo=tipo,
        categoria=categoria,
        publicacion=publicacion,
        comentario=comentario,
        extra=extra[:255],
    )


def notificar_admins_reporte(actor, motivo_display, publicacion=None, comentario=None):
    """
    Notifica a TODOS los administradores que un usuario reportó contenido, para que
    puedan revisarlo y moderar. No notifica al propio actor si fuese admin.
    """
    admins = Usuario.objects.filter(
        Q(rol=Usuario.Rol.ADMINISTRADOR) | Q(is_staff=True) | Q(is_superuser=True)
    ).distinct()
    creadas = 0
    for admin in admins:
        if admin == actor:
            continue
        crear_notificacion(
            destinatario=admin, actor=actor,
            tipo=Notificacion.Tipo.REPORTE_CONTENIDO,
            publicacion=publicacion, comentario=comentario,
            extra=motivo_display,
        )
        creadas += 1
    return creadas


@login_required
def mapa_view(request):
    """Renders the interactive map page."""
    context = {
        'active_menu': 'mapa',
    }
    return render(request, 'feed/mapa.html', context)


@login_required
def api_incidentes_mapa(request):
    """JSON API endpoint returning geolocated incidents for the map."""
    estado = request.GET.get('estado', '')

    incidentes = Publicacion.objects.filter(
        latitud__isnull=False,
        longitud__isnull=False,
    )

    if estado and estado != 'TODOS':
        incidentes = incidentes.filter(estado_incidencia=estado)

    data = []
    for inc in incidentes:
        data.append({
            'id': inc.id,
            'titulo': inc.titulo or 'Incidencia Urbana',
            'categoria': inc.categoria,
            'categoria_display': inc.get_categoria_display() if hasattr(inc, 'get_categoria_display') else inc.categoria,
            'latitud': float(inc.latitud),
            'longitud': float(inc.longitud),
            'contenido': inc.contenido,
            'ubicacion': inc.ubicacion or '',
            'estado': inc.estado_incidencia,
            'estado_display': inc.get_estado_incidencia_display(),
            'autor': inc.autor_nombre,
            'likes': inc.likes,
            'comentarios': inc.total_comentarios,
            'tiempo': timesince(inc.fecha_creacion) + ' atrás',
            'imagen_url': inc.imagen.url if inc.imagen else None,
        })

    return JsonResponse({'incidentes': data})


# ── Límites geográficos de Medellín ──
# Bounding box que cubre el municipio de Medellín (16 comunas + corregimientos),
# sin abarcar municipios vecinos como Bello, Itagüí o Envigado. Solo se permite
# radicar incidencias cuyo pin caiga dentro de este rango.
MEDELLIN_BOUNDS = {
    'lat_min': 6.19,
    'lat_max': 6.31,
    'lng_min': -75.64,
    'lng_max': -75.53,
}


def coordenadas_en_medellin(lat, lng):
    """Devuelve True si (lat, lng) cae dentro de los límites de Medellín."""
    return (
        MEDELLIN_BOUNDS['lat_min'] <= lat <= MEDELLIN_BOUNDS['lat_max']
        and MEDELLIN_BOUNDS['lng_min'] <= lng <= MEDELLIN_BOUNDS['lng_max']
    )


# ── Sanitización de imágenes ──
# Solo se aceptan PNG y JPG. Límite de tamaño (bytes) para evitar cargas abusivas.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
# Formatos permitidos (detectados por Pillow, NO por extensión) y su normalización de salida
_FORMATOS_PERMITIDOS = {'JPEG', 'PNG'}


class ImagenInvalida(Exception):
    """Se lanza cuando la imagen no supera las validaciones de seguridad."""
    pass


def sanitizar_imagen(archivo):
    """
    Valida y neutraliza una imagen subida por el usuario.

    Seguridad:
      1. Rechaza archivos que superen el tamaño máximo.
      2. Verifica con Pillow que el contenido ES realmente una imagen (verify()),
         detectando el formato REAL, no confiando en la extensión ni el mimetype.
      3. Solo admite PNG y JPEG.
      4. RE-CODIFICA la imagen desde sus píxeles a un archivo limpio. Esto descarta
         cualquier carga maliciosa embebida (scripts, polyglots, metadatos EXIF con
         payloads, bytes extra tras el fin de la imagen, etc.), ya que la salida se
         reconstruye únicamente a partir de los datos de imagen decodificados.

    Devuelve un ContentFile listo para asignar al ImageField, o lanza ImagenInvalida.
    """
    if archivo is None:
        return None

    # 1. Tamaño
    if archivo.size > MAX_IMAGE_BYTES:
        raise ImagenInvalida('La imagen supera el tamaño máximo permitido (8 MB).')

    # Leer todos los bytes una sola vez
    datos = archivo.read()

    # 2 y 3. Verificar que es una imagen real y de formato permitido
    try:
        with Image.open(io.BytesIO(datos)) as img_check:
            img_check.verify()  # Detecta archivos corruptos o que no son imágenes
            formato = (img_check.format or '').upper()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImagenInvalida('El archivo no es una imagen válida.')

    if formato not in _FORMATOS_PERMITIDOS:
        raise ImagenInvalida('Formato no permitido. Solo se aceptan imágenes PNG o JPG.')

    # 4. Re-abrir (verify() invalida el objeto) y re-codificar limpiamente
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImagenInvalida('No se pudo procesar la imagen.')

    buffer = io.BytesIO()
    nombre_base = (archivo.name.rsplit('.', 1)[0] if archivo.name else 'evidencia')[:60]

    if formato == 'PNG':
        # Conservar transparencia si existe
        if img.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            img = img.convert('RGBA')
        img.save(buffer, format='PNG', optimize=True)
        extension = 'png'
    else:  # JPEG
        # JPEG no soporta canal alfa: aplanar sobre fondo blanco
        if img.mode in ('RGBA', 'LA', 'P'):
            fondo = Image.new('RGB', img.size, (255, 255, 255))
            img_rgba = img.convert('RGBA')
            fondo.paste(img_rgba, mask=img_rgba.split()[-1])
            img = fondo
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        # Re-guardar sin metadatos EXIF (no se copian por defecto)
        img.save(buffer, format='JPEG', quality=85, optimize=True)
        extension = 'jpg'

    buffer.seek(0)
    return ContentFile(buffer.read(), name=f"{nombre_base}.{extension}")


@login_required
@require_POST
def radicar_incidencia_ajax(request):
    """Endpoint to record a new incident with title, category, coords, and evidence."""
    titulo = request.POST.get('titulo', '').strip()
    categoria = request.POST.get('categoria', 'VIAS').strip()
    contenido = request.POST.get('contenido', '').strip()
    ubicacion = request.POST.get('ubicacion', '').strip()
    latitud_raw = request.POST.get('latitud', '').strip()
    longitud_raw = request.POST.get('longitud', '').strip()
    ubicacion_fijada = request.POST.get('ubicacion_fijada', '').strip().lower() in ('1', 'true', 'si', 'sí')
    imagen = request.FILES.get('imagen')

    if not contenido:
        if titulo:
            contenido = titulo
        else:
            return JsonResponse({'status': 'error', 'message': 'Por favor ingrese una descripción del incidente.'}, status=400)

    # ── Ubicación obligatoria ──
    # Se exigen coordenadas válidas Y que el usuario haya fijado explícitamente el
    # punto (clic/arrastre en el mapa, "Mi ubicación" o búsqueda de dirección).
    try:
        latitud = round(float(latitud_raw), 7)
        longitud = round(float(longitud_raw), 7)
    except (ValueError, TypeError):
        return JsonResponse({
            'status': 'error',
            'message': 'Debe seleccionar una ubicación en el mapa antes de radicar la incidencia.'
        }, status=400)

    if not ubicacion_fijada or not ubicacion:
        return JsonResponse({
            'status': 'error',
            'message': 'La ubicación es obligatoria. Marque el punto en el mapa o busque una dirección.'
        }, status=400)

    # Rango geográfico válido (sanidad básica de coordenadas)
    if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
        return JsonResponse({
            'status': 'error',
            'message': 'Las coordenadas de la ubicación no son válidas.'
        }, status=400)

    # ── Restricción a Medellín ──
    # Solo se admiten incidencias ubicadas dentro de los límites de Medellín.
    if not coordenadas_en_medellin(latitud, longitud):
        return JsonResponse({
            'status': 'error',
            'message': 'La ubicación debe estar dentro de Medellín. Selecciona un punto dentro de la ciudad.'
        }, status=400)

    # ── Validación y sanitización de la evidencia fotográfica ──
    imagen_limpia = None
    if imagen is not None:
        try:
            imagen_limpia = sanitizar_imagen(imagen)
        except ImagenInvalida as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    user = request.user
    autor_nombre = f"{user.first_name} {user.last_name}".strip() or user.username

    publicacion = Publicacion.objects.create(
        autor=user,
        autor_nombre=autor_nombre,
        titulo=titulo,
        categoria=categoria,
        contenido=contenido,
        ubicacion=ubicacion,
        latitud=latitud,
        longitud=longitud,
        imagen=imagen_limpia,
        estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO
    )

    registrar_actividad_anti_saturacion(
        titulo=f"Nuevo reporte ({publicacion.get_categoria_display()}): {titulo or contenido[:30]}",
        tipo='incidente',
        tiempo="Hace un momento"
    )

    return JsonResponse({
        'status': 'ok',
        'message': '¡Incidencia radicada exitosamente!',
        'incidente': {
            'id': publicacion.id,
            'titulo': publicacion.titulo or 'Incidencia Urbana',
            'categoria': publicacion.categoria,
            'categoria_display': publicacion.get_categoria_display(),
            'latitud': float(publicacion.latitud),
            'longitud': float(publicacion.longitud),
            'contenido': publicacion.contenido,
            'ubicacion': publicacion.ubicacion or '',
            'estado': publicacion.estado_incidencia,
            'estado_display': publicacion.get_estado_incidencia_display(),
            'autor': publicacion.autor_nombre,
            'likes': 0,
            'comentarios': 0,
            'tiempo': 'Hace un momento',
            'imagen_url': publicacion.imagen.url if publicacion.imagen else None,
        }
    })


def registrar_actividad_anti_saturacion(titulo, tipo='incidente', tiempo='Hace un momento'):
    """
    OBSOLETO: la "Actividad Reciente" ya no se persiste en una tabla aparte.
    Ahora se deriva directamente de las publicaciones vivas (ver
    obtener_actividades_recientes_balanceadas), de modo que el tiempo mostrado es
    real y las publicaciones eliminadas desaparecen automáticamente de la cola.

    Se conserva como no-op para no romper las llamadas existentes.
    """
    return None


def _actividad_desde_publicacion(pub):
    """
    Construye un diccionario de 'Actividad Reciente' a partir de una Publicacion real.
    El tiempo se calcula dinámicamente con timesince (hora real de publicación) y el
    identificador es estable (basado en el id de la publicación) para que el frontend
    pueda reconciliar y, si la publicación se elimina, retirarla de la cola.
    """
    es_resuelta = pub.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA
    tipo = 'resuelta' if es_resuelta else 'incidente'

    if es_resuelta:
        titulo = f"Incidencia #{pub.id} marcada como Resuelta."
    else:
        categoria = pub.get_categoria_display() if hasattr(pub, 'get_categoria_display') else pub.categoria
        detalle = (pub.titulo or pub.contenido or '').strip()[:40] or 'Incidencia urbana'
        titulo = f"Nuevo reporte ({categoria}): {detalle}"

    return {
        'id': f"pub-{tipo}-{pub.id}",
        'publicacion_id': pub.id,
        'titulo': titulo,
        'tiempo': pub.tiempo_relativo + ' atrás',
        'tipo': tipo,
        'orden_fecha': pub.fecha_creacion.timestamp(),
    }


def obtener_actividades_recientes_balanceadas():
    """
    Retorna exactamente las 6 actividades (3 no resueltas + 3 resueltas) derivadas
    DIRECTAMENTE de las publicaciones reales, ordenadas por fecha de creación
    descendente. Al estar basadas en las publicaciones vivas:
      - El tiempo mostrado es la hora real de publicación (timesince).
      - Si una publicación se elimina, desaparece automáticamente de la cola.
    """
    sin_resolver = list(
        Publicacion.objects.filter(
            estado_incidencia__in=[
                Publicacion.EstadoIncidencia.REPORTADO,
                Publicacion.EstadoIncidencia.EN_PROCESO,
            ]
        ).order_by('-fecha_creacion', '-id')[:3]
    )
    resueltas = list(
        Publicacion.objects.filter(
            estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA
        ).order_by('-fecha_creacion', '-id')[:3]
    )

    actividades = [_actividad_desde_publicacion(p) for p in sin_resolver]
    actividades += [_actividad_desde_publicacion(p) for p in resueltas]

    # Ordenar la lista combinada por fecha real (más reciente primero)
    actividades.sort(key=lambda a: a['orden_fecha'], reverse=True)
    return actividades


# Etiquetas legibles y hashtags derivados para cada categoría de incidencia
_CATEGORIA_HASHTAG = {
    'VIAS': '#Vias',
    'ALUMBRADO': '#Alumbrado',
    'PARQUES': '#Parques',
    'INFRAESTRUCTURA': '#Infraestructura',
}

# Etiqueta de "sección" mostrada en el widget según el tipo de tendencia
_CATEGORIA_SECCION = {
    'VIAS': 'MOVILIDAD',
    'ALUMBRADO': 'SERVICIOS',
    'PARQUES': 'COMUNIDAD',
    'INFRAESTRUCTURA': 'INFRAESTRUCTURA',
}

# Regex para extraer hashtags reales escritos por los usuarios (#PalabraClave)
_HASHTAG_RE = re.compile(r'#(\w{2,40})', re.UNICODE)


def _plural_reportes(n):
    return f"{n} reporte" + ("" if n == 1 else "s")


def calcular_trending_topics(limite=5, horas=48):
    """
    Calcula los Trending Topics REALES a partir de las publicaciones.

    Combina dos señales:
      1. Categorías con más reportes (campo estructurado, fiable).
      2. Hashtags escritos por los usuarios (#texto) en título/contenido.

    Usa una ventana reciente (por defecto 48h); si no hay nada en ese rango,
    cae de forma automática a considerar todas las publicaciones. Devuelve una
    lista de dicts lista para la plantilla y el endpoint JSON.
    """
    desde = timezone.now() - timedelta(hours=horas)
    qs = Publicacion.objects.filter(fecha_creacion__gte=desde)
    if not qs.exists():
        # Fallback: sin actividad reciente, usar el histórico completo
        qs = Publicacion.objects.all()

    tendencias = []

    # ── 1. Tendencias por categoría ──
    por_categoria = (
        qs.values('categoria')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    for row in por_categoria:
        cat = row['categoria'] or 'VIAS'
        total = row['total']
        if total <= 0:
            continue
        tendencias.append({
            'tipo': 'categoria',
            'clave': cat,
            'categoria': _CATEGORIA_SECCION.get(cat, 'GENERAL'),
            'hashtag': _CATEGORIA_HASHTAG.get(cat, f"#{cat.title()}"),
            'detalle': f"{_plural_reportes(total)} recientes",
            'total': total,
        })

    # ── 2. Tendencias por hashtag escrito por usuarios ──
    contador = Counter()
    for titulo, contenido in qs.values_list('titulo', 'contenido'):
        texto = f"{titulo or ''} {contenido or ''}"
        for match in _HASHTAG_RE.findall(texto):
            contador[match.lower()] += 1

    for palabra, total in contador.most_common(limite):
        tendencias.append({
            'tipo': 'hashtag',
            'clave': palabra,
            'categoria': 'TENDENCIA',
            'hashtag': f"#{palabra}",
            'detalle': f"{_plural_reportes(total)}",
            'total': total,
        })

    # Ordenar todo por cantidad y recortar al límite
    tendencias.sort(key=lambda t: t['total'], reverse=True)
    return tendencias[:limite]


@login_required
def api_trending_topics(request):
    """Devuelve los Trending Topics calculados en vivo para el refresco del widget."""
    topics = calcular_trending_topics()
    return JsonResponse({'status': 'ok', 'trending_topics': topics})


@login_required
def detalle_publicacion_view(request, publicacion_id):
    """
    Vista de detalle de una publicación (tipo Facebook): muestra la publicación
    completa con TODOS sus comentarios. Reutiliza post_card.html en modo 'detalle'.
    """
    publicacion = get_object_or_404(
        Publicacion.objects.prefetch_related('comentarios__respuestas', 'comentarios__autor', 'autor'),
        id=publicacion_id
    )

    # Reacciones y reposteo del usuario para colorear los botones (como en el feed)
    reaccion = ReaccionPublicacion.objects.filter(publicacion=publicacion, usuario=request.user).first()
    publicacion.user_reaction = reaccion.tipo if reaccion else None
    publicacion.user_reposteo = Reposteo.objects.filter(publicacion=publicacion, usuario=request.user).exists()

    comment_ids = []
    for c in publicacion.comentarios.all():
        comment_ids.append(c.id)
    user_comment_reactions = {}
    if comment_ids:
        for r in ReaccionComentario.objects.filter(usuario=request.user, comentario_id__in=comment_ids):
            user_comment_reactions[r.comentario_id] = r.tipo
    for c in publicacion.comentarios.all():
        c.user_reaction = user_comment_reactions.get(c.id)
        for rep in c.respuestas.all():
            rep.user_reaction = user_comment_reactions.get(rep.id)

    context = {
        'post': publicacion,
        'active_menu': 'feed',
    }
    return render(request, 'feed/detalle_publicacion.html', context)


@login_required
def feed_comunitario_view(request):
    # Seed sample data if empty so UI looks 100% complete and identical to designs
    if not Publicacion.objects.exists():
        _seed_demo_data()

    # El feed comunitario muestra TODAS las publicaciones recientes disponibles (sin limitación)
    publicaciones = list(Publicacion.objects.all().order_by('-id').prefetch_related(
        'comentarios__respuestas', 'comentarios__autor', 'autor'
    ))
    # Trending Topics calculados en vivo desde las publicaciones (categorías + hashtags)
    trending_topics = calcular_trending_topics()

    # El apartado 'Actividad Reciente' mantiene estrictamente 6 cupos (3 no resueltos + 3 resueltos)
    actividades = obtener_actividades_recientes_balanceadas()

    # Mapear reacciones del usuario actual para colorear botones (Like / Dislike)
    user_post_reactions = {}
    user_comment_reactions = {}
    user_reposts = set()
    if request.user.is_authenticated:
        for r in ReaccionPublicacion.objects.filter(usuario=request.user, publicacion__in=publicaciones):
            user_post_reactions[r.publicacion_id] = r.tipo
        user_reposts = set(
            Reposteo.objects.filter(usuario=request.user, publicacion__in=publicaciones)
            .values_list('publicacion_id', flat=True)
        )
        all_comment_ids = []
        for p in publicaciones:
            for c in p.comentarios.all():
                all_comment_ids.append(c.id)
        if all_comment_ids:
            for r in ReaccionComentario.objects.filter(usuario=request.user, comentario_id__in=all_comment_ids):
                user_comment_reactions[r.comentario_id] = r.tipo

    for p in publicaciones:
        p.user_reaction = user_post_reactions.get(p.id)
        p.user_reposteo = p.id in user_reposts
        for c in p.comentarios.all():
            c.user_reaction = user_comment_reactions.get(c.id)
            for rep in c.respuestas.all():
                rep.user_reaction = user_comment_reactions.get(rep.id)

    # Form handling for new community post
    if request.method == 'POST':
        contenido = request.POST.get('contenido', '').strip()
        titulo = request.POST.get('titulo', '').strip()
        categoria = request.POST.get('categoria', 'VIAS').strip()
        imagen = request.FILES.get('imagen')
        # Sanitizar imagen también en el formulario clásico; si no es válida, se descarta
        imagen_limpia = None
        if imagen is not None:
            try:
                imagen_limpia = sanitizar_imagen(imagen)
            except ImagenInvalida:
                imagen_limpia = None
        if contenido or titulo:
            user = request.user
            autor_nombre = f"{user.first_name} {user.last_name}".strip() or user.username

            pub = Publicacion.objects.create(
                autor=user,
                autor_nombre=autor_nombre,
                titulo=titulo,
                categoria=categoria,
                contenido=contenido or titulo,
                imagen=imagen_limpia,
                estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO
            )
            # Registrar actividad con anti-saturación (3 no resueltos máx.)
            registrar_actividad_anti_saturacion(
                f"Nuevo reporte ({pub.get_categoria_display()}): {titulo or contenido[:32]}",
                tipo='incidente'
            )
            return redirect('feed_comunitario')

    context = {
        'publicaciones': publicaciones,
        'trending_topics': trending_topics,
        'actividades': actividades,
        'active_menu': 'feed',
    }
    return render(request, 'feed/feed_comunitario.html', context)


@login_required
@require_POST
def reaccionar_publicacion_ajax(request, publicacion_id):
    """Permite dar LIKE o DISLIKE a una publicación. Solo se puede reaccionar una vez por usuario."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    tipo = request.POST.get('tipo', 'LIKE').upper()
    if tipo not in [ReaccionPublicacion.TipoReaccion.LIKE, ReaccionPublicacion.TipoReaccion.DISLIKE]:
        return JsonResponse({'status': 'error', 'message': 'Tipo de reacción inválido.'}, status=400)

    reaccion = ReaccionPublicacion.objects.filter(publicacion=publicacion, usuario=request.user).first()
    user_reaction = None

    if reaccion:
        if reaccion.tipo == tipo:
            # Si presiona el mismo botón, se desmarca (toggle off)
            if tipo == ReaccionPublicacion.TipoReaccion.LIKE:
                publicacion.likes = max(0, publicacion.likes - 1)
            else:
                publicacion.dislikes = max(0, publicacion.dislikes - 1)
            reaccion.delete()
            user_reaction = None
        else:
            # Si cambia de reacción (de like a dislike o viceversa)
            if tipo == ReaccionPublicacion.TipoReaccion.LIKE:
                publicacion.dislikes = max(0, publicacion.dislikes - 1)
                publicacion.likes += 1
            else:
                publicacion.likes = max(0, publicacion.likes - 1)
                publicacion.dislikes += 1
            reaccion.tipo = tipo
            reaccion.save(update_fields=['tipo'])
            user_reaction = tipo
    else:
        # Reacción nueva
        ReaccionPublicacion.objects.create(publicacion=publicacion, usuario=request.user, tipo=tipo)
        if tipo == ReaccionPublicacion.TipoReaccion.LIKE:
            publicacion.likes += 1
            # Notificar solo cuando alguien da Me Gusta (no en dislikes)
            crear_notificacion(
                destinatario=publicacion.autor, actor=request.user,
                tipo=Notificacion.Tipo.LIKE, publicacion=publicacion,
            )
        else:
            publicacion.dislikes += 1
        user_reaction = tipo

    publicacion.save(update_fields=['likes', 'dislikes'])
    return JsonResponse({
        'status': 'ok',
        'likes': publicacion.likes,
        'dislikes': publicacion.dislikes,
        'user_reaction': user_reaction
    })


# Mantener compatibilidad con llamadas anteriores a like
@login_required
@require_POST
def dar_like_ajax(request, publicacion_id):
    return reaccionar_publicacion_ajax(request, publicacion_id)


@login_required
@require_POST
def reaccionar_comentario_ajax(request, comentario_id):
    """Permite dar LIKE o DISLIKE a un comentario o respuesta. Solo se puede reaccionar una vez por usuario."""
    comentario = get_object_or_404(Comentario, id=comentario_id)
    tipo = request.POST.get('tipo', 'LIKE').upper()
    if tipo not in [ReaccionComentario.TipoReaccion.LIKE, ReaccionComentario.TipoReaccion.DISLIKE]:
        return JsonResponse({'status': 'error', 'message': 'Tipo de reacción inválido.'}, status=400)

    reaccion = ReaccionComentario.objects.filter(comentario=comentario, usuario=request.user).first()
    user_reaction = None

    if reaccion:
        if reaccion.tipo == tipo:
            # Desmarcar reacción
            if tipo == ReaccionComentario.TipoReaccion.LIKE:
                comentario.likes = max(0, comentario.likes - 1)
            else:
                comentario.dislikes = max(0, comentario.dislikes - 1)
            reaccion.delete()
            user_reaction = None
        else:
            # Cambiar reacción
            if tipo == ReaccionComentario.TipoReaccion.LIKE:
                comentario.dislikes = max(0, comentario.dislikes - 1)
                comentario.likes += 1
            else:
                comentario.likes = max(0, comentario.likes - 1)
                comentario.dislikes += 1
            reaccion.tipo = tipo
            reaccion.save(update_fields=['tipo'])
            user_reaction = tipo
    else:
        # Reacción nueva
        ReaccionComentario.objects.create(comentario=comentario, usuario=request.user, tipo=tipo)
        if tipo == ReaccionComentario.TipoReaccion.LIKE:
            comentario.likes += 1
            crear_notificacion(
                destinatario=comentario.autor, actor=request.user,
                tipo=Notificacion.Tipo.LIKE, publicacion=comentario.publicacion,
                comentario=comentario, extra=comentario.texto[:80],
            )
        else:
            comentario.dislikes += 1
        user_reaction = tipo

    comentario.save(update_fields=['likes', 'dislikes'])
    return JsonResponse({
        'status': 'ok',
        'likes': comentario.likes,
        'dislikes': comentario.dislikes,
        'user_reaction': user_reaction
    })


@login_required
@require_POST
def toggle_repost_ajax(request, publicacion_id):
    """Repostea / quita el reposteo de una publicación (toggle, estilo Twitter/X)."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)

    reposteo = Reposteo.objects.filter(usuario=request.user, publicacion=publicacion).first()
    if reposteo:
        reposteo.delete()
        reposteado = False
    else:
        Reposteo.objects.create(usuario=request.user, publicacion=publicacion)
        reposteado = True

    return JsonResponse({
        'status': 'ok',
        'reposteado': reposteado,
        'total_reposteos': publicacion.total_reposteos,
        'message': '¡Publicación reposteada!' if reposteado else 'Reposteo eliminado.',
    })


@login_required
@require_POST
def agregar_comentario_ajax(request, publicacion_id):
    """Crea un comentario en la publicación o una respuesta anidada si se especifica padre_id."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    texto = request.POST.get('texto', '').strip()
    padre_id = request.POST.get('padre_id')

    if not texto:
        return JsonResponse({'status': 'error', 'message': 'El comentario no puede estar vacío.'}, status=400)

    padre = None
    if padre_id:
        padre = get_object_or_404(Comentario, id=padre_id, publicacion=publicacion)

    autor = request.user
    autor_nombre = f"{autor.first_name} {autor.last_name}".strip() or autor.username

    comentario = Comentario.objects.create(
        publicacion=publicacion,
        padre=padre,
        autor=autor,
        autor_nombre=autor_nombre,
        texto=texto
    )

    # Notificar: si es respuesta, al autor del comentario padre; si no, al autor de la publicación
    fragmento = texto[:80]
    if padre and padre.autor:
        crear_notificacion(
            destinatario=padre.autor, actor=autor,
            tipo=Notificacion.Tipo.RESPUESTA, publicacion=publicacion, comentario=comentario, extra=fragmento,
        )
    else:
        crear_notificacion(
            destinatario=publicacion.autor, actor=autor,
            tipo=Notificacion.Tipo.COMENTARIO, publicacion=publicacion, comentario=comentario, extra=fragmento,
        )

    initials = "".join([part[0].upper() for part in autor_nombre.split()[:2]]) or "UR"

    return JsonResponse({
        'status': 'ok',
        'comentario': {
            'id': comentario.id,
            'autor_nombre': comentario.autor_nombre,
            'initials': initials,
            'texto': comentario.texto,
            'tiempo': 'Hace un momento',
            'padre_id': comentario.padre_id,
            'likes': 0,
            'dislikes': 0,
            'total_respuestas': 0
        },
        'total_comentarios': publicacion.comentarios.count()
    })


@login_required
@require_POST
def reportar_publicacion_ajax(request, publicacion_id):
    """Permite a cualquier usuario reportar una publicación a los administradores."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    motivo = request.POST.get('motivo', ReporteContenido.Motivo.INAPROPIADO).strip()
    descripcion = request.POST.get('descripcion', '').strip()

    if ReporteContenido.objects.filter(usuario=request.user, publicacion=publicacion).exists():
        return JsonResponse({
            'status': 'info',
            'message': 'Ya has enviado un reporte para esta publicación previamente.'
        })

    reporte = ReporteContenido.objects.create(
        usuario=request.user,
        publicacion=publicacion,
        motivo=motivo,
        descripcion=descripcion
    )

    # Notificar a los administradores para que revisen y moderen
    notificar_admins_reporte(
        actor=request.user,
        motivo_display=reporte.get_motivo_display(),
        publicacion=publicacion,
    )

    return JsonResponse({
        'status': 'ok',
        'message': '¡Gracias! El reporte ha sido enviado al equipo de moderación.'
    })


@login_required
@require_POST
def reportar_comentario_ajax(request, comentario_id):
    """Permite a cualquier usuario reportar un comentario o respuesta."""
    comentario = get_object_or_404(Comentario, id=comentario_id)
    motivo = request.POST.get('motivo', ReporteContenido.Motivo.INAPROPIADO).strip()
    descripcion = request.POST.get('descripcion', '').strip()

    if ReporteContenido.objects.filter(usuario=request.user, comentario=comentario).exists():
        return JsonResponse({
            'status': 'info',
            'message': 'Ya has enviado un reporte para este comentario previamente.'
        })

    reporte = ReporteContenido.objects.create(
        usuario=request.user,
        comentario=comentario,
        motivo=motivo,
        descripcion=descripcion
    )

    # Notificar a los administradores; enlazamos también la publicación contenedora
    notificar_admins_reporte(
        actor=request.user,
        motivo_display=reporte.get_motivo_display(),
        publicacion=comentario.publicacion,
        comentario=comentario,
    )

    return JsonResponse({
        'status': 'ok',
        'message': '¡Gracias! El comentario ha sido reportado a moderación.'
    })


def _es_admin(user):
    return user.is_authenticated and (user.rol == Usuario.Rol.ADMINISTRADOR or user.is_staff or user.is_superuser)


def _solo_administrador(view_func):
    """
    Decorator que restringe el acceso a usuarios con rol ADMINISTRADOR (o is_staff/superuser).
    Un ciudadano que intente acceder manualmente a la URL recibirá un 403.
    """
    from functools import wraps
    from django.http import HttpResponseForbidden

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not _es_admin(request.user):
            return HttpResponseForbidden(
                '<h2>403 — Acceso denegado</h2>'
                '<p>No tienes permisos para acceder al panel de administrador.</p>'
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


@login_required
def ayuda_view(request):
    """Vista de Ayuda y Preguntas Frecuentes. Accesible para CIUDADANO y ADMINISTRADOR."""
    return render(request, 'feed/ayuda.html', {'active_menu': 'ayuda'})


@login_required
@_solo_administrador
def panel_administrador_view(request):
    """
    Punto de entrada del panel administrador.
    Reutiliza exactamente la misma lógica y template que feed_comunitario,
    con active_menu='panel' para resaltar el ítem correcto en el sidebar.
    El administrador tiene acceso a todas las funciones ciudadanas MÁS
    las herramientas de moderación activadas por _es_admin().
    """
    # Reutilizar toda la lógica del feed comunitario
    if not Publicacion.objects.exists():
        _seed_demo_data()
    _ensure_demo_balance()

    publicaciones = list(Publicacion.objects.all().order_by('-id').prefetch_related(
        'comentarios__respuestas', 'comentarios__autor', 'autor'
    ))
    trending_topics = calcular_trending_topics()
    actividades = obtener_actividades_recientes_balanceadas()

    user_post_reactions = {}
    user_comment_reactions = {}
    for r in ReaccionPublicacion.objects.filter(usuario=request.user, publicacion__in=publicaciones):
        user_post_reactions[r.publicacion_id] = r.tipo
    all_comment_ids = [c.id for p in publicaciones for c in p.comentarios.all()]
    if all_comment_ids:
        for r in ReaccionComentario.objects.filter(usuario=request.user, comentario_id__in=all_comment_ids):
            user_comment_reactions[r.comentario_id] = r.tipo

    for p in publicaciones:
        p.user_reaction = user_post_reactions.get(p.id)
        for c in p.comentarios.all():
            c.user_reaction = user_comment_reactions.get(c.id)
            for rep in c.respuestas.all():
                rep.user_reaction = user_comment_reactions.get(rep.id)

    context = {
        'publicaciones': publicaciones,
        'trending_topics': trending_topics,
        'actividades': actividades,
        'active_menu': 'panel',   # Resalta "Panel" en el sidebar del admin
    }
    return render(request, 'feed/feed_comunitario.html', context)

@login_required
@require_POST
def moderar_publicacion_ajax(request, publicacion_id):
    """Permite a un administrador censurar o eliminar una publicación."""
    if not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permisos de moderación.'}, status=403)

    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    accion = request.POST.get('accion', '').upper().strip()

    if accion == 'ELIMINAR':
        pub_id = publicacion.id
        publicacion.delete()
        return JsonResponse({
            'status': 'ok',
            'accion': 'ELIMINAR',
            'message': 'Publicación eliminada por el administrador.',
            'publicacion_id': pub_id,
            'actividades': obtener_actividades_recientes_balanceadas(),
        })
    elif accion == 'CENSURAR':
        publicacion.censurado = not publicacion.censurado
        if publicacion.censurado:
            motivo = request.POST.get('motivo', 'Incumplimiento de normas comunitarias')
            publicacion.motivo_censura = motivo
        else:
            publicacion.motivo_censura = ''
        publicacion.save(update_fields=['censurado', 'motivo_censura'])
        return JsonResponse({
            'status': 'ok',
            'accion': 'CENSURAR',
            'censurado': publicacion.censurado,
            'message': 'Publicación censurada.' if publicacion.censurado else 'Publicación descensurada.'
        })
    else:
        return JsonResponse({'status': 'error', 'message': 'Acción de moderación no reconocida.'}, status=400)


@login_required
@require_POST
def editar_publicacion_ajax(request, publicacion_id):
    """Permite al autor o a un administrador editar título, categoría y contenido."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    if publicacion.autor != request.user and not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar esta publicación.'}, status=403)

    titulo = request.POST.get('titulo', '').strip()
    contenido = request.POST.get('contenido', '').strip()
    categoria = request.POST.get('categoria', '').strip()

    if not contenido and not titulo:
        return JsonResponse({'status': 'error', 'message': 'El título o la descripción no pueden estar vacíos.'}, status=400)

    publicacion.titulo = titulo
    publicacion.contenido = contenido or titulo
    if categoria in [c[0] for c in Publicacion.Categoria.choices]:
        publicacion.categoria = categoria

    publicacion.save(update_fields=['titulo', 'contenido', 'categoria'])

    return JsonResponse({
        'status': 'ok',
        'message': '¡Publicación editada exitosamente!',
        'publicacion': {
            'id': publicacion.id,
            'titulo': publicacion.titulo,
            'categoria': publicacion.categoria,
            'categoria_display': publicacion.get_categoria_display(),
            'contenido': publicacion.contenido,
        }
    })


@login_required
@require_POST
def eliminar_publicacion_ajax(request, publicacion_id):
    """Permite al autor de la publicación o a un administrador eliminarla."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    if publicacion.autor != request.user and not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso para eliminar esta publicación.'}, status=403)

    pub_id = publicacion.id
    publicacion.delete()

    # Al eliminar la publicación, su actividad queda retirada de la cola.
    # Devolvemos las actividades vigentes para que el widget se sincronice al instante.
    return JsonResponse({
        'status': 'ok',
        'message': 'Publicación eliminada correctamente.',
        'publicacion_id': pub_id,
        'actividades': obtener_actividades_recientes_balanceadas(),
    })



@login_required
@require_POST
def moderar_comentario_ajax(request, comentario_id):
    """Permite a un administrador censurar o eliminar un comentario o respuesta, o al autor eliminarlo."""
    comentario = get_object_or_404(Comentario, id=comentario_id)
    post = comentario.publicacion
    accion = request.POST.get('accion', '').upper().strip()

    es_autor = (comentario.autor == request.user)
    es_admin = _es_admin(request.user)

    if accion == 'ELIMINAR':
        if not (es_autor or es_admin):
            return JsonResponse({'status': 'error', 'message': 'No tienes permiso para eliminar este comentario.'}, status=403)
        comentario.delete()
        return JsonResponse({
            'status': 'ok',
            'accion': 'ELIMINAR',
            'total_comentarios': post.total_comentarios,
            'message': 'Comentario eliminado correctamente.'
        })
    elif accion == 'CENSURAR':
        comentario.censurado = not comentario.censurado
        comentario.save(update_fields=['censurado'])
        return JsonResponse({
            'status': 'ok',
            'accion': 'CENSURAR',
            'censurado': comentario.censurado,
            'message': 'Comentario censurado.' if comentario.censurado else 'Comentario descensurado.'
        })
    else:
        return JsonResponse({'status': 'error', 'message': 'Acción de moderación no reconocida.'}, status=400)


@login_required
@require_POST
def editar_comentario_ajax(request, comentario_id):
    """Permite al autor del comentario o a un administrador editar su texto."""
    comentario = get_object_or_404(Comentario, id=comentario_id)
    if comentario.autor != request.user and not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este comentario.'}, status=403)

    texto = request.POST.get('texto', '').strip()
    if not texto:
        return JsonResponse({'status': 'error', 'message': 'El comentario no puede estar vacío.'}, status=400)

    comentario.texto = texto
    comentario.save(update_fields=['texto'])

    return JsonResponse({
        'status': 'ok',
        'message': '¡Comentario editado exitosamente!',
        'comentario': {
            'id': comentario.id,
            'texto': comentario.texto
        }
    })


@login_required
@require_POST
def eliminar_comentario_ajax(request, comentario_id):
    """Permite al autor del comentario o a un administrador eliminarlo."""
    comentario = get_object_or_404(Comentario, id=comentario_id)
    if comentario.autor != request.user and not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso para eliminar este comentario.'}, status=403)

    post = comentario.publicacion
    comentario.delete()
    return JsonResponse({
        'status': 'ok',
        'message': 'Comentario eliminado correctamente.',
        'total_comentarios': post.total_comentarios
    })


@login_required
@require_POST
def cambiar_estado_incidencia_ajax(request, publicacion_id):
    """Permite cambiar el estado de una incidencia (ej. marcar como RESUELTA)."""
    if not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permisos para cambiar el estado.'}, status=403)

    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    nuevo_estado = request.POST.get('estado', Publicacion.EstadoIncidencia.RESUELTA).upper().strip()
    if nuevo_estado not in [c[0] for c in Publicacion.EstadoIncidencia.choices]:
        return JsonResponse({'status': 'error', 'message': 'Estado no válido.'}, status=400)

    publicacion.estado_incidencia = nuevo_estado
    publicacion.save(update_fields=['estado_incidencia'])

    # Notificar al autor del reporte que su incidencia cambió de estado
    crear_notificacion(
        destinatario=publicacion.autor, actor=request.user,
        tipo=Notificacion.Tipo.CAMBIO_ESTADO, publicacion=publicacion,
        extra=publicacion.get_estado_incidencia_display(),
    )

    # La actividad se deriva directamente de la publicación (tiempo real y sincronizada)
    actividad = _actividad_desde_publicacion(publicacion)

    return JsonResponse({
        'status': 'ok',
        'message': f'Incidencia #{publicacion.id} marcada como {publicacion.get_estado_incidencia_display()}.',
        'id': publicacion.id,
        'estado': publicacion.estado_incidencia,
        'es_resuelta': publicacion.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA,
        'actividad': {
            'id': actividad['id'],
            'publicacion_id': actividad['publicacion_id'],
            'titulo': actividad['titulo'],
            'tiempo': actividad['tiempo'],
            'tipo': actividad['tipo'],
        }
    })


@login_required
def api_actividad_reciente(request):
    """
    Devuelve en tiempo real las 6 actividades (3 no resueltas + 3 resueltas)
    derivadas de las publicaciones vivas. El tiempo se recalcula en cada llamada
    (hora real) y las publicaciones eliminadas ya no figuran en la respuesta.
    """
    actividades = obtener_actividades_recientes_balanceadas()
    data = [{
        'id': a['id'],
        'publicacion_id': a['publicacion_id'],
        'titulo': a['titulo'],
        'tiempo': a['tiempo'],
        'tipo': a['tipo'],
    } for a in actividades]
    return JsonResponse({'status': 'ok', 'actividades': data})


@login_required
def render_post_card_ajax(request, publicacion_id):
    """Retorna el fragmento HTML renderizado de una publicación para inserción en tiempo real."""
    publicacion = get_object_or_404(
        Publicacion.objects.prefetch_related('comentarios__respuestas', 'comentarios__autor', 'autor'),
        id=publicacion_id
    )
    reaccion = ReaccionPublicacion.objects.filter(publicacion=publicacion, usuario=request.user).first()
    publicacion.user_reaction = reaccion.tipo if reaccion else None
    publicacion.user_reposteo = Reposteo.objects.filter(publicacion=publicacion, usuario=request.user).exists()

    # Anotar reacciones y reposteos del usuario en los comentarios/respuestas
    comment_ids = [c.id for c in publicacion.comentarios.all()]
    user_comment_reactions = {}
    if comment_ids:
        for r in ReaccionComentario.objects.filter(usuario=request.user, comentario_id__in=comment_ids):
            user_comment_reactions[r.comentario_id] = r.tipo
    for c in publicacion.comentarios.all():
        c.user_reaction = user_comment_reactions.get(c.id)
        for rep in c.respuestas.all():
            rep.user_reaction = user_comment_reactions.get(rep.id)

    html = render_to_string('includes/post_card.html', {'post': publicacion, 'user': request.user}, request=request)
    return JsonResponse({
        'status': 'ok',
        'id': publicacion.id,
        'estado': publicacion.estado_incidencia,
        'es_resuelta': publicacion.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA,
        'html': html,
    })


@login_required
def api_feed_actualizado(request):
    """Devuelve los IDs más recientes de los 3 sin resolver y 3 resueltos para sincronización en tiempo real."""
    sin_resolver = list(Publicacion.objects.filter(
        estado_incidencia__in=[Publicacion.EstadoIncidencia.REPORTADO, Publicacion.EstadoIncidencia.EN_PROCESO]
    ).values_list('id', flat=True)[:3])

    resueltas = list(Publicacion.objects.filter(
        estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA
    ).values_list('id', flat=True)[:3])

    return JsonResponse({
        'status': 'ok',
        'sin_resolver_ids': sin_resolver,
        'resueltas_ids': resueltas,
    })


ACCENT_MAP = {
    'a': '[aáàäâAÁÀÄÂ]', 'á': '[aáàäâAÁÀÄÂ]', 'à': '[aáàäâAÁÀÄÂ]', 'ä': '[aáàäâAÁÀÄÂ]', 'â': '[aáàäâAÁÀÄÂ]',
    'e': '[eéèëêEÉÈËÊ]', 'é': '[eéèëêEÉÈËÊ]', 'è': '[eéèëêEÉÈËÊ]', 'ë': '[eéèëêEÉÈËÊ]', 'ê': '[eéèëêEÉÈËÊ]',
    'i': '[iíìïîIÍÌÏÎ]', 'í': '[iíìïîIÍÌÏÎ]', 'ì': '[iíìïîIÍÌÏÎ]', 'ï': '[iíìïîIÍÌÏÎ]', 'î': '[iíìïîIÍÌÏÎ]',
    'o': '[oóòöôOÓÒÖÔ]', 'ó': '[oóòöôOÓÒÖÔ]', 'ò': '[oóòöôOÓÒÖÔ]', 'ö': '[oóòöôOÓÒÖÔ]', 'ô': '[oóòöôOÓÒÖÔ]',
    'u': '[uúùüûUÚÙÜÛ]', 'ú': '[uúùüûUÚÙÜÛ]', 'ù': '[uúùüûUÚÙÜÛ]', 'ü': '[uúùüûUÚÙÜÛ]', 'û': '[uúùüûUÚÙÜÛ]',
    'n': '[nñNÑ]', 'ñ': '[nñNÑ]',
}

def to_accent_insensitive_regex(term):
    """
    Transforma un término en una expresión regular insensible a acentos/tildes en español.
    Ejemplo: 'reporte' -> 'r[eéèëêEÉÈËÊ]p[oóòöôOÓÒÖÔ]rt[eéèëêEÉÈËÊ]'
    Permite encontrar 'reporté' al buscar 'reporte', o viceversa.
    """
    pattern = []
    for ch in term:
        lower_ch = ch.lower()
        if lower_ch in ACCENT_MAP:
            pattern.append(ACCENT_MAP[lower_ch])
        else:
            pattern.append(re.escape(ch))
    return "".join(pattern)


@login_required
@require_GET
def api_buscar_publicaciones(request):
    """
    RF-008: Búsqueda de reportes y comentarios de otros usuarios con protocolos de seguridad
    y coincidencia por similitud (insensible a acentos/tildes).
    
    Protocolos de seguridad implementados:
    1. Sanitización estricta de inputs (longitud máxima, eliminación de tags HTML/scripts y caracteres de control).
    2. Rate limiting / Throttling preventivo contra ataques de denegación de servicio (DoS/fuerza bruta).
    3. Consultas seguras y parametrizadas para evitar inyecciones.
    4. Control de divulgación de información: excluye comentarios y publicaciones censuradas para usuarios estándar.
    5. Validación por lista blanca de parámetros (tab, personas, ubicación) y formato estricto de fecha ISO.
    """
    # ── Protocolo 1: Rate Limiting por usuario / IP (máximo 45 peticiones por minuto) ──
    client_id = request.user.id or request.META.get('REMOTE_ADDR', 'anonymous')
    cache_key = f"rate_search_{client_id}"
    req_count = cache.get(cache_key, 0)
    if req_count >= 45:
        return JsonResponse({
            'status': 'error',
            'message': 'Demasiadas solicitudes de búsqueda. Por favor espera unos segundos.'
        }, status=429)
    cache.set(cache_key, req_count + 1, 60)

    # ── Protocolo 2: Sanitización y validación estricta de parámetros ──
    q_raw = request.GET.get('q', '')
    # Truncar a máximo 150 caracteres y limpiar caracteres nulos o de control
    q_clean = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', q_raw)[:150]
    # Eliminar cualquier intento de inyección de etiquetas HTML/scripts
    q = re.sub(r'<[^>]*>', '', q_clean).strip()

    # Validación por lista blanca
    tab = request.GET.get('tab', 'historico').strip().lower()
    if tab not in ('historico', 'recientes', 'media'):
        tab = 'historico'

    personas = request.GET.get('personas', 'todas').strip().lower()
    if personas not in ('todas', 'cercanas'):
        personas = 'todas'

    ubicacion = request.GET.get('ubicacion', 'cercano').strip().lower()
    if ubicacion not in ('todas', 'cercano'):
        ubicacion = 'cercano'

    fecha_raw = request.GET.get('fecha', '').strip()
    fecha_validada = None
    if fecha_raw:
        try:
            from datetime import datetime
            dt = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
            if 2000 <= dt.year <= 2100:
                fecha_validada = dt
        except (ValueError, TypeError):
            fecha_validada = None

    # ── Protocolo 3: Consultas seguras y parametrizadas ──
    qs = Publicacion.objects.all().prefetch_related(
        'comentarios__respuestas', 'comentarios__autor', 'autor'
    )

    es_admin = (
        request.user.rol == Usuario.Rol.ADMINISTRADOR or
        request.user.is_staff or
        request.user.is_superuser
    )

    if not es_admin:
        qs = qs.filter(censurado=False)

    comentarios_data = []

    if q:
        palabras = q.split()
        post_q_filter = Q()
        comentarios_q_filter = Q()

        for p in palabras:
            pat = to_accent_insensitive_regex(p)
            post_q_filter |= (
                Q(contenido__iregex=pat) |
                Q(titulo__iregex=pat) |
                Q(categoria__iregex=pat) |
                Q(ubicacion__iregex=pat) |
                Q(autor_nombre__iregex=pat) |
                Q(autor__username__iregex=pat)
            )
            comentarios_q_filter |= (
                Q(texto__iregex=pat) |
                Q(autor_nombre__iregex=pat) |
                Q(autor__username__iregex=pat)
            )

        # Filtrar publicaciones cuyo propio contenido coincida
        qs = qs.filter(post_q_filter).distinct()

        # Búsqueda independiente de comentarios para visualización individual estilo Twitter
        com_qs = Comentario.objects.select_related('publicacion', 'autor', 'padre').all()
        if not es_admin:
            com_qs = com_qs.filter(censurado=False, publicacion__censurado=False)
        com_qs = com_qs.filter(comentarios_q_filter).order_by('-fecha_creacion')[:35]

        for c in com_qs:
            comentarios_data.append({
                'id': c.id,
                'post_id': c.publicacion_id,
                'post_title': c.publicacion.titulo or c.publicacion.categoria,
                'post_author': c.publicacion.autor.username if c.publicacion.autor else c.publicacion.autor_nombre,
                'comment_author': c.autor_nombre,
                'comment_username': c.autor.username if c.autor else '',
                'comment_avatar': c.autor.avatar.url if (c.autor and getattr(c.autor, 'avatar', None)) else '',
                'comment_text': c.texto,
                'comment_time': c.tiempo_relativo,
                'is_reply': bool(c.padre_id),
                'parent_author': c.padre.autor_nombre if c.padre else '',
            })

    if fecha_validada:
        qs = qs.filter(fecha_creacion__date=fecha_validada)

    if tab == 'media':
        qs = qs.filter(
            (Q(imagen__isnull=False) & ~Q(imagen='')) |
            (Q(imagen_url__isnull=False) & ~Q(imagen_url=''))
        )
    elif tab == 'recientes':
        qs = qs.order_by('-fecha_creacion')
    else:  # 'historico'
        qs = qs.order_by('-id')

    if personas == 'cercanas':
        qs = qs.filter(Q(autor=request.user) | Q(latitud__isnull=False))

    publicaciones = list(qs[:50])

    user_post_reactions = {}
    user_reposts = set()
    if request.user.is_authenticated:
        for r in ReaccionPublicacion.objects.filter(usuario=request.user, publicacion__in=publicaciones):
            user_post_reactions[r.publicacion_id] = r.tipo
        user_reposts = set(
            Reposteo.objects.filter(usuario=request.user, publicacion__in=publicaciones)
            .values_list('publicacion_id', flat=True)
        )
    for p in publicaciones:
        p.user_reaction = user_post_reactions.get(p.id)
        p.user_reposteo = p.id in user_reposts

    cards_html = []
    for p in publicaciones:
        cards_html.append(render_to_string('includes/post_card.html', {'post': p, 'request': request, 'user': request.user}))

    return JsonResponse({
        'status': 'ok',
        'count': len(publicaciones),
        'post_ids': [p.id for p in publicaciones],
        'html': "".join(cards_html),
        'comentarios': comentarios_data,
        'comentarios_count': len(comentarios_data),
    })




def _seed_demo_data():
    """Initializes the database with the exact sample data seen in View 4 & View 5."""
    user_ana, _ = Usuario.objects.get_or_create(
        username='ana_garcia',
        defaults={'email': 'ana.garcia@ciudad.gov', 'first_name': 'Ana', 'last_name': 'García', 'rol': Usuario.Rol.CIUDADANO}
    )
    user_luis, _ = Usuario.objects.get_or_create(
        username='luis_rodriguez',
        defaults={'email': 'luis.rodriguez@ciudad.gov', 'first_name': 'Luis', 'last_name': 'Rodríguez', 'rol': Usuario.Rol.ADMINISTRADOR}
    )
    user_maria, _ = Usuario.objects.get_or_create(
        username='maria_lopez',
        defaults={'email': 'maria.lopez@ciudad.gov', 'first_name': 'María', 'last_name': 'López', 'rol': Usuario.Rol.CIUDADANO}
    )
    user_carlos, _ = Usuario.objects.get_or_create(
        username='carlos_martinez',
        defaults={'email': 'carlos.martinez@ciudad.gov', 'first_name': 'Carlos', 'last_name': 'Martínez', 'rol': Usuario.Rol.CIUDADANO}
    )

    # Post 1 (Ana García) - REPORTADO - El Poblado
    p1 = Publicacion.objects.create(
        autor=user_ana,
        autor_nombre='Ana García',
        contenido='Gran bache en la Avenida Central, esquina con Calle 4. Está causando mucho tráfico y riesgo para los ciclistas. Por favor, precaución si pasan por ahí.',
        likes=24,
        estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
        ubicacion='Avenida Central esquina con Calle 4',
        latitud=6.2100000,
        longitud=-75.5700000,
    )
    Comentario.objects.create(
        publicacion=p1,
        autor_nombre='Carlos M.',
        texto='Ya reporté esto en la app también, ojalá lo arreglen pronto.'
    )

    # Post 2 (Luis Rodríguez) - RESUELTA - Parque de los Deseos
    Publicacion.objects.create(
        autor=user_luis,
        autor_nombre='Luis Rodríguez',
        contenido='La luminaria del Parque Los Pinos ya fue reparada. Gracias a las cuadrillas por la rápida atención.',
        likes=112,
        estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA,
        ubicacion='Parque Los Pinos',
        latitud=6.2560000,
        longitud=-75.5660000,
    )

    # Post 3 (María López) - EN_PROCESO - Laureles
    Publicacion.objects.create(
        autor=user_maria,
        autor_nombre='María López',
        contenido='Fuga de agua potable en la Circular 73 con Calle 39B. Ya fue reportada y la cuadrilla de EPM está en camino.',
        likes=37,
        estado_incidencia=Publicacion.EstadoIncidencia.EN_PROCESO,
        ubicacion='Circular 73 con Calle 39B, Laureles',
        latitud=6.2460000,
        longitud=-75.5930000,
    )

    # Post 4 (Carlos Martínez) - EN_PROCESO - Centro
    Publicacion.objects.create(
        autor=user_carlos,
        autor_nombre='Carlos Martínez',
        contenido='Semáforo dañado en la intersección de la Avenida Oriental con Calle 49. Genera congestión vehicular en hora pico.',
        likes=58,
        estado_incidencia=Publicacion.EstadoIncidencia.EN_PROCESO,
        ubicacion='Avenida Oriental con Calle 49, Centro',
        latitud=6.2510000,
        longitud=-75.5640000,
    )

    # Post 5 (Ana García) - REPORTADO - Robledo
    Publicacion.objects.create(
        autor=user_ana,
        autor_nombre='Ana García',
        contenido='Árbol caído sobre la vía en la carrera 80 con calle 65. Impide el tránsito de vehículos.',
        likes=15,
        estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
        ubicacion='Carrera 80 con Calle 65, Robledo',
        latitud=6.2630000,
        longitud=-75.6100000,
    )

    # Trending Topics
    TrendingTopic.objects.get_or_create(
        categoria='TRÁFICO',
        hashtag='#CorteAvenidaSur',
        defaults={'detalle': '45 reportes en la última hora', 'orden': 1}
    )
    TrendingTopic.objects.get_or_create(
        categoria='SERVICIOS',
        hashtag='#FallaElectricaNorte',
        defaults={'detalle': '120 reportes', 'orden': 2}
    )
    TrendingTopic.objects.get_or_create(
        categoria='COMUNIDAD',
        hashtag='#JornadaLimpiezaParque',
        defaults={'detalle': 'Evento activo', 'orden': 3}
    )

    # Actividad Reciente
    ActividadReciente.objects.get_or_create(
        titulo='Nuevo incidente reportado en Calle 8.',
        defaults={'tiempo': 'Hace 2 min', 'tipo': 'incidente', 'orden': 1}
    )
    ActividadReciente.objects.get_or_create(
        titulo='Incidencia #492 marcada como Resuelta.',
        defaults={'tiempo': 'Hace 15 min', 'tipo': 'resuelta', 'orden': 2}
    )


def _ensure_demo_balance():
    """Garantiza que existan al menos 3 publicaciones resueltas para los 3 espacios reservados."""
    resueltas = Publicacion.objects.filter(estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA).count()
    if resueltas < 3:
        user_luis = Usuario.objects.filter(username='luis_rodriguez').first() or Usuario.objects.filter(rol=Usuario.Rol.ADMINISTRADOR).first()
        if not user_luis:
            user_luis = Usuario.objects.first()

        nuevas_resueltas = [
            {
                'titulo': 'Luminarias LED instaladas en el Parque Los Pinos',
                'categoria': Publicacion.Categoria.ALUMBRADO,
                'contenido': 'Se completó con éxito el cambio e instalación de luminarias LED de alta potencia. El parque ahora cuenta con iluminación completa para la seguridad del sector.',
                'ubicacion': 'Parque Los Pinos, Medellín',
                'likes': 42,
            },
            {
                'titulo': 'Repavimentación y sellado de bache en Av. Oriental',
                'categoria': Publicacion.Categoria.VIAS,
                'contenido': 'Cuadrilla de la Secretaría de Obras concluyó el bacheo asfáltico en la calzada oriental. El tránsito vehicular fluye con total normalidad.',
                'ubicacion': 'Avenida Oriental con Calle 52, Medellín',
                'likes': 78,
            },
            {
                'titulo': 'Mantenimiento preventivo de juegos infantiles en Belén',
                'categoria': Publicacion.Categoria.PARQUES,
                'contenido': 'Los juegos infantiles y barandas de seguridad del parque barrial fueron reparados y pintados. Espacio habilitado para los niños.',
                'ubicacion': 'Parque de Belén, Medellín',
                'likes': 35,
            }
        ]

        faltantes = 3 - resueltas
        for item in nuevas_resueltas[:faltantes]:
            Publicacion.objects.create(
                autor=user_luis,
                autor_nombre='Luis Rodríguez (Admin)' if user_luis and user_luis.rol == Usuario.Rol.ADMINISTRADOR else 'Gestión Municipal',
                titulo=item['titulo'],
                categoria=item['categoria'],
                contenido=item['contenido'],
                ubicacion=item['ubicacion'],
                likes=item['likes'],
                estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA
            )




# ==========================================================================
# Notificaciones
# ==========================================================================
def _seed_notificaciones_demo(usuario):
    """
    Siembra unas notificaciones de ejemplo para 'usuario' si no tiene ninguna,
    de modo que la vista no se vea vacía en la demo. Usa publicaciones reales
    del usuario si existen; si no, crea notificaciones sin publicación asociada.
    """
    if Notificacion.objects.filter(destinatario=usuario).exists():
        return

    pub = Publicacion.objects.filter(autor=usuario).order_by('-id').first()
    muestras = [
        (Notificacion.Tipo.COMENTARIO, 'Ana García', Notificacion.Categoria.PUBLICACION, 'Gran bache, ya lo reporté también 👍'),
        (Notificacion.Tipo.LIKE, 'Luis Rodríguez', Notificacion.Categoria.PUBLICACION, ''),
        (Notificacion.Tipo.COMENTARIO, 'Sandra M.', Notificacion.Categoria.PUBLICACION, 'Ojalá lo arreglen pronto, llevo meses reportándolo'),
        (Notificacion.Tipo.CAMBIO_ESTADO, 'Equipo UrbanReport', Notificacion.Categoria.REPORTE, 'Resuelta'),
    ]
    for tipo, nombre, categoria, extra in muestras:
        Notificacion.objects.create(
            destinatario=usuario,
            actor=None,
            actor_nombre=nombre,
            tipo=tipo,
            categoria=categoria,
            publicacion=pub if categoria == Notificacion.Categoria.PUBLICACION else pub,
            extra=extra,
            leido=False,
        )


@login_required
def notificaciones_view(request):
    """
    Vista de Notificaciones del usuario autenticado. Soporta filtro por categoría
    (todas / publicaciones / reportes) y agrupa por día (hoy / ayer / anteriores).
    Al entrar, se marcan como leídas.
    """
    _seed_notificaciones_demo(request.user)

    filtro = request.GET.get('filtro', 'todas').lower()
    qs = Notificacion.objects.filter(destinatario=request.user).select_related('actor', 'publicacion', 'comentario')

    if filtro == 'publicaciones':
        qs = qs.filter(categoria=Notificacion.Categoria.PUBLICACION)
    elif filtro == 'reportes':
        qs = qs.filter(categoria=Notificacion.Categoria.REPORTE)

    notificaciones = list(qs)

    # Agrupar por día para la plantilla (Hoy / Ayer / Anteriores)
    hoy = timezone.localdate()
    ayer = hoy - timedelta(days=1)
    for n in notificaciones:
        fecha_local = timezone.localtime(n.fecha_creacion).date()
        if fecha_local == hoy:
            n.grupo_dia = 'Hoy'
        elif fecha_local == ayer:
            n.grupo_dia = 'Ayer'
        else:
            n.grupo_dia = 'Anteriores'

    context = {
        'notificaciones': notificaciones,
        'filtro_activo': filtro,
        'total_no_leidas': Notificacion.objects.filter(destinatario=request.user, leido=False).count(),
        'active_menu': 'notificaciones',
    }
    return render(request, 'feed/notificaciones.html', context)


@login_required
def abrir_notificacion(request, notificacion_id):
    """Marca la notificación como leída y redirige a la publicación/comentario asociado."""
    n = get_object_or_404(
        Notificacion.objects.select_related('publicacion', 'comentario', 'actor'),
        id=notificacion_id, destinatario=request.user,
    )
    if not n.leido:
        n.leido = True
        n.save(update_fields=['leido'])

    if n.publicacion_id:
        url = reverse('detalle_publicacion', args=[n.publicacion_id])
        if n.comentario_id:
            url += f'#comment-card-{n.comentario_id}'
        else:
            url += f'#post-card-{n.publicacion_id}'
        return redirect(url)
    if n.actor and n.tipo == Notificacion.Tipo.SEGUIDOR:
        return redirect('perfil_usuario', username=n.actor.username)
    return redirect('notificaciones')


@login_required
@require_POST
def marcar_notificaciones_leidas_ajax(request):
    """Marca todas las notificaciones del usuario como leídas."""
    actualizadas = Notificacion.objects.filter(destinatario=request.user, leido=False).update(leido=True)
    return JsonResponse({'status': 'ok', 'actualizadas': actualizadas, 'total_no_leidas': 0})


@login_required
def api_notificaciones_no_leidas(request):
    """Devuelve el número de notificaciones no leídas (para el badge de la campana)."""
    total = Notificacion.objects.filter(destinatario=request.user, leido=False).count()
    return JsonResponse({'status': 'ok', 'total_no_leidas': total})
