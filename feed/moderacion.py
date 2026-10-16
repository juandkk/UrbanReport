"""
Moderación de lenguaje inapropiado para UrbanReport.

Módulo central y reutilizable que detecta groserías, insultos y expresiones
ofensivas en publicaciones y comentarios del feed comunitario, ANTES de guardar
el contenido en la base de datos.

Combina dos fuentes de detección:
  1. `better-profanity`: biblioteca base (principalmente inglés).
  2. Un diccionario propio en español (`PALABRAS_ES`), pensado para la comunidad
     colombiana. Es la fuente principal para nuestro contexto y es fácil de ampliar:
     basta con agregar términos al conjunto `PALABRAS_ES`.

Estrategia de detección (robusta frente a evasiones comunes):
  - Normaliza el texto: minúsculas, sin tildes y revirtiendo "leet speak"
    (p. ej. "p3nd3j0" -> "pendejo").
  - Coincidencia por palabra completa (token), para evitar falsos positivos con
    palabras que contienen accidentalmente una subcadena prohibida
    (p. ej. "Vergara" NO debe marcar por contener "verga").
  - Coincidencia por subcadena SOLO para una lista acotada de términos
    inequívocos (atrapa evasiones tipo "h-i-j-u-e-p-u-t-a").
  - Detección de "letras sueltas" ("p u t a") que no ocurre en texto legítimo.

Limitación conocida y asumida: ningún filtro automático detecta todas las
variantes ni todos los contextos. Esta capa cubre los casos frecuentes y es
fácilmente ampliable; se complementa con la moderación/denuncia comunitaria y
administrativa que ya existe en el proyecto.
"""
import re
import unicodedata

from better_profanity import profanity


# ── Diccionario configurable de español (ampliar aquí) ──────────────────────
# Agrega o quita términos de este conjunto para mantener el filtro al día.
# Se comparan sobre el texto NORMALIZADO (minúsculas, sin tildes, anti-leet).
PALABRAS_ES = {
    # Insultos / groserías generales
    'puta', 'puto', 'putas', 'putos', 'putita', 'putito', 'puton', 'putear',
    'perra', 'hp', 'hpta', 'hijueputa', 'hijueputas', 'hijuputa', 'ijueputa',
    'hijuepucha', 'hijodeputa', 'hijadeputa', 'hijo de puta', 'hija de puta',
    'hijo de perra', 'joputa', 'jueputa', 'gonorrea', 'gonorriento',
    'gonorrienta', 'malparido', 'malparida', 'malparidos', 'malnacido',
    'malnacida', 'marica', 'maricas', 'maricon', 'maricona', 'maricones',
    'mariconazo', 'verga', 'vergas', 'vergazo', 'vergota', 'careverga',
    'pendejo', 'pendeja', 'pendejos', 'pendejas', 'pendejada', 'imbecil',
    'imbeciles', 'idiota', 'idiotas', 'estupido', 'estupida', 'estupidos',
    'tarado', 'tarada', 'retrasado', 'mongolico', 'subnormal', 'baboso',
    'cabron', 'cabrona', 'cabrones', 'coño', 'cono', 'mierda', 'mierdas',
    'mrd', 'mierdero', 'carajo', 'carajos', 'culero', 'culera', 'culiao',
    'culiado', 'culicagado', 'zorra', 'zorras', 'ramera', 'rameras',
    'puta madre', 'putamadre', 'prostituta', 'prostitutas', 'prepago',
    'pirobo', 'piroba', 'pirobos', 'pirobas', 'gamin', 'guevon', 'gueon',
    'huevon', 'huevones', 'guevonazo', 'mamaguevo', 'mamahuevo', 'mamawebo',
    'mamona', 'mamon', 'chupapollas', 'chupaverga', 'chimba', 'chucha',
    'chimbo', 'cagada', 'cagon', 'careverga', 'carepicha', 'carechimba',
    'maldito', 'maldita', 'malditos', 'desgraciado', 'desgraciada',
    # Sexual / anatomía usada de forma ofensiva
    'pene', 'penes', 'pipi', 'pipis', 'picha', 'pichula', 'polla', 'pollas',
    'pija', 'pito', 'vagina', 'vaginas', 'cuca', 'crica', 'panocha', 'concha',
    'conchatumadre', 'ctm', 'teta', 'tetas', 'tetona', 'culo', 'culos',
    'nalga', 'nalgas', 'ano', 'orto', 'porno', 'pornografia', 'orgia',
    'follar', 'masturba', 'masturbacion', 'semen', 'esperma', 'violador',
    'violacion', 'pedofilo', 'pederasta', 'zoofilia',
    # Términos de orientación/identidad usados como insulto
    'gay', 'gays', 'lesbiana', 'lesbianas', 'lesbico', 'lesbica', 'tortillera',
    'marimacha', 'travesti', 'joto', 'volteado', 'camionera',
}

