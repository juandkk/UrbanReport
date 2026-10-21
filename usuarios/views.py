from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone
from .models import Usuario, ConfiguracionSistema
from .forms import (
    LoginForm,
    RegistroForm,
    RecuperarContrasenaForm,
    CompletarPerfilForm,
    ConfiguracionForm,
    AdminConfiguracionForm,
    ParametrosAlertaForm,
    NuevoAdminForm,
)


def _es_administrador(user):
    """Criterio único de administrador (igual que el context processor es_admin)."""
    return user.is_authenticated and (
        getattr(user, 'rol', None) == Usuario.Rol.ADMINISTRADOR
        or user.is_staff
        or user.is_superuser
    )

def recuperar_contrasena_view(request, *args, **kwargs):
    """
    Recuperación de contraseña (temporalmente fuera de servicio).

    Por motivos de seguridad y para prevenir el restablecimiento no autorizado de cuentas,
    la función de recuperación de contraseñas se encuentra deshabilitada de forma temporal.
    No se aceptan solicitudes POST ni se generan tokens o enlaces de restablecimiento.
    """
    return render(request, 'usuarios/password_reset_form.html', {
        'servicio_deshabilitado': True,
    })


def recuperar_contrasena_enviado_view(request):
    """Redirige a la vista de recuperación fuera de servicio."""
    return redirect('recuperar_contrasena')


def login_view(request):
    en_mantenimiento = ConfiguracionSistema.esta_en_mantenimiento()
    if request.user.is_authenticated:
        if _es_administrador(request.user):
            return redirect('panel_administrador')
        if en_mantenimiento:
            return render(request, 'usuarios/mantenimiento.html', status=503)
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
                # Si el sistema está en modo mantenimiento, solo los administradores pueden ingresar
                if en_mantenimiento and not _es_administrador(user):
                    messages.error(
                        request,
                        'El sistema se encuentra en modo mantenimiento. El acceso para ciudadanos está suspendido temporalmente.',
                    )
                else:
                    login(request, user)
                    if not recordarme:
                        request.session.set_expiry(0)
                    else:
                        request.session.set_expiry(1209600)  # 2 semanas
                    # Redirigir según el rol del usuario
                    if _es_administrador(user):
                        return redirect('panel_administrador')
                    return redirect('feed_comunitario')
            else:
                messages.error(request, 'Credenciales incorrectas. Verifica tu correo y contraseña.')
    else:
        form = LoginForm()

    return render(request, 'usuarios/login.html', {
        'form': form,
        'active_tab': 'login',
        'modo_mantenimiento': en_mantenimiento,
    })


@login_required
def completar_perfil_view(request):
    """
    Pide a los usuarios con el perfil incompleto (típicamente los que entraron
    por Google/Facebook) que completen sus datos de contacto y ubicación.
    Si el perfil ya está completo, redirige al feed.
    """
    if not request.user.perfil_incompleto():
        return redirect('feed_comunitario')

    if request.method == 'POST':
        form = CompletarPerfilForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, '¡Gracias! Tu perfil quedó completo.')
            return redirect('feed_comunitario')
        else:
            messages.error(request, 'Por favor completa los campos obligatorios.')
    else:
        form = CompletarPerfilForm(instance=request.user)

    return render(request, 'usuarios/completar_perfil.html', {'form': form})


def registro_view(request):
    if request.user.is_authenticated:
        return redirect('feed_comunitario')

    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Con varios AUTHENTICATION_BACKENDS, login() necesita saber qué backend usar.
            # El registro con usuario y contraseña corresponde al backend de Django.
            
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
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


# La recuperación de contraseña ahora usa el sistema nativo de Django
# (PasswordResetView y familia), configurado en usuarios/urls.py con las
# plantillas usuarios/password_reset_*.html.


def logout_view(request):
    if request.user.is_authenticated:
        # Registrar el instante exacto de desconexión para reflejar "Último Acceso" real
        Usuario.objects.filter(pk=request.user.pk).update(last_login=timezone.now())
    logout(request)
    return redirect('login')


