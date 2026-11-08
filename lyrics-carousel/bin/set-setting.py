#!/usr/bin/env python3
"""Escribe ajustes del plugin en el settings.toml de Noctalia.

Uso:  set-setting.py <clave> <valor> [tipo] [<clave> <valor> [tipo] ...]
       set-setting.py override <clave> <valor> <tipo>
       set-setting.py persist <clave> <valor> <tipo>
       set-setting.py merge

Tipos: bool | int | float | string

Mantiene el formato del fichero (secciones entrecomilladas, claves ordenadas
como las deja Noctalia) y escribe de forma atómica para no corromper la
configuración.

"override" deja el valor solo en la capa temporal (overrides.json), que el
panel vuelca al cerrarse. "persist" lo escribe además en el settings.toml:
es lo que necesitan los atajos de la ventana, que no tienen panel que
vuelque nada.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import tempfile

try:
    import tomllib
except ImportError:  # pragma: no cover - python < 3.11
    tomllib = None

# Las rutas del estado las comparte el script: si el helper buscara el
# settings.toml en un sitio y el script en otro, uno escribiria donde el
# otro lee.
from paths import overrides_path, settings_path

PLUGIN_ID = "faminec/lyrics-carousel"
SECTION = f'[plugin_settings."{PLUGIN_ID}"]'

ALLOWED = {
    "font_family", "font_size", "direction", "marker",
    "karaoke", "footer", "hints", "header", "spacing",
    "ghost", "offset_ms", "width", "height", "anchor",
    "custom_x", "custom_y", "accent", "custom_color", "active_scale",
    "visible_above", "visible_below", "glyph",
}

BOOL_KEYS = {
    "marker", "karaoke", "footer", "hints", "header", "ghost",
}
INT_KEYS = {
    "font_size", "spacing", "offset_ms", "width", "height",
    "custom_x", "custom_y", "visible_above", "visible_below",
}
FLOAT_KEYS = {"active_scale"}

# Los mismos patrones que lib/settings.luau (PATTERNS). El panel y el IPC
# del widget ya los aplican; el helper es otra via de escritura y sin esto
# podria guardar un glifo inexistente o un color invalido.
PATTERNS = {
    "glyph": r"^[a-z0-9-]+$",
    "custom_color": r"^#[0-9a-fA-F]{6}$",
    # Mismo patron que en lib/settings.luau: la fuente no puede estar
    # vacia ni llevar saltos de linea (se pasa al comando de kitty).
    "font_family": r"^[^\n]+$",
}

# Los limites (min/max) no se copian aqui: se leen del manifiesto, que es
# la fuente de verdad. Si se codificaran, un cambio en plugin.toml
# dejaria al plugin escribiendo valores que su propia pagina de ajustes
# no permite.
_MANIFEST_LIMITS = None


def manifest_limits() -> dict:
    """Rangos (min, max) que declara el manifiesto del plugin.

    Sin tomllib (Python < 3.11) el manifiesto se lee con una expresion
    regular: si no, el recorte desapareceria en silencio y el helper
    escribiria valores que la pagina de ajustes no permite.
    """
    global _MANIFEST_LIMITS
    if _MANIFEST_LIMITS is not None:
        return _MANIFEST_LIMITS
    manifest = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin.toml"
    )
    limits = {}
    if tomllib is not None:
        try:
            with open(manifest, "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        for field in data.get("setting", []):
            key = field.get("key")
            if not key:
                continue
            low = field.get("min")
            high = field.get("max")
            if low is None and high is None:
                continue
            limits[key] = (low, high)
    else:
        limits = manifest_limits_sin_tomllib(manifest)
    _MANIFEST_LIMITS = limits
    return limits


def _numero_toml(texto: str):
    """Convierte un numero TOML (con +, exponente o _) a int/float."""
    valor = float(texto.replace("_", ""))
    return int(valor) if valor.is_integer() else valor


def manifest_limits_sin_tomllib(manifest: str) -> dict:
    """Lee min/max del manifiesto con una expresion regular.

    Solo se usa cuando no hay tomllib. El formato del manifiesto es
    sencillo (bloques [[setting]] con key/min/max), pero el fallback no
    puede suponer que sea el unico formato valido: acepta comillas simples
    y numeros con signo +, exponente o separadores, y cierra el ajuste en
    cualquier cabecera de tabla (un min/max de [[panel]] no pertenece al
    ultimo ajuste).
    """
    limits = {}
    try:
        with open(manifest, encoding="utf-8") as handle:
            texto = handle.read()
    except OSError:
        return limits

    def anadir(clave, minimo, maximo):
        if clave is not None and (minimo is not None or maximo is not None):
            limits[clave] = (minimo, maximo)

    numero = r"[-+]?(?:\d[\d_]*(?:\.\d[\d_]*)?|\.\d[\d_]*)(?:[eE][-+]?\d[\d_]*)?"
    clave = None
    minimo = None
    maximo = None
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        if re.match(r"^\[\[.*\]\]\s*(?:#.*)?$", limpia) or re.match(
            r"^\[[^\[].*\]\s*(?:#.*)?$", limpia
        ):
            anadir(clave, minimo, maximo)
            clave, minimo, maximo = None, None, None
            continue
        encontrado = re.match(r"""^key\s*=\s*(?:"([^"]+)"|'([^']+)')""", limpia)
        if encontrado:
            clave = encontrado.group(1) or encontrado.group(2)
            continue
        encontrado = re.match(rf"^min\s*=\s*({numero})", limpia)
        if encontrado:
            minimo = _numero_toml(encontrado.group(1))
            continue
        encontrado = re.match(rf"^max\s*=\s*({numero})", limpia)
        if encontrado:
            maximo = _numero_toml(encontrado.group(1))
    anadir(clave, minimo, maximo)
    return limits


