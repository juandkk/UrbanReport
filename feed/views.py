from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .models import Publicacion, Comentario, TrendingTopic, ActividadReciente
from usuarios.models import Usuario


@login_required
def feed_comunitario_view(request):
    # Determine mode: 'general' (Vista 4: "Estadísticas") or 'mis_estadisticas' (Vista 5: "Mis estadísticas")
    modo = request.GET.get('modo', 'general')

    # Seed sample data if empty so UI looks 100% complete and identical to designs
    if not Publicacion.objects.exists():
        _seed_demo_data()

    publicaciones = Publicacion.objects.prefetch_related('comentarios').all()
    trending_topics = TrendingTopic.objects.all()
    actividades = ActividadReciente.objects.all()

    # Form handling for new community post
    if request.method == 'POST':
        contenido = request.POST.get('contenido', '').strip()
        imagen = request.FILES.get('imagen')
        if contenido:
            # If user is authenticated, use user, else find or create demo user
            if request.user.is_authenticated:
                user = request.user
                autor_nombre = f"{user.first_name} {user.last_name}".strip() or user.username
            else:
                user, _ = Usuario.objects.get_or_create(
                    username='ciudadano_demo',
                    defaults={
                        'email': 'demo@ciudad.gov',
                        'first_name': 'Ciudadano',
                        'last_name': 'Activo',
                        'rol': Usuario.Rol.CIUDADANO
                    }
                )
                autor_nombre = 'Ciudadano Activo'

            Publicacion.objects.create(
                autor=user,
                autor_nombre=autor_nombre,
                contenido=contenido,
                imagen=imagen
            )
            return redirect(f"{request.path}?modo={modo}")

    context = {
        'publicaciones': publicaciones,
        'trending_topics': trending_topics,
        'actividades': actividades,
        'modo': modo,
        'active_menu': 'feed',
    }
    return render(request, 'feed/feed_comunitario.html', context)


@require_POST
def dar_like_ajax(request, publicacion_id):
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    publicacion.likes += 1
    publicacion.save(update_fields=['likes'])
    return JsonResponse({'status': 'ok', 'likes': publicacion.likes})


@require_POST
def agregar_comentario_ajax(request, publicacion_id):
    publicacion = get_object_or_404(Publicacion, id=publicacion_id)
    texto = request.POST.get('texto', '').strip()
    if not texto:
        return JsonResponse({'status': 'error', 'message': 'El comentario no puede estar vacío.'}, status=400)

    if request.user.is_authenticated:
        autor = request.user
        autor_nombre = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    else:
        autor = None
        autor_nombre = request.POST.get('autor_nombre', 'Vecino de la comunidad')

    comentario = Comentario.objects.create(
        publicacion=publicacion,
        autor=autor,
        autor_nombre=autor_nombre,
        texto=texto
    )

    return JsonResponse({
        'status': 'ok',
        'autor_nombre': comentario.autor_nombre,
        'texto': comentario.texto,
        'total_comentarios': publicacion.comentarios.count()
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

    # Post 1 (Ana García)
    p1 = Publicacion.objects.create(
        autor=user_ana,
        autor_nombre='Ana García',
        contenido='Gran bache en la Avenida Central, esquina con Calle 4. Está causando mucho tráfico y riesgo para los ciclistas. Por favor, precaución si pasan por ahí.',
        likes=24,
        estado_incidencia=Publicacion.EstadoIncidencia.REPORTADO,
        ubicacion='Avenida Central esquina con Calle 4'
    )
    Comentario.objects.create(
        publicacion=p1,
        autor_nombre='Carlos M.',
        texto='Ya reporté esto en la app también, ojalá lo arreglen pronto.'
    )

    # Post 2 (Luis Rodríguez)
    Publicacion.objects.create(
        autor=user_luis,
        autor_nombre='Luis Rodríguez',
        contenido='La luminaria del Parque Los Pinos ya fue reparada. Gracias a las cuadrillas por la rápida atención.',
        likes=112,
        estado_incidencia=Publicacion.EstadoIncidencia.RESUELTA,
        ubicacion='Parque Los Pinos'
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
