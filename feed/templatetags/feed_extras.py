from django import template
from django.utils.timesince import timesince

register = template.Library()

@register.filter(name='timesince_spaced')
def timesince_spaced(value):
    """
    Filtro de plantilla que aplica timesince asegurando que siempre
    exista un espacio tras cualquier coma (ej. '2 horas, 38 minutos').
    """
    if not value:
        return ""
    try:
        t = timesince(value)
        return t.replace(', ', ',').replace(',', ', ')
    except Exception:
        return str(value)
