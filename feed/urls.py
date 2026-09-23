from django.urls import path
from . import views

urlpatterns = [
    path('', views.feed_comunitario_view, name='feed_comunitario'),
    path('like/<int:publicacion_id>/', views.dar_like_ajax, name='dar_like_ajax'),
    path('comentar/<int:publicacion_id>/', views.agregar_comentario_ajax, name='agregar_comentario_ajax'),
]