@login_required
def configuracion_view(request):
    """
    Vista "Configuración" del perfil CIUDADANO. SIEMPRE opera sobre el usuario
    autenticado (request.user): no acepta ningún id/username externo, de modo que
    un usuario jamás puede ver ni modificar la configuración de otra cuenta.

    Si el usuario es ADMINISTRADOR, se redirige a su propia vista de configuración
    (más completa), de modo que el botón "Configuración" del perfil lleva a cada
    rol a la vista que le corresponde.

    GET  -> muestra el formulario precargado con los datos actuales del usuario
            (campos vacíos si aún no ha guardado nada).
    POST -> valida en el servidor y, si todo es correcto, persiste de forma
            atómica (transacción) información personal, residencia y las dos
            preferencias de notificaciones. Si algo falla, no guarda nada.

    Interruptores de notificaciones (semántica directa): ENCENDIDO = recibir las
    notificaciones correspondientes; APAGADO = no recibirlas. Estos valores se
    guardan en Usuario.notif_feed / Usuario.notif_reportes y los respeta
    crear_notificacion() al momento de generar cada notificación.
    """
    usuario = request.user

    # Los administradores tienen su propia vista de configuración.
    if _es_administrador(usuario):
        return redirect('configuracion_admin')

    if request.method == 'POST':
        # Semántica directa de los interruptores: ENCENDIDO = recibir notificaciones.
        # El checkbox marca "on" cuando está activo; su ausencia significa apagado.
        recibir_feed = request.POST.get('notif_feed') in ('on', '1', 'true', 'True')
        recibir_reportes = request.POST.get('notif_reportes') in ('on', '1', 'true', 'True')
        if 'mostrar_estado_actividad' in request.POST or 'mostrar_estado_actividad_present' in request.POST:
            mostrar_act = request.POST.get('mostrar_estado_actividad') in ('on', '1', 'true', 'True')
        else:
            mostrar_act = usuario.mostrar_estado_actividad

        # Copia mutable del POST con los valores que espera el ModelForm.
        datos = request.POST.copy()
        datos['notif_feed'] = 'on' if recibir_feed else ''
        datos['notif_reportes'] = 'on' if recibir_reportes else ''
        datos['mostrar_estado_actividad'] = 'on' if mostrar_act else ''

        form = ConfiguracionForm(datos, instance=usuario)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except Exception:
                messages.error(request, 'Ocurrió un error al guardar. Inténtalo de nuevo.')
            else:
                messages.success(request, 'Cambios guardados correctamente.')
                return redirect('configuracion')
        else:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        form = ConfiguracionForm(instance=usuario)

    context = {
        'form': form,
        # Estado de los interruptores: encendido = recibir = valor directo de la preferencia.
        'notif_feed': usuario.notif_feed,
        'notif_reportes': usuario.notif_reportes,
        'mostrar_estado_actividad': usuario.mostrar_estado_actividad,
        'active_menu': 'perfil',
    }
    return render(request, 'usuarios/configuracion.html', context)


