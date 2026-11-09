#!/usr/bin/env python3
"""Datos del API de Noctalia que necesitan los validadores estáticos.

Centraliza el conocimiento que antes estaba duplicado (o hardcodeado) en cada
script: la lista de iconos, las variantes de botón que acepta la UI, las
propiedades que despachan un manejador por nombre y los puntos de entrada que
llama Noctalia.

Todo se deduce de la instalación real cuando es posible, y de una lista
conservadora cuando no:

* Los iconos salen de la fuente Tabler que instala Noctalia.
* Las variantes de botón salen del código del core si está disponible; si no,
  se usa la unión de todas las que ha tenido el core (para no marcar como
  error algo que sí funciona).
* Los manejadores por nombre son los que el reconciliador despacha a la
  función global del script.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# --------------------------------------------------------------------- iconos

ICON_LISTS = (
    "/usr/share/noctalia/assets/fonts/tabler.json",
    "/usr/local/share/noctalia/assets/fonts/tabler.json",
    "~/.local/share/noctalia/assets/fonts/tabler.json",
)

_icon_cache: set[str] | None = None


def icon_list_path() -> str | None:
    for candidate in ICON_LISTS:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


def icon_names() -> set[str]:
    """Nombres de icono disponibles. Set vacío si no se encuentra la fuente."""
    global _icon_cache
    if _icon_cache is not None:
        return _icon_cache
    path = icon_list_path()
    names: set[str] = set()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                names = set(json.load(handle).keys())
        except (OSError, ValueError):
            names = set()
    _icon_cache = names
    return names


# --------------------------------------------------------- variantes de botón

# Unión de todas las variantes que ha aceptado el core. Si el código del core
# está a mano se usan las suyas, que son las exactas.
BUTTON_VARIANTS_FALLBACK = {
    "default",
    "primary",
    "secondary",
    "destructive",
    "outline",
    "ghost",
}

CORE_SOURCES = (
    "/tmp/opencode/noctalia-src/src/ui/ui_tree_reconciler.cpp",
    "~/noctalia-src/src/ui/ui_tree_reconciler.cpp",
    "~/src/noctalia/src/ui/ui_tree_reconciler.cpp",
)

_VARIANT_RE = re.compile(r'\*token\s*==\s*"([a-z]+)"')

_variant_cache: set[str] | None = None


def button_variants() -> set[str]:
    """Variantes que `ui.button({ variant = ... })` acepta."""
    global _variant_cache
    if _variant_cache is not None:
        return _variant_cache
    variants = set()
    for candidate in CORE_SOURCES:
        path = os.path.expanduser(candidate)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            continue
        # La función parseButtonVariant del core solo compara con literales.
        start = body.find("parseButtonVariant")
        if start == -1:
            continue
        chunk = body[start:start + 1200]
        found = set(_VARIANT_RE.findall(chunk))
        if found:
            variants = found
            break
    if not variants:
        variants = set(BUTTON_VARIANTS_FALLBACK)
    _variant_cache = variants
    return variants


# ------------------------------------------------- manejadores despachados

# Propiedades que el reconciliador convierte en una llamada a la función global
# del script con ese nombre. Si la función no es global, nunca se ejecuta.
CALLBACK_PROPS = {
    "onClick",
    "onRightClick",
    "onHover",
    "onChange",
    "onDragEnd",
    "onSubmit",
    "onScroll",
    "onDrop",
    "onPointerMove",
    "onPointerLeave",
}

# Puntos de entrada que llama Noctalia al script.
ENTRY_POINTS = {
    "onOpen",
    "onClose",
    "onConfigChanged",
    "onIpc",
    "onExit",
    "update",
}

# ------------------------------------------------------------------ ficheros

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}


def luau_files(root: Path) -> list[Path]:
    """Ficheros .luau de un directorio, sin directorios de ruido."""
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.endswith(".luau"):
                files.append(Path(current) / name)
    return sorted(files)


def plugin_dir_of(path: Path, root: Path) -> Path | None:
    """Directorio del plugin al que pertenece un fichero .luau.

    Un plugin es el primer componente de la ruta relativa a la raíz del repo.
    """
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 2:
        return None
    return root.resolve() / parts[0]


def plugin_dirs(root: Path) -> list[Path]:
    """Directorios con un plugin.toml, ordenados."""
    found = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "plugin.toml" in names:
            found.append(Path(current))
    return sorted(found)


# ------------------------------------------------------- análisis de Luau

# Una función global: `function f(...)` sin `local` delante.
GLOBAL_FUNCTION_RE = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# Una asignación a global: `f = ...` sin `local` delante.
GLOBAL_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]")
# Un local: `local function f(` o `local f =`.
LOCAL_FUNCTION_RE = re.compile(r"^\s*local\s+function\s+([A-Za-z_][A-Za-z0-9_]*)")
LOCAL_ASSIGN_RE = re.compile(r"^\s*local\s+([A-Za-z_][A-Za-z0-9_]*)\b")

# Bloques de comentario largos de Luau: --[[ ... ]] y --[=[ ... ]=]
LONG_COMMENT_RE = re.compile(r"--\[(=*)\[.*?\](=*)\]", re.S)


def strip_luau_comments(text: str) -> str:
    """Quita comentarios de línea y bloques largos, dejando los saltos de línea."""
    text = LONG_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = []
    for line in text.split("\n"):
        # Un -- dentro de una cadena no es un comentario: se Corta el análisis
        # de esa línea pero se conservan las comillas para no abrir un string
        # desbalanceado en las líneas siguientes.
        quote = None
        cut = len(line)
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == "-" and line[index : index + 2] == "--":
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return "\n".join(out)


def global_functions(text: str) -> set[str]:
    """Nombres definidos como función global en el fichero."""
    body = strip_luau_comments(text)
    names = set()
    for line in body.split("\n"):
        match = GLOBAL_FUNCTION_RE.match(line)
        if match:
            names.add(match.group(1))
            continue
        match = GLOBAL_ASSIGN_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


def local_names(text: str) -> set[str]:
    """Nombres declarados como local en el fichero."""
    body = strip_luau_comments(text)
    names = set()
    for line in body.split("\n"):
        match = LOCAL_FUNCTION_RE.match(line)
        if match:
            names.add(match.group(1))
            continue
        match = LOCAL_ASSIGN_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


def line_of(text: str, index: int) -> int:
    """Número de línea (1-based) de una posición del texto."""
    return text.count("\n", 0, index) + 1


# ------------------------------------------------------------- compilador Lua

# Compiladores de Lua/Luau que sirven para mirar el bytecode. El orden va de
# más a menos parecido a Luau.
COMPILERS = ("luac5.4", "luac", "luac5.3", "luac5.1", "luajit")

_compiler_cache: str | None = None


def luac() -> str:
    """Ruta al compilador disponible, o "" si no hay ninguno."""
    global _compiler_cache
    if _compiler_cache is not None:
        return _compiler_cache
    import shutil

    found = ""
    for name in COMPILERS:
        path = shutil.which(name)
        if path:
            found = path
            break
    _compiler_cache = found
    return found


def compile_ok(text: str) -> bool:
    """True si el texto compila sin errores de sintaxis."""
    import subprocess

    compiler = luac()
    if not compiler:
        return False
    try:
        result = subprocess.run(
            [compiler, "-p", "-"], input=text, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def bytecode(source: str) -> str | None:
    """Bytecode de un fichero, o None si no se puede compilar."""
    import subprocess
    import tempfile

    compiler = luac()
    if not compiler:
        return None
    handle = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".lua", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run(
            [compiler, "-l", "-p", path], capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if handle is not None:
            try:
                os.unlink(handle.name)
            except OSError:
                pass


def compile_error(text: str) -> str | None:
    """Mensaje del compilador si el código no compila; None si compila."""
    import subprocess

    compiler = luac()
    if not compiler:
        return None
    try:
        result = subprocess.run(
            [compiler, "-p", "-"], input=text, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return None
    message = (result.stderr or result.stdout or "").strip()
    return message.splitlines()[0] if message else "error de sintaxis"


def luau_bytecode(text: str) -> tuple[str | None, str | None]:
    """(bytecode, error_de_sintaxis) de un fichero Luau.

    El bytecode se saca del código normalizado (para quitarle lo que es solo
    de Luau). Si tampoco así compila, el fichero tiene un **error de sintaxis
    real** y se devuelve el mensaje del compilador: nunca se traga.

    El mensaje se pide del ORIGINAL, que es donde está el error de verdad.
    """
    if compile_ok(text):
        listing = bytecode(text)
        if listing is not None:
            return listing, None
        return None, "no se pudo generar el bytecode"

    normalized = normalize(text)
    if compile_ok(normalized):
        listing = bytecode(normalized)
        if listing is not None:
            return listing, None
        return None, "no se pudo generar el bytecode"

    # El mensaje se saca del codigo NORMALIZADO: si el original falla por una
    # anotacion de tipo, ese no es el problema de verdad. Tras quitarle lo
    # que es solo de Luau, si sigue sin compilar, el error es real.
    error = compile_error(normalized) or compile_error(text) or "error de sintaxis"
    return None, error


# --------------------------------------------------------------- normalizar

LUAU_ONLY = [
    # x += y  ->  x = x + y   (solo al principio de linea, indentado)
    (re.compile(r"^(\s*)([A-Za-z_][\w.\[\]'\"]*)\s*\+=\s*(.+)$"), r"\1\2 = \2 + \3"),
    (re.compile(r"^(\s*)([A-Za-z_][\w.\[\]'\"]*)\s*-=\s*(.+)$"), r"\1\2 = \2 - \3"),
    (re.compile(r"^(\s*)([A-Za-z_][\w.\[\]'\"]*)\s*\*=\s*(.+)$"), r"\1\2 = \2 * \3"),
    (re.compile(r"^(\s*)([A-Za-z_][\w.\[\]'\"]*)\s*/=\s*(.+)$"), r"\1\2 = \2 / \3"),
    # x ..= y -> x = x .. y
    (re.compile(r"^(\s*)([A-Za-z_][\w.\[\]'\"]*)\s*\.\.=\s*(.+)$"), r"\1\2 = \2 .. \3"),
    (re.compile(r"\bcontinue\b"), "do end --[[continue]]"),
]

# Un local puede declarar varios nombres: "local a, b = 1, 2"
LOCAL_MULTI_RE = re.compile(r"^\s*local\s+([A-Za-z_][\w,\s\[\]'\"-]*?)\s*(?:=[^=]|$)")
LOCAL_FUNCTION_RE = re.compile(r"^\s*local\s+function\s+([A-Za-z_]\w*)")

# Caracteres que pueden formar parte de un tipo de Luau.
TYPE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.?|<>& ")

# Palabras clave de Lua: cortan el escaneo de un tipo.
LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "for", "function", "if",
    "in", "local", "not", "or", "repeat", "return", "then", "until", "while",
}


def _word_at(text: str, i: int) -> str:
    """Palabra que termina en la posicion `i` (hacia atras)."""
    j = i
    while j >= 0 and (text[j].isalnum() or text[j] == "_"):
        j -= 1
    return text[j + 1 : i + 1]


def strip_type_annotations(text: str) -> str:
    """Quita las anotaciones de tipo de Luau sin romper el codigo.

    Una anotacion es `NOMBRE: TIPO`. El problema de distinguirlas de una clave
    de tabla (`{ foo: bar }`) se resuelve por el contexto:

    * dentro de `{ }` o `[ ]` no se toca nada: ahi `:` es una clave;
    * en una lista de parametros de una funcion si se quita: `function f(a: number)`;
    * a nivel de sentencia se quita solo si lo que sigue al tipo es `=`, `,`
      o el fin de la sentencia: `local x: number = 1`.

    Al quitarla se conserva el separador (`=`, `,`, `)`), que es lo que
    rompia el codigo antes: `local x: number = 1` se convertia en
    `local x 1`.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    depth = 0  # profundidad de llaves y corchetes (las llaves de tabla)
    paren_depth = 0  # profundidad de parentesis
    in_params = False  # dentro de la lista de parametros de una funcion
    params_depth = 0
    expect_params = False  # se ha visto "function": el "(" abre parametros
    last_word = ""
    in_word = False

    while index < length:
        char = text[index]

        # --- cadenas ---------------------------------------------------
        if char in "\"'":
            quote = char
            out.append(char)
            index += 1
            while index < length:
                out.append(text[index])
                if text[index] == "\\":
                    if index + 1 < length:
                        out.append(text[index + 1])
                        index += 2
                        continue
                elif text[index] == quote:
                    index += 1
                    break
                index += 1
            in_word = False
            continue

        # --- comentarios ------------------------------------------------
        if char == "-" and text[index : index + 2] == "--":
            end = text.find("\n", index)
            if end == -1:
                end = length
            out.append(text[index:end])
            index = end
            continue

        # --- posible anotacion de tipo ----------------------------------
        if char == ":" and text[index : index + 2] != "::":
            if depth == 0 or in_params:
                j = index + 1
                type_end = -1
                while j < length:
                    c = text[j]
                    if c == "{":
                        # Tipo compuesto: {string: number}
                        level = 0
                        while j < length:
                            if text[j] == "{":
                                level += 1
                            elif text[j] == "}":
                                level -= 1
                                if level == 0:
                                    j += 1
                                    break
                            j += 1
                        continue
                    if c in "\"'":
                        j = _skip_quote(text, j)
                        continue
                    if c in "=,)\n":
                        type_end = j
                        break
                    if c not in TYPE_CHARS:
                        break
                    j += 1
                    # Una palabra clave corta el tipo: el tipo de retorno de
                    # "function f(): number return x" no se come el "return".
                    if c.isalpha():
                        palabra = _word_at(text, j - 1)
                        if palabra in LUA_KEYWORDS:
                            type_end = j - 1 - len(palabra) + 1
                            break
                if type_end == -1 and j >= length:
                    # El tipo llega hasta el final del texto.
                    type_end = length
                if type_end != -1:
                    tipo = text[index + 1 : type_end].strip()
                    if tipo and _looks_like_type(tipo):
                        # Se quita ": TIPO" y se deja el separador intacto.
                        siguiente = text[type_end : type_end + 1]
                        out.append("" if siguiente in ",)" else " ")
                        index = type_end
                        in_word = False
                        continue
            out.append(char)
            index += 1
            in_word = False
            continue

        # --- resto ------------------------------------------------------
        out.append(char)
        index += 1
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth = max(0, depth - 1)
        elif char == "(":
            paren_depth += 1
            if expect_params:
                in_params = True
                params_depth = paren_depth
                expect_params = False
        elif char == ")":
            if in_params and paren_depth == params_depth:
                in_params = False
            paren_depth = max(0, paren_depth - 1)

        if char.isalnum() or char == "_":
            if not in_word:
                last_word = ""
                in_word = True
            last_word += char
            if last_word == "function":
                expect_params = True
        else:
            if not char.isspace():
                in_word = False
                if last_word == "function":
                    expect_params = True
                last_word = ""

    return "".join(out)


