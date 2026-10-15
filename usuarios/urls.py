from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('completar-perfil/', views.completar_perfil_view, name='completar_perfil'),
    path('perfil/', views.perfil_view, name='perfil'),
    path('perfil/configuracion/', views.configuracion_view, name='configuracion'),
    path('perfil/<str:username>/', views.perfil_view, name='perfil_usuario'),
    path('perfil/<str:username>/seguir/', views.toggle_seguir_ajax, name='toggle_seguir'),
    path('perfil/<str:username>/seguidores/', views.lista_seguidores_ajax, name='lista_seguidores'),
    path('perfil/<str:username>/seguidos/', views.lista_seguidos_ajax, name='lista_seguidos'),
    path('perfil-editar/', views.editar_perfil_ajax, name='editar_perfil'),
    path('registro/', views.registro_view, name='registro'),
    path('recuperar-contrasena/', views.recuperar_contrasena_view, name='recuperar_contrasena'),
    path('logout/', views.logout_view, name='logout'),
]