# Términos INEQUÍVOCOS: aquí sí buscamos por subcadena (texto compactado), porque
# no aparecen dentro de palabras legítimas. Atrapa evasiones con separadores.
_INEQUIVOCAS = {
    'hijueputa', 'hijuputa', 'hijodeputa', 'hijadeputa', 'malparido',
    'malparida', 'malnacido', 'gonorrea', 'gonorriento', 'maricon',
    'mariconazo', 'mamaguevo', 'mamahuevo', 'mamawebo', 'hijuepucha',
    'chupapollas', 'chupaverga', 'conchatumadre', 'prostituta', 'pirobo',
    'piroba', 'cabron', 'desgraciado', 'pendejo', 'pendeja', 'gonorreo',
}

# Sustituciones "leet" habituales para evadir filtros (3->e, 0->o, etc.)
_LEET = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a',
    '$': 's', '!': 'i',
})

# Mensaje único y respetuoso mostrado al usuario cuando el contenido es rechazado.
MENSAJE_RECHAZO = (
    'Tu mensaje contiene palabras o expresiones inapropiadas. '
    'Modifícalo e inténtalo nuevamente.'
)

# Inicializar better-profanity una sola vez al importar el módulo.
# Se cargan sus términos por defecto (inglés) y se añaden los de español, de modo
# que `profanity.contains_profanity` también cubra nuestro diccionario.
profanity.load_censor_words()
profanity.add_censor_words(list(PALABRAS_ES))


def _normalizar(texto):
    """
    Normaliza el texto para la comparación:
      - minúsculas
      - sin tildes/diacríticos
      - sustituciones leet (3->e, 0->o, ...)
    """
    t = (texto or '').lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = t.translate(_LEET)
    return t


def contiene_lenguaje_inapropiado(texto):
    """
    Devuelve True si `texto` contiene lenguaje inapropiado según el diccionario
    español, los términos inequívocos (subcadena) o better-profanity.

    No lanza excepciones: es una función booleana pura, segura de usar en
    cualquier vista.
    """
    if not texto or not texto.strip():
        return False

    norm = _normalizar(texto)

    # 1. Coincidencia por palabra completa (token). Evita falsos positivos:
    #    "Vergara" no coincide con "verga" porque son tokens distintos.
    tokens = set(re.split(r'[^a-z]+', norm))
    for prohibida in PALABRAS_ES:
        if ' ' not in prohibida and prohibida in tokens:
            return True
        # Frases con espacio: buscar como subcadena en el texto normalizado.
        if ' ' in prohibida and prohibida in norm:
            return True

    # 2. Subcadena sobre texto compactado, SOLO términos inequívocos.
    compacto = re.sub(r'[^a-z]', '', norm)
    for clave in _INEQUIVOCAS:
        if len(clave) >= 4 and clave in compacto:
            return True

    # 3. Evasión por "letras sueltas" ("p u t a", "g.a.y"): no ocurre en texto
    #    legítimo, así que compactamos esos tramos y comparamos con TODO el
    #    diccionario (incluidos términos cortos).
    tramos_sueltos = re.findall(r'(?:\b[a-z]\W+){2,}[a-z]\b', norm)
    for tramo in tramos_sueltos:
        compacto_tramo = re.sub(r'[^a-z]', '', tramo)
        for prohibida in PALABRAS_ES:
            clave = prohibida.replace(' ', '')
            if len(clave) >= 3 and clave in compacto_tramo:
                return True

    # 4. Respaldo: better-profanity (cubre inglés y nuestros términos añadidos).
    try:
        if profanity.contains_profanity(norm):
            return True
    except Exception:
        # Si la biblioteca fallara por cualquier motivo, no bloqueamos de más:
        # ya aplicamos nuestro diccionario arriba.
        pass

    return False


def validar_texto_limpio(*textos):
    """
    Recibe uno o más textos y devuelve True solo si NINGUNO contiene lenguaje
    inapropiado. Pensado para validar varios campos a la vez (p. ej. título y
    contenido de una publicación).
    """
    return not any(contiene_lenguaje_inapropiado(t) for t in textos)