def _skip_quote(text: str, i: int) -> int:
    """Índice siguiente a la cadena que empieza en `text[i]`."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return i + 1


def _looks_like_type(tipo: str) -> bool:
    """True si el texto parece un tipo de Luau y no una expresión cualquiera."""
    if not tipo:
        return False
    if tipo in ("nil", "true", "false"):
        return False
    # Un tipo es un identificador (o varios unidos por | / &), conpunctos,
    # interrogantes y <>; puede acabar en [] (array) o {} (tabla).
    base = tipo.split("=")[0].strip()
    if not base:
        return False
    for parte in base.replace("|", " ").replace("&", " ").split():
        limpio = parte.rstrip("?").replace("[", "").replace("]", "")
        if not limpio:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", limpio):
            # Tipos compuestos: {string: number} -> se acepta si parece un tipo.
            if limpio.startswith("{") or limpio.endswith("}"):
                continue
            return False
    return True


def _skip_string(text: str, i: int) -> int:
    """Índice siguiente a la cadena que empieza en `text[i]` (comilla doble)."""
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == '"':
            return j + 1
        j += 1
    return i + 1


def _find_word(text: str, word: str, i: int, depth: int = 0) -> int:
    """Índice de `word` a partir de `i`, saltando cadenas y anidamiento."""
    while i < len(text):
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return -1
            depth -= 1
        elif depth == 0 and text.startswith(word, i):
            return i
        i += 1
    return -1


def _find_value_end(text: str, i: int) -> int:
    """Índice donde termina un valor de expresión.

    Termina en la primera coma o corchete de cierre que esté al nivel de
    anidamiento en el que se empezó (las cadenas se saltan enteras).
    """
    depth = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c == "," and depth == 0:
            return i
        i += 1
    return len(text)


def _split_if_expression(text: str):
    """Convierte 'if C then A else B' (expresion de Luau) a '(C) and (A) or (B)'.

    Solo se consideran los `if` que pueden ser expresion: los que estan al
    principio de una linea (sentencias) o despues de then/else/do/; se
    ignoran. Las cadenas se saltan para no confundirse con una palabra clave.
    """
    for m in re.finditer(r'(?<![\w.])if\s+', text):
        start = m.start()
        before = text[:start].rstrip()
        if before.endswith("(") or before.endswith(","):
            pass
        elif before.endswith("=") and not before.endswith(("==", "~=", "<=", ">=")):
            pass
        else:
            continue
        i = m.end()
        cond_start = i
        pos = _find_word(text, " then ", i)
        if pos == -1:
            return None, None
        cond = text[cond_start:pos].strip()
        i = pos + len(" then ")
        val1_start = i
        pos = _find_word(text, " else ", i)
        if pos == -1:
            return None, None
        val1 = text[val1_start:pos].strip()
        i = pos + len(" else ")
        val2_start = i
        end = _find_value_end(text, i)
        val2 = text[val2_start:end].strip()
        if not cond or not val1 or val2 is None:
            return None, None
        replacement = f"(({cond}) and ({val1}) or ({val2}))"
        return text[:start] + replacement + text[end:], (cond, val1, val2)
    return None, None


def normalize(text: str) -> str:
    """Convierte Luau en algo que `luac` entienda.

    Se quitan, en este orden:
      1. las anotaciones de tipo (`local x: number = 1` -> `local x = 1`);
      2. los operadores compuestos (`+=`, `..=`);
      3. `continue`;
      4. las expresiones `if/then/else` de Luau.

    Nada de esto puede romper el código: al final se comprueba que el
    resultado compila, y si no, se devuelve el original para que el error de
    sintaxis se reporte tal cual.
    """
    # 1) anotaciones de tipo (antes de tocar los operadores, porque una
    #    anotacion puede acabar en `,` o `)`).
    text = strip_type_annotations(text)

    out = []
    for line in text.split("\n"):
        for pat, rep in LUAU_ONLY:
            line = pat.sub(rep, line)
        out.append(line)
    text = "\n".join(out)
    # Expresiones if/then/else (Luau): se reescriben en bucle hasta que no queden.
    for _ in range(20):
        new, _info = _split_if_expression(text)
        if new is None:
            break
        text = new
    return text