def clamp_value(key: str, value):
    """Recorta un valor numerico a los limites del manifiesto."""
    bounds = manifest_limits().get(key)
    if bounds is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    low, high = bounds
    if low is not None and value < low:
        return low
    if high is not None and value > high:
        return high
    return value


def prepare(key: str, value, kind: str):
    """Convierte el valor a su tipo, lo recorta y valida su formato."""
    preparado = clamp_value(key, parse_value(value, kind))
    patron = PATTERNS.get(key)
    if patron is not None and (
        not isinstance(preparado, str) or re.fullmatch(patron, preparado) is None
    ):
        raise ValueError(f"formato no válido para {key}: {value!r}")
    return preparado


def format_value(value: str, kind: str) -> str:
    if kind == "bool":
        return "true" if str(value).lower() in ("1", "true", "yes", "on") else "false"
    if kind == "int":
        return str(int(float(value)))
    if kind == "float":
        return str(float(value))
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def patch(text: str, key: str, raw_value: str) -> str:
    """Inserta o reemplaza una clave dentro de la sección del plugin."""
    lines = text.split("\n")
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == SECTION:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    if start is None:
        block = [SECTION, f"{key} = {raw_value}"]
        prefix = text if text.endswith("\n") else text + "\n"
        if not prefix.strip():
            return "\n".join(block) + "\n"
        return prefix + "\n".join(block) + "\n"

    body = lines[start + 1 : end]
    # El TOML no admite claves duplicadas: si las hay, todo el fichero
    # queda invalido y Noctalia descarta la seccion entera. Se deja solo la
    # primera aparicion de cada clave.
    seen = set()
    clean = []
    for line in body:
        name = line.split("=", 1)[0].strip()
        if name and not name.startswith("["):
            if name in seen:
                continue
            seen.add(name)
        clean.append(line)
    body = clean
    replaced = False
    for index, line in enumerate(body):
        if line.strip().startswith(key + " "):
            if not replaced:
                body[index] = f"{key} = {raw_value}"
                replaced = True
            else:
                # Clave duplicada: el TOML ser\u00eda inv\u00e1lido y Noctalia
                # descartaria toda la secci\u00f3n. Se elimina el duplicado.
                body[index] = None
    body = [line for line in body if line is not None]
    if not replaced:
        insert_at = len(body)
        while insert_at > 0 and body[insert_at - 1].strip() == "":
            insert_at -= 1
        for index in range(insert_at):
            name = body[index].split("=", 1)[0].strip()
            if name and name > key:
                insert_at = index
                break
        body.insert(insert_at, f"{key} = {raw_value}")
    return "\n".join(lines[: start + 1] + body + lines[end:])


def parse_args(argv):
    pairs = []
    index = 0
    while index < len(argv):
        key = argv[index]
        if index + 1 >= len(argv):
            raise ValueError(f"falta el valor de {key}")
        value = argv[index + 1]
        kind = "string"
        if index + 2 < len(argv) and argv[index + 2] in ("bool", "int", "float", "string"):
            kind = argv[index + 2]
            index += 1
        pairs.append((key, value, kind))
        index += 2
    return pairs


def ensure_dir(path: str) -> bool:
    """Garantiza que el directorio exista.

    El directorio de datos del plugin lo crea Noctalia, pero puede no existir
    (si se borra a mano o si el plugin nunca ha guardado nada) y entonces ni
    el lock ni la escritura podrian crearse.
    """
    directory = os.path.dirname(path)
    if not directory:
        return True
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except OSError as error:
        print(f"no se pudo crear {directory}: {error}", file=sys.stderr)
        return False


