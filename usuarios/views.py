from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Usuario
from .forms import LoginForm, RegistroForm, RecuperarContrasenaForm


def login_view(request):
    if request.user.is_authenticated:
        if request.user.rol == Usuario.Rol.ADMINISTRADOR or request.user.is_staff or request.user.is_superuser:
            return redirect('panel_administrador')
        return redirect('feed_comunitario')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email_or_user = form.cleaned_data['email_or_username']
            password = form.cleaned_data['password']
            recordarme = form.cleaned_data['recordarme']

            # Intentar autenticación por nombre de usuario
            user = authenticate(request, username=email_or_user, password=password)
            if user is None:
                # Intentar por email
                try:
                    user_obj = Usuario.objects.get(email__iexact=email_or_user)
                    user = authenticate(request, username=user_obj.username, password=password)
                except Usuario.DoesNotExist:
                    user = None

            if user is not None:
                login(request, user)
                if not recordarme:
                    request.session.set_expiry(0)
                else:
                    request.session.set_expiry(1209600)  # 2 semanas
                # Redirigir según el rol del usuario
                if user.rol == Usuario.Rol.ADMINISTRADOR or user.is_staff or user.is_superuser:
                    return redirect('panel_administrador')
                return redirect('feed_comunitario')
            else:
                messages.error(request, 'Credenciales incorrectas. Verifica tu correo y contraseña.')
    else:
        form = LoginForm()

    return render(request, 'usuarios/login.html', {
        'form': form,
        'active_tab': 'login'
    })


def registro_view(request):
    if request.user.is_authenticated:
        return redirect('feed_comunitario')

    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f'¡Bienvenido a UrbanReport, {user.username}!')
            return redirect('feed_comunitario')
        else:
            messages.error(request, 'Por favor corrige los errores indicados en el formulario.')
    else:
        form = RegistroForm()

    return render(request, 'usuarios/registro.html', {
        'form': form,
        'active_tab': 'registro'
    })


def recuperar_contrasena_view(request):
    mensaje_enviado = False
    correo_destino = ''

    if request.method == 'POST':
        form = RecuperarContrasenaForm(request.POST)
        if form.is_valid():
            correo_destino = form.cleaned_data['email']
            mensaje_enviado = True
            messages.success(
                request,
                f'Instrucciones enviadas exitosamente a {correo_destino}.'
            )
    else:
        form = RecuperarContrasenaForm()

    return render(request, 'usuarios/recuperar_contrasena.html', {
        'form': form,
        'mensaje_enviado': mensaje_enviado,
        'correo_destino': correo_destino,
    })


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def perfil_view(request, username=None):
    """
    Vista "Perfil": muestra las publicaciones de un usuario junto a una tarjeta
    lateral con su información y sus seguidores/seguidos. Si no se indica username,
    muestra el perfil del usuario autenticado ("Mi Perfil"). Sirve para ciudadanos
    y administradores; el rol se refleja en la etiqueta y el menú lateral.
    """
    from django.shortcuts import get_object_or_404
    # Importaciones locales para evitar dependencias circulares entre apps
    from feed.models import Publicacion, ReaccionPublicacion, ReaccionComentario

    if username:
        usuario = get_object_or_404(Usuario, username=username)
    else:
        usuario = request.user

    es_propio_perfil = (usuario == request.user)
    ya_lo_sigo = False if es_propio_perfil else request.user.sigue_a(usuario)

    publicaciones = list(
        Publicacion.objects.filter(autor=usuario)
        .order_by('-id')
        .prefetch_related('comentarios__respuestas', 'comentarios__autor', 'autor')
    )

    # Mapear las reacciones de QUIEN VE el perfil para colorear los botones (igual que en el feed)
    user_post_reactions = {}
    user_comment_reactions = {}
    for r in ReaccionPublicacion.objects.filter(usuario=request.user, publicacion__in=publicaciones):
        user_post_reactions[r.publicacion_id] = r.tipo

    all_comment_ids = []
    for p in publicaciones:
        for c in p.comentarios.all():
            all_comment_ids.append(c.id)
    if all_comment_ids:
        for r in ReaccionComentario.objects.filter(usuario=request.user, comentario_id__in=all_comment_ids):
            user_comment_reactions[r.comentario_id] = r.tipo

    for p in publicaciones:
        p.user_reaction = user_post_reactions.get(p.id)
        for c in p.comentarios.all():
            c.user_reaction = user_comment_reactions.get(c.id)
            for rep in c.respuestas.all():
                rep.user_reaction = user_comment_reactions.get(rep.id)

    # Estadísticas reales derivadas de las publicaciones del usuario
    total_publicaciones = len(publicaciones)
    total_resueltas = sum(
        1 for p in publicaciones
        if p.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA
    )

    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username

    confianza = usuario.nivel_confianza()

    context = {
        'perfil_usuario': usuario,
        'nombre_completo': nombre_completo,
        'confianza': confianza,
        'publicaciones': publicaciones,
        'total_publicaciones': total_publicaciones,
        'total_resueltas': total_resueltas,
        'total_seguidores': usuario.total_seguidores,
        'total_seguidos': usuario.total_seguidos,
        'es_propio_perfil': es_propio_perfil,
        'ya_lo_sigo': ya_lo_sigo,
        'es_admin': usuario.rol == Usuario.Rol.ADMINISTRADOR or usuario.is_staff or usuario.is_superuser,
        'ubicaciones': UBICACIONES_MEDELLIN,
        'active_menu': 'perfil',
    }
    return render(request, 'usuarios/perfil.html', context)