@login_required
@require_POST
def eliminar_cuenta_view(request):
    """
    Elimina permanentemente la cuenta del ciudadano autenticado.
    - Exclusivo para cuentas de ciudadano (los administradores no pueden borrarse desde aquí).
    - Exige confirmación explícita escribiendo 'ELIMINAR'.
    - Limpia archivos multimedia (avatar e imágenes de publicaciones propias) antes de eliminar.
    - Cierra la sesión y elimina el usuario dentro de una transacción atómica.
    """
    from django.urls import reverse
    from feed.models import Comentario, Publicacion

    es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    usuario = request.user

    if _es_administrador(usuario):
        msg = 'Las cuentas de administrador no pueden eliminarse desde esta sección.'
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=403)
        messages.error(request, msg)
        return redirect('configuracion_admin')

    confirmacion = (request.POST.get('confirmacion') or '').strip()
    if confirmacion != 'ELIMINAR':
        msg = 'Debes escribir exactamente «ELIMINAR» para confirmar la eliminación de tu cuenta.'
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=400)
        messages.error(request, msg)
        return redirect('configuracion')

    try:
        with transaction.atomic():
            for pub in Publicacion.objects.filter(autor=usuario).only('imagen'):
                if pub.imagen:
                    pub.imagen.delete(save=False)
            for com in Comentario.objects.filter(autor=usuario).only('imagen'):
                if com.imagen:
                    com.imagen.delete(save=False)
            if usuario.avatar:
                usuario.avatar.delete(save=False)
            logout(request)
            usuario.delete()
    except Exception:
        msg = 'Ocurrió un error al intentar eliminar la cuenta. Inténtalo de nuevo.'
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=500)
        messages.error(request, msg)
        return redirect('configuracion')

    messages.success(request, 'Tu cuenta ha sido eliminada permanentemente.')
    if es_ajax:
        return JsonResponse({
            'status': 'ok',
            'message': 'Tu cuenta ha sido eliminada permanentemente.',
            'redirect_url': reverse('login'),
        })
    return redirect('login')


# ==========================================================================
# Configuración del ADMINISTRADOR
# ==========================================================================

def _tiempo_relativo(dt):
    """Devuelve una etiqueta tipo 'Hace 5 min' / 'Hace 2 h' / 'Nunca' para un datetime."""
    if not dt:
        return 'Nunca'
    delta = timezone.now() - dt
    segundos = int(delta.total_seconds())
    if segundos < 60:
        return 'Hace un momento'
    minutos = segundos // 60
    if minutos < 60:
        return f'Hace {minutos} min'
    horas = minutos // 60
    if horas < 24:
        return f'Hace {horas} h'
    dias = horas // 24
    return f'Hace {dias} d'


def _ids_usuarios_con_sesion_activa():
    """Devuelve el conjunto de IDs (int) de usuarios con al menos una sesión activa no expirada."""
    from django.contrib.sessions.models import Session
    ids = set()
    ahora = timezone.now()
    for sesion in Session.objects.filter(expire_date__gt=ahora).only('session_data'):
        try:
            datos = sesion.get_decoded()
            uid = datos.get('_auth_user_id')
            if uid is not None:
                ids.add(int(uid))
        except Exception:
            continue
    return ids


def _formatear_ultimo_acceso(dt, en_linea=False):
    """
    Devuelve una tupla (etiqueta_relativa, fecha_exacta) para la última conexión del administrador.
    """
    if not dt:
        return ('Nunca', 'Sin conexiones registradas')
    fecha_local = timezone.localtime(dt).strftime('%d/%m/%Y %H:%M')
    segundos = int((timezone.now() - dt).total_seconds())
    if en_linea and segundos < 60:
        return ('Ahora mismo', fecha_local)
    return (_tiempo_relativo(dt), fecha_local)


def _serializar_admin_estado(admin_user, sesiones_activas=None, usuario_actual=None, ahora=None):
    """Construye la fila de estado de conexión y metadatos de un administrador."""
    if ahora is None:
        ahora = timezone.now()
    if sesiones_activas is None:
        sesiones_activas = _ids_usuarios_con_sesion_activa()

    es_actual = bool(usuario_actual and admin_user.id == usuario_actual.id)
    tiene_sesion = es_actual or (admin_user.id in sesiones_activas)
    ultimo_dt = ahora if es_actual else admin_user.last_login
    actividad_reciente = bool(ultimo_dt and (ahora - ultimo_dt).total_seconds() <= 300)
    en_linea = bool(tiene_sesion and actividad_reciente)

    ultimo_acceso, ultimo_acceso_fecha = _formatear_ultimo_acceso(ultimo_dt, en_linea=en_linea)
    nombre = f"{admin_user.first_name} {admin_user.last_name}".strip() or admin_user.username
    rol_label = 'Super Admin' if admin_user.is_superuser else 'Administrador'

    return {
        'id': admin_user.id,
        'username': admin_user.username,
        'nombre': nombre,
        'rol_label': rol_label,
        'ultimo_acceso': ultimo_acceso,
        'ultimo_acceso_fecha': ultimo_acceso_fecha,
        'en_linea': en_linea,
        'es_superuser': admin_user.is_superuser,
        'es_actual': es_actual,
    }


