from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Seguimiento


@admin.register(Seguimiento)
class SeguimientoAdmin(admin.ModelAdmin):
    list_display = ('seguidor', 'seguido', 'fecha_creacion')
    search_fields = ('seguidor__username', 'seguido__username')


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Información Urbana', {
            'fields': ('rol', 'telefono', 'direccion', 'barrio_vereda', 'numero_finca', 'codigo_postal', 'avatar')
        }),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'rol', 'is_staff')
    list_filter = ('rol', 'is_staff', 'is_active')