@login_required
@require_POST
def toggle_seguir_ajax(request, username):
    """
    Alterna seguir / dejar de seguir a otro usuario. Devuelve el nuevo estado y
    los conteos actualizados de seguidores para refrescar la UI sin recargar.
    """
    from django.shortcuts import get_object_or_404
    from .models import Seguimiento

    objetivo = get_object_or_404(Usuario, username=username)

    if objetivo == request.user:
        return JsonResponse(
            {'status': 'error', 'message': 'No puedes seguirte a ti mismo.'},
            status=400,
        )

    relacion = Seguimiento.objects.filter(seguidor=request.user, seguido=objetivo).first()
    if relacion:
        relacion.delete()
        siguiendo = False
    else:
        Seguimiento.objects.create(seguidor=request.user, seguido=objetivo)
        siguiendo = True

    return JsonResponse({
        'status': 'ok',
        'siguiendo': siguiendo,
        'total_seguidores': objetivo.total_seguidores,
        'total_seguidos': objetivo.total_seguidos,
        'message': f'Ahora sigues a {objetivo.username}.' if siguiendo else f'Dejaste de seguir a {objetivo.username}.',
    })


# Opciones de ubicación (sin coordenadas exactas): Medellín y sus zonas.
UBICACIONES_MEDELLIN = [
    'Medellín',
    'Medellín - El Poblado',
    'Medellín - Laureles',
    'Medellín - Belén',
    'Medellín - La Candelaria (Centro)',
    'Medellín - Robledo',
    'Medellín - Buenos Aires',
    'Medellín - Aranjuez',
    'Medellín - Castilla',
    'Medellín - Guayabal',
    'Medellín - Manrique',
    'Medellín - San Javier (Comuna 13)',
]


def _serializar_usuario_relacion(u, viewer):
    """Datos mínimos de un usuario para las listas de seguidores/seguidos."""
    nombre = f"{u.first_name} {u.last_name}".strip() or u.username
    return {
        'username': u.username,
        'nombre': nombre,
        'iniciales': (nombre[:2].upper() or 'UR'),
        'avatar_url': u.avatar.url if u.avatar else None,
        'rol': u.get_rol_display(),
        'perfil_url': f'/perfil/{u.username}/',
        'seguir_url': f'/perfil/{u.username}/seguir/',
        'lo_sigo': viewer.sigue_a(u),
        'es_yo': (u == viewer),
    }


@login_required
def lista_seguidores_ajax(request, username):
    """Devuelve la lista de usuarios que siguen a <username> (estilo Instagram)."""
    from django.shortcuts import get_object_or_404
    usuario = get_object_or_404(Usuario, username=username)
    seguidores = usuario.seguidores.all().order_by('username')
    data = [_serializar_usuario_relacion(u, request.user) for u in seguidores]
    return JsonResponse({'status': 'ok', 'titulo': 'Seguidores', 'usuarios': data})


@login_required
def lista_seguidos_ajax(request, username):
    """Devuelve la lista de usuarios que <username> sigue (estilo Instagram)."""
    from django.shortcuts import get_object_or_404
    usuario = get_object_or_404(Usuario, username=username)
    seguidos = usuario.seguidos.all().order_by('username')
    data = [_serializar_usuario_relacion(u, request.user) for u in seguidos]
    return JsonResponse({'status': 'ok', 'titulo': 'Seguidos', 'usuarios': data})


@login_required
@require_POST
def editar_perfil_ajax(request):
    """
    Actualiza el perfil del usuario autenticado: nombre, ubicación (de una lista
    predefinida, sin coordenadas exactas) y foto de perfil (sanitizada: solo
    PNG/JPG y re-codificada por seguridad).
    """
    # Reutilizamos la sanitización de imágenes de la app feed
    from feed.views import sanitizar_imagen, ImagenInvalida

    usuario = request.user

    nombre = request.POST.get('nombre', '').strip()
    ubicacion = request.POST.get('ubicacion', '').strip()
    avatar = request.FILES.get('avatar')
    eliminar_avatar = request.POST.get('eliminar_avatar', '').strip().lower() in ('1', 'true', 'si', 'sí')

    # Nombre: se guarda en first_name (y limpiamos last_name para evitar duplicidad)
    if nombre:
        partes = nombre.split()
        usuario.first_name = partes[0][:150]
        usuario.last_name = ' '.join(partes[1:])[:150] if len(partes) > 1 else ''

    # Ubicación: solo se acepta si está dentro de las opciones válidas
    if ubicacion:
        if ubicacion not in UBICACIONES_MEDELLIN:
            return JsonResponse(
                {'status': 'error', 'message': 'Ubicación no válida.'},
                status=400,
            )
        usuario.barrio_vereda = ubicacion

    # Avatar:
    #  - Si se pide eliminar, se borra el archivo y se limpia el campo (vuelve al SVG por defecto).
    #  - Si se sube uno nuevo, se valida y sanitiza. Subir tiene prioridad sobre eliminar.
    if avatar is not None:
        try:
            avatar_limpio = sanitizar_imagen(avatar)
        except ImagenInvalida as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        # Borrar el archivo anterior para no dejar huérfanos en media/
        if usuario.avatar:
            usuario.avatar.delete(save=False)
        usuario.avatar = avatar_limpio
    elif eliminar_avatar and usuario.avatar:
        usuario.avatar.delete(save=False)
        usuario.avatar = None

    usuario.save()

    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username
    return JsonResponse({
        'status': 'ok',
        'message': '¡Perfil actualizado correctamente!',
        'nombre': nombre_completo,
        'ubicacion': usuario.barrio_vereda or 'Sin ubicación registrada',
        'avatar_url': usuario.avatar.url if usuario.avatar else None,
        'tiene_avatar': bool(usuario.avatar),
    })