def _listar_administradores(usuario_actual=None):
    """
    Lista de administradores activos para la tabla inferior de la vista.
    Criterio de admin: rol ADMINISTRADOR o is_staff o is_superuser.
    'En línea' si posee sesión activa y tuvo actividad en los últimos 5 minutos.
    """
    from django.db.models import Q
    ahora = timezone.now()
    if usuario_actual and usuario_actual.is_authenticated:
        if not usuario_actual.last_login or (ahora - usuario_actual.last_login).total_seconds() >= 10:
            Usuario.objects.filter(pk=usuario_actual.pk).update(last_login=ahora)
            usuario_actual.last_login = ahora

    admins = list(
        Usuario.objects.filter(
            Q(rol=Usuario.Rol.ADMINISTRADOR) | Q(is_staff=True) | Q(is_superuser=True)
        ).distinct().order_by('-last_login', 'username')
    )
    sesiones_activas = _ids_usuarios_con_sesion_activa()
    filas = [
        _serializar_admin_estado(a, sesiones_activas=sesiones_activas, usuario_actual=usuario_actual, ahora=ahora)
        for a in admins
    ]
    filas.sort(key=lambda x: (not x['en_linea'], x['ultimo_acceso'] == 'Nunca'))
    return filas


@login_required
def configuracion_admin_view(request):
    """
    Vista "Configuración" EXCLUSIVA del ADMINISTRADOR.

    Un ciudadano que intente entrar (incluso escribiendo la URL) recibe 403.
    Reúne, en un solo formulario:
      - Información personal + Residencia (reutiliza AdminConfiguracionForm,
        que hereda del form del ciudadano).
      - Gestión del sistema (modo mantenimiento, info de backups).
      - Parámetros de alerta (umbral crítico y tiempo máx. respuesta).
      - Tabla de administradores activos.

    SIEMPRE opera sobre request.user para los datos personales: un admin no puede
    editar los datos personales de otro admin desde este formulario.
    """
    if not _es_administrador(request.user):
        return HttpResponseForbidden(
            '<h2>403 — Acceso denegado</h2>'
            '<p>Esta sección es exclusiva para administradores.</p>'
        )

    usuario = request.user
    config = ConfiguracionSistema.obtener()

    if request.method == 'POST':
        datos_admin = request.POST.copy()
        if 'mostrar_estado_actividad' in request.POST or 'mostrar_estado_actividad_present' in request.POST:
            mostrar_act_adm = request.POST.get('mostrar_estado_actividad') in ('on', '1', 'true', 'True')
        else:
            mostrar_act_adm = usuario.mostrar_estado_actividad
        datos_admin['mostrar_estado_actividad'] = 'on' if mostrar_act_adm else ''
        form = AdminConfiguracionForm(datos_admin, instance=usuario)
        alerta_form = ParametrosAlertaForm(request.POST, instance=config)

        if form.is_valid() and alerta_form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    cfg_inst = alerta_form.save(commit=False)
                    if 'modo_mantenimiento' in request.POST or 'modo_mantenimiento_present' in request.POST:
                        cfg_inst.modo_mantenimiento = request.POST.get('modo_mantenimiento') in ('on', '1', 'true', 'True')
                    cfg_inst.save()
            except Exception:
                messages.error(request, 'Ocurrió un error al guardar. Inténtalo de nuevo.')
            else:
                messages.success(request, 'Cambios guardados correctamente.')
                return redirect('configuracion_admin')
        else:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        form = AdminConfiguracionForm(instance=usuario)
        alerta_form = ParametrosAlertaForm(instance=config)

    context = {
        'form': form,
        'alerta_form': alerta_form,
        'config': config,
        'ultimo_backup_rel': _tiempo_relativo(config.ultimo_backup),
        'administradores': _listar_administradores(usuario_actual=usuario),
        'nuevo_admin_form': NuevoAdminForm(),
        'mostrar_estado_actividad': usuario.mostrar_estado_actividad,
        'active_menu': 'perfil',
    }
    return render(request, 'usuarios/configuracion_admin.html', context)


