from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from .models import Usuario
from .forms import LoginForm, RegistroForm, RecuperarContrasenaForm


def login_view(request):
    if request.user.is_authenticated:
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
