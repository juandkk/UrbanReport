from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0004_configurar_site'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='notif_feed',
            field=models.BooleanField(default=True, verbose_name='Notificaciones del feed'),
        ),
        migrations.AddField(
            model_name='usuario',
            name='notif_reportes',
            field=models.BooleanField(default=True, verbose_name='Notificaciones de reportes'),
        ),
    ]