@login_required
def estado_administradores_ajax(request):
    """Devuelve en JSON la lista actualizada de administradores, su última conexión y estado en línea."""
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)
    return JsonResponse({
        'status': 'ok',
        'administradores': _listar_administradores(usuario_actual=request.user),
    })


@login_required
@require_POST
def toggle_modo_mantenimiento_ajax(request):
    """Activa/desactiva el modo mantenimiento. Solo administradores."""
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)
    config = ConfiguracionSistema.obtener()
    activar = request.POST.get('activar') in ('on', '1', 'true', 'True')
    config.modo_mantenimiento = activar
    config.save(update_fields=['modo_mantenimiento', 'actualizado_en'])
    return JsonResponse({
        'status': 'ok',
        'modo_mantenimiento': config.modo_mantenimiento,
        'message': 'Modo mantenimiento activado. El acceso para ciudadanos está suspendido.' if activar else 'Modo mantenimiento desactivado. El acceso público está habilitado.',
    })


@login_required
@require_POST
def ejecutar_backup_ajax(request):
    """
    Registra un backup manual: actualiza la marca de tiempo del último respaldo.
    Solo administradores. (El respaldo real de la BD lo gestiona la infraestructura;
    aquí se deja registrada la ejecución, que es lo que la vista necesita mostrar.)
    """
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)
    config = ConfiguracionSistema.obtener()
    config.ultimo_backup = timezone.now()
    config.save(update_fields=['ultimo_backup', 'actualizado_en'])
    return JsonResponse({
        'status': 'ok',
        'ultimo_backup_rel': _tiempo_relativo(config.ultimo_backup),
        'ultimo_backup_abs': timezone.localtime(config.ultimo_backup).strftime('%d/%m/%Y %H:%M'),
        'message': 'Backup ejecutado correctamente.',
    })


@login_required
@require_POST
def crear_admin_ajax(request):
    """Crea un nuevo administrador. Solo administradores."""
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)

    form = NuevoAdminForm(request.POST)
    if form.is_valid():
        nuevo = form.save()
        return JsonResponse({
            'status': 'ok',
            'message': f'Administrador «{nuevo.username}» creado correctamente.',
            'admin': _serializar_admin_estado(nuevo, usuario_actual=request.user),
        })
    # Devolver el primer error legible
    errores = []
    for campo, errs in form.errors.items():
        for e in errs:
            errores.append(e)
    return JsonResponse({'status': 'error', 'message': errores[0] if errores else 'Datos inválidos.'}, status=400)


@login_required
@require_POST
def promover_ciudadano_ajax(request):
    """
    Cambia el rol de un ciudadano a ADMINISTRADOR por su username o email.
    Solo administradores. Esto modifica el registro del usuario en la base de datos.
    """
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)

    identificador = (request.POST.get('identificador') or '').strip()
    if not identificador:
        return JsonResponse({'status': 'error', 'message': 'Indica el usuario o correo del ciudadano.'}, status=400)

    from django.db.models import Q
    objetivo = Usuario.objects.filter(
        Q(username__iexact=identificador) | Q(email__iexact=identificador)
    ).first()

    if objetivo is None:
        return JsonResponse({'status': 'error', 'message': 'No se encontró un usuario con ese dato.'}, status=404)

    if _es_administrador(objetivo):
        return JsonResponse({'status': 'error', 'message': 'Ese usuario ya es administrador.'}, status=400)

    objetivo.rol = Usuario.Rol.ADMINISTRADOR
    objetivo.is_staff = True
    objetivo.save(update_fields=['rol', 'is_staff'])

    return JsonResponse({
        'status': 'ok',
        'message': f'«{objetivo.username}» ahora es administrador.',
        'admin': _serializar_admin_estado(objetivo, usuario_actual=request.user),
    })


