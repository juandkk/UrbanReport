import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.timesince import timesince

register = template.Library()

_MENCION_RE = re.compile(r'(?<![\w@])@([A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*)')


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


@register.filter(name='renderizar_menciones')
def renderizar_menciones(value):
    """
    Escapa el texto de forma segura y convierte menciones @username en enlaces
    clicables hacia el perfil de ese usuario (/perfil/<username>/).
    No convierte direcciones de correo (p. ej. usuario@correo.com).
    """
    if not value:
        return ""
    escaped = escape(str(value))

    def _reemplazar(match):
        uname = match.group(1)
        return (
            f'<a href="/perfil/{uname}/" class="user-mention" '
            f'onclick="event.stopPropagation();" title="Ver perfil de @{uname}">@{uname}</a>'
        )

    return mark_safe(_MENCION_RE.sub(_reemplazar, escaped))
