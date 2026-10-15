import os

from django.db import migrations


def configurar_site(apps, schema_editor):
    """
    Actualiza el Site por defecto de Django (que viene como 'example.com') al
    dominio real del proyecto, para que allauth muestre el nombre correcto en
    las pantallas de login social. Toma el dominio de RENDER_EXTERNAL_HOSTNAME
    si está disponible; si no, usa el de Render conocido.
    """
    Site = apps.get_model('sites', 'Site')
    dominio = os.getenv('RENDER_EXTERNAL_HOSTNAME') or 'urbanreport.onrender.com'
    Site.objects.update_or_create(
        id=1,
        defaults={'domain': dominio, 'name': 'UrbanReport'},
    )


def revertir_site(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    Site.objects.filter(id=1).update(domain='example.com', name='example.com')


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0003_seguimiento_usuario_seguidos_and_more'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(configurar_site, revertir_site),
    ]