@login_required
@require_POST
def revocar_admin_ajax(request, user_id):
    """
    Revoca el rol de administrador (lo vuelve ciudadano). Solo administradores.
    Protecciones: no puedes revocarte a ti mismo ni revocar a un superusuario.
    """
    if not _es_administrador(request.user):
        return JsonResponse({'status': 'error', 'message': 'No autorizado.'}, status=403)

    from django.shortcuts import get_object_or_404
    objetivo = get_object_or_404(Usuario, id=user_id)

    if objetivo == request.user:
        return JsonResponse({'status': 'error', 'message': 'No puedes revocar tu propio acceso.'}, status=400)
    if objetivo.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'No se puede revocar a un superusuario.'}, status=400)

    objetivo.rol = Usuario.Rol.CIUDADANO
    objetivo.is_staff = False
    objetivo.save(update_fields=['rol', 'is_staff'])
    return JsonResponse({
        'status': 'ok',
        'message': f'«{objetivo.username}» ya no es administrador.',
        'user_id': objetivo.id,
    })


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
    from feed.models import Publicacion, ReaccionPublicacion, ReaccionComentario, Reposteo

    if username:
        usuario = get_object_or_404(Usuario, username=username)
    else:
        usuario = request.user

    es_propio_perfil = (usuario == request.user)
    ya_lo_sigo = False if es_propio_perfil else request.user.sigue_a(usuario)

    # Pestaña activa: 'publicaciones' (por defecto) o 'reposteos'
    tab = request.GET.get('tab', 'publicaciones').lower()
    if tab not in ('publicaciones', 'reposteos'):
        tab = 'publicaciones'

    _prefetch = ('comentarios__respuestas__autor', 'comentarios__autor', 'reposteos')

    # Publicaciones propias del usuario del perfil
    publicaciones_propias = list(
        Publicacion.objects.filter(autor=usuario).order_by('-id').select_related('autor').prefetch_related(*_prefetch)
    )
    total_publicaciones = len(publicaciones_propias)

    # Reposteos del usuario del perfil (publicaciones que él reposteó), en orden de reposteo
    reposteos_qs = Reposteo.objects.filter(usuario=usuario).order_by('-fecha_creacion')
    total_reposteos = reposteos_qs.count()
    publicaciones_reposteadas = []
    if tab == 'reposteos' and total_reposteos > 0:
        reposteos_list = list(reposteos_qs)
        ids = [rp.publicacion_id for rp in reposteos_list]
        cache = {
            p.id: p
            for p in Publicacion.objects.filter(id__in=ids)
            .select_related('autor')
            .prefetch_related(*_prefetch)
        }
        for rp in reposteos_list:
            p = cache.get(rp.publicacion_id)
            if p:
                p.reposteado_por_perfil = True  # marca para mostrar la etiqueta "Reposteó"
                publicaciones_reposteadas.append(p)

    # Lista que se mostrará según la pestaña
    publicaciones = publicaciones_reposteadas if tab == 'reposteos' else publicaciones_propias

    from feed.views import _anotar_interacciones_usuario
    _anotar_interacciones_usuario(publicaciones, request.user)

    # Estadísticas reales (siempre sobre las publicaciones propias, no la pestaña activa)
    total_resueltas = sum(
        1 for p in publicaciones_propias
        if p.estado_incidencia == Publicacion.EstadoIncidencia.RESUELTA
    )

    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip() or usuario.username

    confianza = usuario.nivel_confianza(total=total_publicaciones, resueltos=total_resueltas)

    context = {
        'perfil_usuario': usuario,
        'mostrar_presencia_perfil': usuario.puede_ver_mi_presencia(request.user),
        'nombre_completo': nombre_completo,
        'confianza': confianza,
        'publicaciones': publicaciones,
        'tab_activa': tab,
        'total_publicaciones': total_publicaciones,
        'total_reposteos': total_reposteos,
        'total_resueltas': total_resueltas,
        'total_seguidores': usuario.total_seguidores,
        'total_seguidos': usuario.total_seguidos,
        'es_propio_perfil': es_propio_perfil,
        'ya_lo_sigo': ya_lo_sigo,
        # NOTA: no se pone 'es_admin' aquí. Ese valor lo provee el context
        # processor usuarios.context_processors.es_admin y SIEMPRE debe reflejar
        # al usuario autenticado (request.user), no al dueño del perfil visitado.
        # Antes se sobrescribía con el rol del perfil, lo que hacía que el
        # sidebar de un ciudadano se volviera el de admin al ver el perfil de uno.
        'perfil_es_admin': usuario.rol == Usuario.Rol.ADMINISTRADOR or usuario.is_staff or usuario.is_superuser,
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
        # Notificar al usuario que ha ganado un nuevo seguidor
        from feed.views import crear_notificacion
        from feed.models import Notificacion
        crear_notificacion(
            destinatario=objetivo, actor=request.user,
            tipo=Notificacion.Tipo.SEGUIDOR,
        )

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


def _serializar_usuario_relacion(u, viewer, seguidos_ids=None):
    """Datos mínimos de un usuario para las listas de seguidores/seguidos."""
    from django.urls import reverse
    nombre = f"{u.first_name} {u.last_name}".strip() or u.username
    lo_sigo = (u.id in seguidos_ids) if seguidos_ids is not None else viewer.sigue_a(u)
    return {
        'username': u.username,
        'nombre': nombre,
        'iniciales': (nombre[:2].upper() or 'UR'),
        'avatar_url': u.avatar.url if u.avatar else None,
        'rol': u.get_rol_display(),
        'perfil_url': reverse('perfil_usuario', args=[u.username]),
        'seguir_url': reverse('toggle_seguir', args=[u.username]),
        'lo_sigo': lo_sigo,
        'es_yo': (u.id == viewer.id),
    }


@login_required
def lista_seguidores_ajax(request, username):
    """Devuelve la lista de usuarios que siguen a <username> (estilo Instagram)."""
    from django.shortcuts import get_object_or_404
    from .models import Seguimiento
    usuario = get_object_or_404(Usuario, username=username)
    seguidores = list(usuario.seguidores.all().order_by('username'))
    seguidos_ids = set(
        Seguimiento.objects.filter(seguidor=request.user, seguido__in=seguidores)
        .values_list('seguido_id', flat=True)
    ) if seguidores else set()
    data = [_serializar_usuario_relacion(u, request.user, seguidos_ids) for u in seguidores]
    return JsonResponse({'status': 'ok', 'titulo': 'Seguidores', 'usuarios': data})


@login_required
def lista_seguidos_ajax(request, username):
    """Devuelve la lista de usuarios que <username> sigue (estilo Instagram)."""
    from django.shortcuts import get_object_or_404
    from .models import Seguimiento
    usuario = get_object_or_404(Usuario, username=username)
    seguidos = list(usuario.seguidos.all().order_by('username'))
    seguidos_ids = set(
        Seguimiento.objects.filter(seguidor=request.user, seguido__in=seguidos)
        .values_list('seguido_id', flat=True)
    ) if seguidos else set()
    data = [_serializar_usuario_relacion(u, request.user, seguidos_ids) for u in seguidos]
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
    # Validador de nombres obscenos/indebidos (reutilizado del formulario)
    from .forms import validar_nombre_perfil
    from django.core.exceptions import ValidationError

    usuario = request.user

    nombre = request.POST.get('nombre', '').strip()
    ubicacion = request.POST.get('ubicacion', '').strip()
    avatar = request.FILES.get('avatar')
    eliminar_avatar = request.POST.get('eliminar_avatar', '').strip().lower() in ('1', 'true', 'si', 'sí')

    # Nombre: se guarda en first_name (y limpiamos last_name para evitar duplicidad)
    if nombre:
        # Rechaza lenguaje obsceno/indebido o suplantación de cuentas de sistema.
        try:
            nombre = validar_nombre_perfil(nombre)
        except ValidationError as e:
            return JsonResponse({'status': 'error', 'message': e.messages[0]}, status=400)
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
