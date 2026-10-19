from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.timesince import timesince
from django.utils import timezone
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from datetime import timedelta
from collections import Counter
import io
import re
from PIL import Image, UnidentifiedImageError
from .models import (
    Publicacion, Comentario,
    ReaccionPublicacion, ReaccionComentario, ReporteContenido, Notificacion, Reposteo
)
from .moderacion import contiene_lenguaje_inapropiado, MENSAJE_RECHAZO
from usuarios.models import Usuario


def crear_notificacion(destinatario, actor, tipo, publicacion=None, comentario=None, categoria=None, extra='', permitir_auto=False):
    """
    Crea una notificación para 'destinatario' generada por 'actor'.
    No hace nada si el actor es el mismo destinatario (salvo permitir_auto=True)
    o si no hay destinatario válido.
    """
    if destinatario is None or actor is None or (destinatario == actor and not permitir_auto):
        return None

    if categoria is None:
        if tipo in (Notificacion.Tipo.CAMBIO_ESTADO, Notificacion.Tipo.REPORTE_CONTENIDO):
            categoria = Notificacion.Categoria.REPORTE
        elif tipo == Notificacion.Tipo.SEGUIDOR:
            categoria = Notificacion.Categoria.SOCIAL
        else:
            categoria = Notificacion.Categoria.PUBLICACION

    # ── Respetar las preferencias de notificaciones del destinatario ──
    # (configuradas en la vista "Configuración" del perfil).
    #   - notif_reportes controla la categoría REPORTE.
    #   - notif_feed controla las categorías del Feed comunitario (PUBLICACION y SOCIAL).
    # Si la preferencia correspondiente está desactivada, no se crea la notificación.
    if categoria == Notificacion.Categoria.REPORTE:
        if not getattr(destinatario, 'notif_reportes', True):
            return None
    else:  # PUBLICACION o SOCIAL -> notificaciones del Feed
        if not getattr(destinatario, 'notif_feed', True):
            return None

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

    incidentes = (
        Publicacion.objects.filter(
            latitud__isnull=False,
            longitud__isnull=False,
        )
        .select_related('autor')
        .annotate(_total_comentarios=Count('comentarios'))
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
            'autor': inc.nombre_autor,
            'likes': inc.likes,
            'comentarios': inc.total_comentarios,
            'tiempo': timesince(inc.fecha_creacion) + ' atrás',
            'imagen_url': inc.imagen.url if inc.imagen else inc.imagen_url,
            'censurado': inc.censurado,
            'motivo_censura': inc.motivo_censura or '',
            'motivo_declinacion': inc.motivo_declinacion or '',
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


# ── Sanitización y optimización de imágenes ──
# Solo se aceptan PNG y JPG. Límite de tamaño (bytes) para evitar cargas abusivas.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_IMAGE_DIMENSION = 1600  # Máximo ancho/alto en píxeles para carga rápida en web
# Formatos permitidos (detectados por Pillow, NO por extensión) y su normalización de salida
_FORMATOS_PERMITIDOS = {'JPEG', 'PNG'}


class ImagenInvalida(Exception):
    """Se lanza cuando la imagen no supera las validaciones de seguridad."""
    pass


def sanitizar_imagen(archivo):
    """
    Valida, redimensiona y neutraliza una imagen subida por el usuario.

    Seguridad y rendimiento:
      1. Rechaza archivos que superen el tamaño máximo.
      2. Verifica con Pillow que el contenido ES realmente una imagen (verify()),
         detectando el formato REAL, no confiando en la extensión ni el mimetype.
      3. Solo admite PNG y JPEG.
      4. Redimensiona proporcionalmente si supera MAX_IMAGE_DIMENSION para optimizar
         el peso de transferencia en el feed y mapa.
      5. RE-CODIFICA la imagen desde sus píxeles a un archivo limpio. Esto descarta
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

    # 4. Re-abrir (verify() invalida el objeto), acotar dimensiones y re-codificar limpiamente
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImagenInvalida('No se pudo procesar la imagen.')

    if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

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

    # ── Moderación de lenguaje ──
    # Rechaza título o descripción con lenguaje inapropiado antes de guardar.
    if contiene_lenguaje_inapropiado(titulo) or contiene_lenguaje_inapropiado(contenido):
        return JsonResponse({'status': 'error', 'message': MENSAJE_RECHAZO}, status=400)

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


def _actividad_desde_publicacion(pub):
    """
    Construye un diccionario de 'Actividad Reciente' a partir de una Publicacion real.
    El tiempo se calcula dinámicamente con timesince (hora real de publicación) y el
    identificador es estable (basado en el id de la publicación) para que el frontend
    pueda reconciliar y, si la publicación se elimina, retirarla de la cola.
    """
    es_resuelta = pub.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA
    es_declinada = pub.estado_incidencia == Publicacion.EstadoIncidencia.DECLINADO
    tipo = 'resuelta' if es_resuelta else 'incidente'

    if es_resuelta:
        titulo = f"Incidencia #{pub.id} marcada como Resuelta."
    elif es_declinada:
        titulo = f"Incidencia #{pub.id} declinada."
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
    Publicacion.Categoria.VIAS: '#Vias',
    Publicacion.Categoria.ALUMBRADO: '#Alumbrado',
    Publicacion.Categoria.PARQUES: '#Parques',
    Publicacion.Categoria.INFRAESTRUCTURA: '#Infraestructura',
    Publicacion.Categoria.REDES: '#RedesYServicios',
    Publicacion.Categoria.ASEO: '#AseoYResiduos',
    Publicacion.Categoria.ACUEDUCTO: '#AcueductoYAlcantarillado',
    Publicacion.Categoria.OTROS: '#Otros',
}

# Etiqueta de "sección" mostrada en el widget según el tipo de tendencia
_CATEGORIA_SECCION = {
    Publicacion.Categoria.VIAS: 'MOVILIDAD',
    Publicacion.Categoria.ALUMBRADO: 'SERVICIOS',
    Publicacion.Categoria.PARQUES: 'COMUNIDAD',
    Publicacion.Categoria.INFRAESTRUCTURA: 'INFRAESTRUCTURA',
    Publicacion.Categoria.REDES: 'SERVICIOS',
    Publicacion.Categoria.ASEO: 'AMBIENTE',
    Publicacion.Categoria.ACUEDUCTO: 'SERVICIOS',
    Publicacion.Categoria.OTROS: 'GENERAL',
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


def _anotar_interacciones_usuario(publicaciones, user):
    """
    Anota en lote (O(1) consultas) las reacciones (LIKE/DISLIKE) y reposteos del
    usuario autenticado sobre una lista de publicaciones y todos sus comentarios
    y respuestas anidadas.
    """
    if not publicaciones:
        return

    user_post_reactions = {}
    user_comment_reactions = {}
    user_reposts = set()

    if user and user.is_authenticated:
        for r in ReaccionPublicacion.objects.filter(usuario=user, publicacion__in=publicaciones):
            user_post_reactions[r.publicacion_id] = r.tipo
        user_reposts = set(
            Reposteo.objects.filter(usuario=user, publicacion__in=publicaciones)
            .values_list('publicacion_id', flat=True)
        )
        all_comment_ids = [
            c.id
            for p in publicaciones
            for c in p.comentarios.all()
        ]
        if all_comment_ids:
            for r in ReaccionComentario.objects.filter(usuario=user, comentario_id__in=all_comment_ids):
                user_comment_reactions[r.comentario_id] = r.tipo

    for p in publicaciones:
        p.user_reaction = user_post_reactions.get(p.id)
        p.user_reposteo = p.id in user_reposts
        for c in p.comentarios.all():
            c.user_reaction = user_comment_reactions.get(c.id)
            for rep in c.respuestas.all():
                rep.user_reaction = user_comment_reactions.get(rep.id)


@login_required
def detalle_publicacion_view(request, publicacion_id):
    """
    Vista de detalle de una publicación (tipo Facebook): muestra la publicación
    completa con TODOS sus comentarios. Reutiliza post_card.html en modo 'detalle'.
    """
    publicacion = get_object_or_404(
        Publicacion.objects.select_related('autor').prefetch_related(
            'comentarios__respuestas__autor', 'comentarios__autor', 'reposteos'
        ),
        id=publicacion_id
    )
    _anotar_interacciones_usuario([publicacion], request.user)

    context = {
        'post': publicacion,
        'active_menu': 'feed',
    }
    return render(request, 'feed/detalle_publicacion.html', context)


@login_required
def feed_comunitario_view(request):
    # El feed comunitario muestra las publicaciones recientes con sus relaciones precargadas
    publicaciones = list(Publicacion.objects.all().order_by('-id').select_related('autor').prefetch_related(
        'comentarios__respuestas__autor', 'comentarios__autor', 'reposteos'
    ))
    # Trending Topics calculados en vivo desde las publicaciones (categorías + hashtags)
    trending_topics = calcular_trending_topics()

    # El apartado 'Actividad Reciente' mantiene estrictamente 6 cupos (3 no resueltos + 3 resueltos)
    actividades = obtener_actividades_recientes_balanceadas()

    _anotar_interacciones_usuario(publicaciones, request.user)

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
            # ── Moderación de lenguaje ──
            # Si el título o la descripción tienen lenguaje inapropiado, no se guarda.
            # Se conserva lo escrito en el contexto para que el usuario pueda corregirlo.
            if contiene_lenguaje_inapropiado(titulo) or contiene_lenguaje_inapropiado(contenido):
                messages.error(request, MENSAJE_RECHAZO)
                context = {
                    'publicaciones': publicaciones,
                    'trending_topics': trending_topics,
                    'actividades': actividades,
                    'active_menu': 'feed',
                    'form_titulo': titulo,
                    'form_contenido': contenido,
                }
                return render(request, 'feed/feed_comunitario.html', context)

            user = request.user
            autor_nombre = f"{user.first_name} {user.last_name}".strip() or user.username

            Publicacion.objects.create(
                autor=user,
                autor_nombre=autor_nombre,
                titulo=titulo,
                categoria=categoria,
                contenido=contenido or titulo,
                imagen=imagen_limpia,
                estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO
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
    """Crea un comentario en la publicación o una respuesta anidada si se especifica padre_id, con imagen opcional."""
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    texto = request.POST.get('texto', '').strip()
    padre_id = request.POST.get('padre_id')
    imagen = request.FILES.get('imagen')

    if not texto and imagen is None:
        return JsonResponse({'status': 'error', 'message': 'El comentario no puede estar vacío.'}, status=400)

    # ── Moderación de lenguaje ──
    if texto and contiene_lenguaje_inapropiado(texto):
        return JsonResponse({'status': 'error', 'message': MENSAJE_RECHAZO}, status=400)

    # ── Validación y sanitización de imagen adjunta (si la hay) ──
    imagen_limpia = None
    if imagen is not None:
        try:
            imagen_limpia = sanitizar_imagen(imagen)
        except ImagenInvalida as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

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
        texto=texto,
        imagen=imagen_limpia,
    )

    # Notificar: si es respuesta, al autor del comentario padre; si no, al autor de la publicación
    fragmento = texto[:80] if texto else '📷 Imagen adjunta'
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
            'autor_nombre': comentario.nombre_autor,
            'initials': initials,
            'texto': comentario.texto,
            'imagen_url': comentario.imagen.url if comentario.imagen else None,
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
def guia_ciudadano_view(request):
    """Guía del Ciudadano: cómo usar UrbanReport (todos los usuarios)."""
    return render(request, 'feed/guia_ciudadano.html', {'active_menu': 'ayuda'})


@login_required
@_solo_administrador
def manual_administrador_view(request):
    """Manual del Administrador: gestión y moderación (solo administradores)."""
    return render(request, 'feed/manual_administrador.html', {'active_menu': 'ayuda'})


def _estadisticas_usuario(usuario, dias=None):
    """
    Calcula las métricas personales de un usuario (RF-020): reportes radicados,
    resueltos, en proceso, impacto (suma de likes recibidos), nivel de confianza,
    distribución por categoría y actividad mensual de los últimos 6 meses.
    `dias` filtra las métricas del periodo (7, 30, ...); None = todo el histórico.
    """
    Estado = Publicacion.EstadoIncidencia
    Cat = Publicacion.Categoria

    # Todas las publicaciones del usuario (base para nivel de confianza, global)
    pubs_todas = Publicacion.objects.filter(autor=usuario)

    # Si se pasa un rango de días, las métricas del periodo se filtran por fecha.
    # dias=None significa "todo el histórico".
    if dias:
        desde = timezone.now() - timedelta(days=dias)
        pubs = pubs_todas.filter(fecha_creacion__gte=desde)
    else:
        pubs = pubs_todas

    # 1 sola consulta agregada para conteos por estado e impacto (suma de likes)
    agregados = pubs.aggregate(
        total=Count('id'),
        resueltos=Count('id', filter=Q(estado_incidencia=Estado.RESUELTA)),
        en_proceso=Count('id', filter=Q(estado_incidencia=Estado.EN_PROCESO)),
        reportados=Count('id', filter=Q(estado_incidencia=Estado.REPORTADO)),
        impacto=Coalesce(Sum('likes'), 0),
    )
    total = agregados['total'] or 0
    resueltos = agregados['resueltos'] or 0
    en_proceso = agregados['en_proceso'] or 0
    reportados = agregados['reportados'] or 0
    impacto = agregados['impacto'] or 0

    # El nivel de confianza es acumulado (todo el histórico), no del periodo.
    if dias is None:
        confianza = usuario.nivel_confianza(total=total, resueltos=resueltos)
    else:
        confianza = usuario.nivel_confianza()

    # Distribución por categoría (del periodo) en 1 sola consulta agrupada
    conteo_cat = dict(
        pubs.values('categoria').annotate(c=Count('id')).values_list('categoria', 'c')
    )
    por_categoria = [
        {'etiqueta': etiqueta, 'cantidad': conteo_cat.get(valor, 0)}
        for valor, etiqueta in Cat.choices
    ]

    # Actividad reciente: últimas 6 publicaciones del usuario (independiente del rango)
    actividad_reciente = list(
        pubs_todas.order_by('-fecha_creacion')[:6]
    )

    # Actividad mensual: últimos 6 meses (radicados vs resueltos) en 1 sola consulta
    ahora = timezone.now()
    MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    year = ahora.year
    month = ahora.month
    secuencia = []
    for i in range(5, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        secuencia.append((y, m))

    secuencia_set = set(secuencia)
    radicados_por_mes = Counter()
    resueltos_por_mes = Counter()
    for fecha_dt, estado_inc in pubs.values_list('fecha_creacion', 'estado_incidencia'):
        if not fecha_dt:
            continue
        ym = (fecha_dt.year, fecha_dt.month)
        if ym in secuencia_set:
            radicados_por_mes[ym] += 1
            if estado_inc == Estado.RESUELTA:
                resueltos_por_mes[ym] += 1

    meses_labels = [MESES_ES[m - 1] for (_, m) in secuencia]
    radicados_mes = [radicados_por_mes[ym] for ym in secuencia]
    resueltos_mes = [resueltos_por_mes[ym] for ym in secuencia]

    return {
        'total': total,
        'resueltos': resueltos,
        'en_proceso': en_proceso,
        'reportados': reportados,
        'impacto': impacto,
        'confianza': confianza,
        'por_categoria': por_categoria,
        'actividad_reciente': actividad_reciente,
        'chart_cat_labels': [c['etiqueta'] for c in por_categoria],
        'chart_cat_data': [c['cantidad'] for c in por_categoria],
        'chart_meses_labels': meses_labels,
        'chart_radicados_data': radicados_mes,
        'chart_resueltos_data': resueltos_mes,
    }


@login_required
def estadisticas_view(request):
    """
    Estadísticas (RF-006, RF-020). Para administradores muestra el tablero de
    métricas generales (datos globales) integrado con sus métricas personales.
    Para ciudadanos muestra solo "Mis Estadísticas e Impacto".
    """
    # Filtro temporal: ?rango=7 | 30 | todo (por defecto 30 días)
    RANGOS = {'7': 7, '30': 30, 'todo': None}
    rango = (request.GET.get('rango') or '30').lower()
    if rango not in RANGOS:
        rango = '30'
    dias = RANGOS[rango]

    es_admin_user = _es_admin(request.user)
    mis_stats = _estadisticas_usuario(request.user, dias=dias)

    context = {
        'active_menu': 'estadisticas' if es_admin_user else 'mis_estadisticas',
        'mis_stats': mis_stats,
        'es_admin_vista': es_admin_user,
        'rango_activo': rango,
    }
    if es_admin_user:
        context['stats'] = _calcular_estadisticas_panel()

    return render(request, 'feed/estadisticas.html', context)


def _calcular_estadisticas_panel():
    """
    Calcula todas las métricas del Panel de Control Municipal a partir de datos
    reales de Publicacion. Devuelve un dict listo para la plantilla y para
    alimentar las gráficas de Chart.js.
    """
    Estado = Publicacion.EstadoIncidencia
    Cat = Publicacion.Categoria

    qs = Publicacion.objects.all()

    # --- 1 sola consulta agregada para total y conteos por estado ---
    agregados = qs.aggregate(
        total=Count('id'),
        reportados=Count('id', filter=Q(estado_incidencia=Estado.REPORTADO)),
        en_proceso=Count('id', filter=Q(estado_incidencia=Estado.EN_PROCESO)),
        resueltas=Count('id', filter=Q(estado_incidencia=Estado.RESUELTA)),
    )
    total = agregados['total'] or 0
    por_estado = {
        Estado.REPORTADO: agregados['reportados'] or 0,
        Estado.EN_PROCESO: agregados['en_proceso'] or 0,
        Estado.RESUELTA: agregados['resueltas'] or 0,
    }
    activas = por_estado[Estado.REPORTADO] + por_estado[Estado.EN_PROCESO]
    resueltas = por_estado[Estado.RESUELTA]

    # --- Tasa de resolución y "satisfacción vecinal" (derivada de la tasa) ---
    tasa_resolucion = round((resueltas / total) * 100, 1) if total else 0.0
    satisfaccion = tasa_resolucion  # satisfacción = tasa de resolución (decisión del equipo)

    # --- Tiempo promedio de respuesta ---
    # Sin campo de fecha de resolución, aproximamos con la antigüedad promedio de
    # los reportes resueltos (cuánto tardan en el sistema), proyectando solo fecha_creacion.
    ahora = timezone.now()
    fechas_resueltas = list(
        qs.filter(estado_incidencia=Estado.RESUELTA).values_list('fecha_creacion', flat=True)
    ) if resueltas else []
    horas = [
        (ahora - fc).total_seconds() / 3600.0
        for fc in fechas_resueltas if fc
    ]
    tiempo_prom_horas = round(sum(horas) / len(horas), 1) if horas else 0.0

    # --- Conteos por categoría en 1 sola consulta agrupada ---
    conteo_cat = dict(
        qs.values('categoria').annotate(c=Count('id')).values_list('categoria', 'c')
    )
    por_categoria = []
    for valor, etiqueta in Cat.choices:
        c = conteo_cat.get(valor, 0)
        por_categoria.append({
            'clave': valor,
            'etiqueta': etiqueta,
            'cantidad': c,
            'porcentaje': round((c / total) * 100) if total else 0,
        })
    # Orden descendente por cantidad para la "Carga por Departamento"
    carga_departamento = sorted(por_categoria, key=lambda x: x['cantidad'], reverse=True)

    # --- Tendencia temporal: reportes por día en los últimos 14 días (1 sola consulta) ---
    dias = 14
    base = ahora.date() - timedelta(days=dias - 1)
    conteo_dias = Counter()
    for fc in qs.filter(fecha_creacion__date__gte=base).values_list('fecha_creacion', flat=True):
        if fc:
            conteo_dias[fc.date()] += 1

    serie_labels = []
    serie_valores = []
    for i in range(dias):
        dia = base + timedelta(days=i)
        serie_labels.append(dia.strftime('%d/%m'))
        serie_valores.append(conteo_dias.get(dia, 0))

    # --- Cola de atención prioritaria: activas, por más votos y antigüedad ---
    cola = list(
        qs.exclude(estado_incidencia__in=[Estado.RESUELTA, Estado.DECLINADO])
          .select_related('autor')
          .order_by('-likes', 'fecha_creacion')[:6]
    )

    return {
        'total': total,
        'activas': activas,
        'resueltas': resueltas,
        'tasa_resolucion': tasa_resolucion,
        'satisfaccion': satisfaccion,
        'tiempo_prom_horas': tiempo_prom_horas,
        'por_estado': por_estado,
        'por_categoria': por_categoria,
        'carga_departamento': carga_departamento,
        # Datos serializados para Chart.js
        'chart_categoria_labels': [c['etiqueta'] for c in por_categoria],
        'chart_categoria_data': [c['cantidad'] for c in por_categoria],
        'chart_estado_labels': ['Reportado', 'En Proceso', 'Resuelta'],
        'chart_estado_data': [
            por_estado[Estado.REPORTADO],
            por_estado[Estado.EN_PROCESO],
            por_estado[Estado.RESUELTA],
        ],
        'chart_tendencia_labels': serie_labels,
        'chart_tendencia_data': serie_valores,
        'cola_prioritaria': cola,
    }


@login_required
@_solo_administrador
def panel_administrador_view(request):
    """
    Panel de Control Municipal (RF-005, Fase 1).
    Vista exclusiva de administradores con KPIs, estadísticas en Chart.js y la
    cola de atención prioritaria. Las métricas se calculan de datos reales.
    """
    stats = _calcular_estadisticas_panel()

    context = {
        'active_menu': 'panel',
        'stats': stats,
    }
    return render(request, 'feed/panel_admin.html', context)


def _filtrar_incidentes(request):
    """
    Construye el queryset de incidentes aplicando los filtros de búsqueda
    avanzada de la query string. Reutilizado por la tabla y por la exportación.
    Devuelve (queryset, filtros_dict).
    """
    Estado = Publicacion.EstadoIncidencia
    Cat = Publicacion.Categoria

    q = (request.GET.get('q') or '').strip()
    f_categoria = (request.GET.get('categoria') or '').strip().upper()
    f_estado = (request.GET.get('estado') or '').strip().upper()
    f_desde = (request.GET.get('desde') or '').strip()
    f_hasta = (request.GET.get('hasta') or '').strip()

    qs = Publicacion.objects.select_related('autor').order_by('-fecha_creacion')

    if q:
        qs = qs.filter(
            Q(titulo__icontains=q) |
            Q(contenido__icontains=q) |
            Q(ubicacion__icontains=q) |
            Q(autor_nombre__icontains=q) |
            Q(autor__username__icontains=q) |
            Q(autor__first_name__icontains=q) |
            Q(autor__last_name__icontains=q)
        )
    if f_categoria in [c[0] for c in Cat.choices]:
        qs = qs.filter(categoria=f_categoria)
    if f_estado in [c[0] for c in Estado.choices]:
        qs = qs.filter(estado_incidencia=f_estado)
    if f_desde:
        qs = qs.filter(fecha_creacion__date__gte=f_desde)
    if f_hasta:
        qs = qs.filter(fecha_creacion__date__lte=f_hasta)

    filtros = {'q': q, 'categoria': f_categoria, 'estado': f_estado, 'desde': f_desde, 'hasta': f_hasta}
    return qs, filtros


@login_required
@_solo_administrador
def incidentes_view(request):
    """
    Gestión de incidentes (RF-005, Fase 2).
    Tabla administrativa con TODOS los reportes y filtros de búsqueda avanzada:
    texto, categoría, estado y rango de fechas. Permite actualizar el estado de
    cada reporte (reutiliza cambiar_estado_incidencia_ajax).
    """
    from django.core.paginator import Paginator

    Estado = Publicacion.EstadoIncidencia
    Cat = Publicacion.Categoria

    qs, filtros_vals = _filtrar_incidentes(request)
    q = filtros_vals['q']
    f_categoria = filtros_vals['categoria']
    f_estado = filtros_vals['estado']
    f_desde = filtros_vals['desde']
    f_hasta = filtros_vals['hasta']

    total_resultados = qs.count()

    # --- Paginación ---
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Querystring sin 'page' para conservar filtros en los enlaces de paginación
    params = request.GET.copy()
    params.pop('page', None)
    querystring_filtros = params.urlencode()

    context = {
        'active_menu': 'incidentes',
        'page_obj': page_obj,
        'total_resultados': total_resultados,
        'categorias': Cat.choices,
        'estados': Estado.choices,
        'motivos_declinacion': Publicacion.MotivoDeclinacion.choices,
        'filtros': {
            'q': q,
            'categoria': f_categoria,
            'estado': f_estado,
            'desde': f_desde,
            'hasta': f_hasta,
        },
        'hay_filtros': bool(q or f_categoria or f_estado or f_desde or f_hasta),
        'querystring_filtros': querystring_filtros,
    }
    return render(request, 'feed/incidentes.html', context)


# Columnas del CSV de incidentes (orden fijo para exportar e importar)
INCIDENTES_CSV_COLUMNAS = [
    'id', 'titulo', 'contenido', 'categoria', 'estado', 'ubicacion',
    'autor', 'latitud', 'longitud', 'likes', 'fecha_creacion',
]


@login_required
@_solo_administrador
def exportar_incidentes_csv(request):
    """
    Exporta a CSV los incidentes que coinciden con los filtros activos
    (RF-005, Fase 3). Respeta la búsqueda avanzada de la tabla.
    """
    import csv
    from django.http import HttpResponse

    qs, _ = _filtrar_incidentes(request)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="incidentes_urbanreport.csv"'
    # BOM para que Excel reconozca UTF-8 (tildes/ñ)
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(INCIDENTES_CSV_COLUMNAS)
    for p in qs:
        writer.writerow([
            p.id,
            p.titulo or '',
            p.contenido or '',
            p.categoria or '',
            p.estado_incidencia or '',
            p.ubicacion or '',
            p.nombre_autor or '',
            p.latitud if p.latitud is not None else '',
            p.longitud if p.longitud is not None else '',
            p.likes,
            p.fecha_creacion.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


@login_required
@_solo_administrador
@require_POST
def importar_incidentes_csv(request):
    """
    Importa incidentes desde un CSV (RF-005, Fase 3).
    Columnas usadas: titulo, contenido, categoria, estado, ubicacion,
    latitud, longitud (la columna 'id' se ignora, siempre se crean nuevos).
    El autor de los reportes importados es el administrador que importa; el
    nombre original se conserva en autor_nombre si viene en el CSV.
    Devuelve un JSON con el resumen (creados, errores).
    """
    import csv
    import io as _io

    archivo = request.FILES.get('archivo')
    if not archivo:
        return JsonResponse({'status': 'error', 'message': 'No se recibió ningún archivo.'}, status=400)
    if not archivo.name.lower().endswith('.csv'):
        return JsonResponse({'status': 'error', 'message': 'El archivo debe ser un .csv'}, status=400)

    try:
        datos = archivo.read().decode('utf-8-sig')  # -sig quita el BOM si lo hay
    except UnicodeDecodeError:
        return JsonResponse({'status': 'error', 'message': 'No se pudo leer el archivo (debe ser UTF-8).'}, status=400)

    lector = csv.DictReader(_io.StringIO(datos))
    if not lector.fieldnames or 'contenido' not in [c.strip().lower() for c in lector.fieldnames]:
        return JsonResponse({
            'status': 'error',
            'message': "El CSV debe tener al menos la columna 'contenido'. Columnas esperadas: " + ', '.join(INCIDENTES_CSV_COLUMNAS),
        }, status=400)

    cats_validas = {c[0] for c in Publicacion.Categoria.choices}
    estados_validos = {c[0] for c in Publicacion.EstadoIncidencia.choices}

    creados = 0
    errores = []
    for i, fila in enumerate(lector, start=2):  # fila 1 = encabezado
        fila = {(k or '').strip().lower(): (v or '').strip() for k, v in fila.items()}
        contenido = fila.get('contenido', '')
        if not contenido:
            errores.append(f'Fila {i}: sin contenido, omitida.')
            continue

        categoria = fila.get('categoria', '').upper()
        if categoria not in cats_validas:
            categoria = Publicacion.Categoria.VIAS
        estado = fila.get('estado', '').upper()
        if estado not in estados_validos:
            estado = Publicacion.EstadoIncidencia.REPORTADO

        def _num(valor):
            try:
                return float(valor) if valor not in ('', None) else None
            except (ValueError, TypeError):
                return None

        try:
            Publicacion.objects.create(
                autor=request.user,
                autor_nombre=fila.get('autor', '') or request.user.username,
                titulo=fila.get('titulo', '')[:200],
                contenido=contenido,
                categoria=categoria,
                estado_incidencia=estado,
                ubicacion=fila.get('ubicacion', '') or None,
                latitud=_num(fila.get('latitud')),
                longitud=_num(fila.get('longitud')),
            )
            creados += 1
        except Exception as e:
            errores.append(f'Fila {i}: {e}')

    return JsonResponse({
        'status': 'ok',
        'creados': creados,
        'errores': errores,
        'message': f'{creados} incidente(s) importado(s).' + (f' {len(errores)} con problemas.' if errores else ''),
    })


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

    # ── Moderación de lenguaje ──
    if contiene_lenguaje_inapropiado(titulo) or contiene_lenguaje_inapropiado(contenido):
        return JsonResponse({'status': 'error', 'message': MENSAJE_RECHAZO}, status=400)

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
        if not es_admin:
            return JsonResponse({'status': 'error', 'message': 'No tienes permiso para censurar este comentario.'}, status=403)
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
    if not texto and not comentario.imagen:
        return JsonResponse({'status': 'error', 'message': 'El comentario no puede estar vacío.'}, status=400)

    # ── Moderación de lenguaje ──
    if texto and contiene_lenguaje_inapropiado(texto):
        return JsonResponse({'status': 'error', 'message': MENSAJE_RECHAZO}, status=400)

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
    """Permite cambiar el estado de una incidencia (ej. marcar como RESUELTA o DECLINADO con motivo)."""
    if not _es_admin(request.user):
        return JsonResponse({'status': 'error', 'message': 'No tienes permisos para cambiar el estado.'}, status=403)

    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    nuevo_estado = request.POST.get('estado', Publicacion.EstadoIncidencia.RESUELTA).upper().strip()
    if nuevo_estado not in [c[0] for c in Publicacion.EstadoIncidencia.choices]:
        return JsonResponse({'status': 'error', 'message': 'Estado no válido.'}, status=400)

    if nuevo_estado == Publicacion.EstadoIncidencia.DECLINADO:
        motivo_raw = (request.POST.get('motivo') or '').strip()
        detalle = (request.POST.get('detalle') or '').strip()
        catalogo = dict(Publicacion.MotivoDeclinacion.choices)
        motivo_base = catalogo.get(
            motivo_raw.upper(),
            motivo_raw or Publicacion.MotivoDeclinacion.NO_PROCEDE.label,
        )
        if detalle:
            motivo_final = f"{motivo_base} — {detalle}"
        else:
            motivo_final = str(motivo_base)
        publicacion.estado_incidencia = nuevo_estado
        publicacion.motivo_declinacion = motivo_final[:255]
        publicacion.save(update_fields=['estado_incidencia', 'motivo_declinacion'])

        extra_notif = f"Declinado — Motivo: {publicacion.motivo_declinacion}"[:255]
        crear_notificacion(
            destinatario=publicacion.autor, actor=request.user,
            tipo=Notificacion.Tipo.CAMBIO_ESTADO, publicacion=publicacion,
            extra=extra_notif, permitir_auto=True,
        )
        mensaje_respuesta = f"Incidencia #{publicacion.id} declinada ({publicacion.motivo_declinacion}). Se notificó al ciudadano."
    else:
        publicacion.estado_incidencia = nuevo_estado
        publicacion.motivo_declinacion = ''
        publicacion.save(update_fields=['estado_incidencia', 'motivo_declinacion'])

        crear_notificacion(
            destinatario=publicacion.autor, actor=request.user,
            tipo=Notificacion.Tipo.CAMBIO_ESTADO, publicacion=publicacion,
            extra=publicacion.get_estado_incidencia_display(),
        )
        mensaje_respuesta = f'Incidencia #{publicacion.id} marcada como {publicacion.get_estado_incidencia_display()}.'

    # La actividad se deriva directamente de la publicación (tiempo real y sincronizada)
    actividad = _actividad_desde_publicacion(publicacion)

    return JsonResponse({
        'status': 'ok',
        'message': mensaje_respuesta,
        'id': publicacion.id,
        'estado': publicacion.estado_incidencia,
        'motivo_declinacion': publicacion.motivo_declinacion,
        'es_resuelta': publicacion.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA,
        'es_declinada': publicacion.estado_incidencia == Publicacion.EstadoIncidencia.DECLINADO,
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
        Publicacion.objects.select_related('autor').prefetch_related(
            'comentarios__respuestas__autor', 'comentarios__autor', 'reposteos'
        ),
        id=publicacion_id
    )
    _anotar_interacciones_usuario([publicacion], request.user)

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
    qs = Publicacion.objects.all().select_related('autor').prefetch_related(
        'comentarios__respuestas__autor', 'comentarios__autor', 'reposteos'
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
    _anotar_interacciones_usuario(publicaciones, request.user)

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


# ==========================================================================
# Notificaciones
# ==========================================================================
@login_required
def notificaciones_view(request):
    """
    Vista de Notificaciones del usuario autenticado. Soporta filtro por categoría
    (todas / publicaciones / reportes) y agrupa por día (hoy / ayer / anteriores).
    Al entrar, se marcan como leídas.
    """
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
