from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('completar-perfil/', views.completar_perfil_view, name='completar_perfil'),
    path('perfil/', views.perfil_view, name='perfil'),
    path('perfil/configuracion/', views.configuracion_view, name='configuracion'),
    path('perfil/eliminar-cuenta/', views.eliminar_cuenta_view, name='eliminar_cuenta'),
    # ── Configuración exclusiva del administrador ──
    path('perfil/configuracion-admin/', views.configuracion_admin_view, name='configuracion_admin'),
    path('admin-config/mantenimiento/', views.toggle_modo_mantenimiento_ajax, name='toggle_modo_mantenimiento'),
    path('admin-config/estado-admins/', views.estado_administradores_ajax, name='estado_administradores'),
    path('admin-config/backup/', views.ejecutar_backup_ajax, name='ejecutar_backup'),
    path('admin-config/nuevo-admin/', views.crear_admin_ajax, name='crear_admin'),
    path('admin-config/promover/', views.promover_ciudadano_ajax, name='promover_ciudadano'),
    path('admin-config/revocar/<int:user_id>/', views.revocar_admin_ajax, name='revocar_admin'),
    path('perfil/<str:username>/', views.perfil_view, name='perfil_usuario'),
    path('perfil/<str:username>/seguir/', views.toggle_seguir_ajax, name='toggle_seguir'),
    path('perfil/<str:username>/seguidores/', views.lista_seguidores_ajax, name='lista_seguidores'),
    path('perfil/<str:username>/seguidos/', views.lista_seguidos_ajax, name='lista_seguidos'),
    path('perfil-editar/', views.editar_perfil_ajax, name='editar_perfil'),
    path('registro/', views.registro_view, name='registro'),
    path('logout/', views.logout_view, name='logout'),

    # ── Recuperación de contraseña (deshabilitada temporalmente por seguridad) ──
    path('recuperar-contrasena/', views.recuperar_contrasena_view, name='recuperar_contrasena'),
    path('recuperar-contrasena/enviado/', views.recuperar_contrasena_view, name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.recuperar_contrasena_view, name='password_reset_confirm'),
    path('reset/completado/', views.recuperar_contrasena_view, name='password_reset_complete'),
]