def overrides_path_now() -> str:
    """Ruta actual del fichero de overrides (se lee cada vez)."""
    return overrides_path()


def read_overrides():
    try:
        with open(overrides_path_now(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_overrides(data) -> bool:
    path = overrides_path_now()
    if not ensure_dir(path):
        return False
    directory = os.path.dirname(path)
    try:
        temporary = ""
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        temporary = handle.name
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    except OSError as error:
        print(f"no se pudo escribir los overrides: {error}", file=sys.stderr)
        return False
    return True


def set_override(key: str, value: str, kind: str) -> int:
    """Guarda un ajuste en el fichero de overrides (no lo vigila Noctalia).

    Varias escrituras pueden solaparse (el panel escribe sin esperar), asi que
    la lectura-modificacion-escritura va con lock: si no, la segunda pisa a la
    primera.
    """
    path = overrides_path_now()
    lock_path = path + ".lock"
    if not ensure_dir(lock_path):
        return 1
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        print(f"no se pudo abrir el lock: {error}", file=sys.stderr)
        return 1
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_overrides()
        data[key] = prepare(key, value, kind)
        if not write_overrides(data):
            return 1
        return 0
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def remove_override(key: str, value) -> bool:
    """Quita una clave de los overrides si sigue teniendo ese valor.

    El valor se comprueba: si el panel ha cambiado esa clave mientras
    tanto, su cambio se respeta y no se toca (el panel vuelca lo suyo al
    cerrarse).
    """
    path = overrides_path_now()
    lock_path = path + ".lock"
    if not ensure_dir(lock_path):
        return False
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_overrides()
        if key not in data or data[key] != value:
            return False
        del data[key]
        return write_overrides(data)
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def parse_value(value: str, kind: str):
    if kind == "bool":
        return str(value).lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    return value


def merge_overrides() -> int:
    """Vuelca los overrides al settings.toml y borra el fichero."""
    data = read_overrides()
    if not data:
        return 0
    pairs = []
    for key, value in data.items():
        if key not in ALLOWED:
            continue
        if isinstance(value, bool):
            kind = "bool"
            raw = "true" if value else "false"
        elif isinstance(value, int):
            kind = "int"
            raw = str(value)
        elif isinstance(value, float):
            kind = "float"
            raw = str(value)
        else:
            kind = "string"
            raw = str(value)
        try:
            # Un override viejo con formato invalido (por ejemplo, un glifo
            # con guion bajo guardado antes de validar) no puede volcarse:
            # se descarta al cerrar el panel en vez de romper el volcado.
            prepare(key, raw, kind)
        except ValueError as error:
            print(f"se descarta {key}: {error}", file=sys.stderr)
            continue
        pairs.append((key, raw, kind))
    if not pairs:
        try:
            os.remove(overrides_path_now())
        except OSError:
            pass
        return 0
    code = write_settings(pairs)
    if code == 0:
        try:
            os.remove(overrides_path_now())
        except OSError:
            pass
    return code


def _valor_toml(texto: str):
    """Convierte un escalar TOML (true, 12, 1.5 o "texto") a su tipo."""
    texto = texto.strip()
    if texto == "true":
        return True
    if texto == "false":
        return False
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        return texto[1:-1]
    numero = re.match(
        r"^[-+]?(?:\d[\d_]*(?:\.\d[\d_]*)?|\.\d[\d_]*)(?:[eE][-+]?\d+)?$", texto
    )
    if numero is not None:
        return _numero_toml(numero.group(0))
    return texto


def read_settings() -> dict:
    """Ajustes guardados del plugin en el settings.toml (solo lectura).

    El manifiesto solo declara el icono de la barra: el resto de ajustes los
    gestiona el panel. Noctalia conserva las claves guardadas aunque no estén
    declaradas, pero `noctalia.getConfig` únicamente devuelve las que conoce,
    así que el panel necesita leer el fichero para ver el valor real. Es la
    misma fuente que usa el script: si el panel enseñara otra cosa, el
    usuario vería un valor que no se aplica.
    """
    try:
        with open(settings_path(), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return {}
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            return {}
        section = (data.get("plugin_settings") or {}).get(PLUGIN_ID) or {}
        return {key: section[key] for key in ALLOWED if key in section}
    return read_settings_sin_tomllib(text)


def read_settings_sin_tomllib(text: str) -> dict:
    """Lee la sección del plugin con una expresión regular (Python < 3.11).

    Solo se usa cuando no hay tomllib. El formato del fichero lo escribe
    Noctalia (una sección `[plugin_settings."faminec/lyrics-carousel"]` con
    claves escalares), pero el fallback se limita a lo que necesita el panel
    y descarta cualquier línea que no entienda.
    """
    values = {}
    dentro = False
    for linea in text.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        if limpia.startswith("["):
            dentro = limpia == SECTION
            continue
        if not dentro or "=" not in limpia:
            continue
        name, _, resto = limpia.partition("=")
        name = name.strip()
        if name not in ALLOWED:
            continue
        values[name] = _valor_toml(resto)
    return values


def persist_override(key: str, value: str, kind: str) -> int:
    """Guarda el ajuste y lo deja escrito en el settings.toml.

    La capa de overrides es temporal (la vuelca el panel al cerrarse). Un
    atajo de la ventana no tiene panel que la vuelque, asi que el valor se
    escribe tambien en el settings.toml: si no, se perderia al reiniciar
    la sesion.

    Primero se escribe en los overrides: si la escritura del settings.toml
    falla, el valor sigue en vigor durante la sesion y el panel lo vuelca
    al cerrarse. Si la escritura va bien, la clave se quita de los
    overrides para que no tape un cambio posterior hecho en la pagina de
    ajustes.
    """
    if set_override(key, value, kind) != 0:
        return 1
    code = write_settings([(key, value, kind)])
    if code != 0:
        return code
    remove_override(key, prepare(key, value, kind))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "override":
        if len(argv) < 5:
            print("uso: set-setting.py override <clave> <valor> <tipo>", file=sys.stderr)
            return 2
        if argv[2] not in ALLOWED:
            print(f"clave desconocida: {argv[2]}", file=sys.stderr)
            return 2
        try:
            return set_override(argv[2], argv[3], argv[4])
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
    if len(argv) >= 2 and argv[1] == "persist":
        if len(argv) < 5:
            print("uso: set-setting.py persist <clave> <valor> <tipo>", file=sys.stderr)
            return 2
        if argv[2] not in ALLOWED:
            print(f"clave desconocida: {argv[2]}", file=sys.stderr)
            return 2
        try:
            return persist_override(argv[2], argv[3], argv[4])
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
    if len(argv) >= 2 and argv[1] == "merge":
        return merge_overrides()
    if len(argv) >= 2 and argv[1] == "read":
        # Solo lectura: el panel la usa para ver el valor real de un ajuste
        # que el manifiesto ya no declara. No escribe nada.
        print(json.dumps(read_settings(), ensure_ascii=False, sort_keys=True))
        return 0
    if len(argv) < 3:
        print("uso: set-setting.py <clave> <valor> [tipo] ...", file=sys.stderr)
        return 2
    try:
        pairs = parse_args(argv[1:])
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    for key, _, _ in pairs:
        if key not in ALLOWED:
            print(f"clave desconocida: {key}", file=sys.stderr)
            return 2

    try:
        return write_settings(pairs)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2


def write_settings(pairs) -> int:
    """Escribe los ajustes en el settings.toml (con lock).

    El script y el panel pueden escribir a la vez: con un fichero de lock
    la lectura-modificacion-escritura se serializa y no se pisan.
    """
    settings = settings_path()
    lock_path = settings + ".lock"
    if not ensure_dir(lock_path):
        return 1
    try:
        lock = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        print(f"no se pudo abrir el lock: {error}", file=sys.stderr)
        return 1
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(settings, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            print(f"no se pudo leer: {error}", file=sys.stderr)
            return 1
        return _write(text, pairs)
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock)


def _write(text, pairs):
    updated = text
    for key, value, kind in pairs:
        updated = patch(updated, key, format_value(prepare(key, value, kind), kind))
    if updated == text:
        return 0

    settings = settings_path()
    if not ensure_dir(settings):
        return 1
    directory = os.path.dirname(settings)
    temporary = ""
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        temporary = handle.name
        with handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, settings)
        temporary = ""
    except OSError as error:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        print(f"no se pudo escribir: {error}", file=sys.stderr)
        return 1

    # Comprobación: el fichero debe seguir siendo un TOML válido y tener los
    # valores escritos. Si algo falla, se avisa con código de error.
    if tomllib is None:
        return 0
    try:
        with open(settings, "rb") as handle:
            check = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"el fichero quedó ilegible: {error}", file=sys.stderr)
        return 1
    section = (check.get("plugin_settings") or {}).get(PLUGIN_ID) or {}
    for key, value, _ in pairs:
        if key not in section:
            print(f"no se pudo guardar {key}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
