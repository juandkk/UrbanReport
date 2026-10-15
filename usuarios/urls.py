from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    # DIAGNÓSTICO TEMPORAL de envío de correo (solo superusers). Eliminar luego.
    path('diag-email/', views._diagnostico_email, name='diag_email'),
    path('completar-perfil/', views.completar_perfil_view, name='completar_perfil'),
    path('perfil/', views.perfil_view, name='perfil'),
    path('perfil/<str:username>/', views.perfil_view, name='perfil_usuario'),
    path('perfil/<str:username>/seguir/', views.toggle_seguir_ajax, name='toggle_seguir'),
    path('perfil/<str:username>/seguidores/', views.lista_seguidores_ajax, name='lista_seguidores'),
    path('perfil/<str:username>/seguidos/', views.lista_seguidos_ajax, name='lista_seguidos'),
    path('perfil-editar/', views.editar_perfil_ajax, name='editar_perfil'),
    path('registro/', views.registro_view, name='registro'),
    path('logout/', views.logout_view, name='logout'),

    # ── Recuperación de contraseña (sistema nativo de Django) ──
    # 1. Pedir el correo
    path('recuperar-contrasena/', auth_views.PasswordResetView.as_view(
        template_name='usuarios/password_reset_form.html',
        email_template_name='usuarios/password_reset_email.txt',
        subject_template_name='usuarios/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='recuperar_contrasena'),
    # 2. "Correo enviado"
    path('recuperar-contrasena/enviado/', auth_views.PasswordResetDoneView.as_view(
        template_name='usuarios/password_reset_done.html',
    ), name='password_reset_done'),
    # 3. Enlace del correo -> poner nueva contraseña
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='usuarios/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    # 4. "Contraseña cambiada"
    path('reset/completado/', auth_views.PasswordResetCompleteView.as_view(
        template_name='usuarios/password_reset_complete.html',
    ), name='password_reset_complete'),
]
