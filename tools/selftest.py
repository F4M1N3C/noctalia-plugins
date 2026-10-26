#!/usr/bin/env python3
"""Autotest de los validadores estáticos.

Un validador que nunca dispara no vale nada, y uno que dispara de más bloquea
la publicación sin motivo. Este script monta un plugin de mentira en un
directorio temporal, con defectos conocidos, y comprueba que:

* cada defecto se detecta (y con el mensaje esperado);
* el código correcto **no** produce avisos (control de falsos positivos);
* **ninguna comprobación puede pasar en vacío**.

Lo último es lo importante: una comprobación del tipo "no hay errores" daría
limpio igual si el revisor no hubiera mirado nada. Por eso cada revisor
informa de **cuántos ficheros revisó**, y aquí se exige que:

1. el revisor dijera haber revisado el número de ficheros del fixture;
2. el control positivo (el defecto que sí tiene que detectar) Saltara en la
   **misma** ejecución — si el detector está roto, el control negativo no
   puede "pasar" por casualidad.

Es el mismo guardián que se puso en la suite de `lyrics-carousel`: la
comprobación comprueba su propio instrumento.

Uso:  python3 tools/selftest.py
Devuelve 1 si algo falla.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

# ------------------------------------------------------------------ fixtures

MANIFEST = """id = "test/probe"
name = "Probe"
version = "1.0.0"
plugin_api = 26
author = "test"
license = "MIT"
dependencies = []
tags = ["utility"]
icon = "settings"
description = "Plugin de prueba para los validadores estaticos."

[[setting]]
key = "notes_dir"
type = "folder"
label_key = "settings.notes_dir.label"
description_key = "settings.notes_dir.description"
default = "~/Notes"

[[widget]]
id = "widget"
entry = "widget.luau"

[[panel]]
id = "panel"
entry = "panel.luau"
width = 400
height = 300
"""

PANEL = """--!nonstrict
-- `ui` es un global del core; `tr` lo define cada plugin.

local function tr(key)
  return noctalia.tr(key)
end

local function helper(glyphName, titleKey)
  return ui.row({ align = "center" }, {
    ui.glyph({ name = glyphName, size = 16 }),
    ui.label({ text = tr(titleKey) }),
  })
end

local function helperLocal()
  return true
end

function onCorrecto()
  return true
end

function onOpen(context)
  local ctx = context
  return ctx
end

function onClose()
  return true
end

function render()
  return ui.column({ gap = 4 }, {
    -- DEFECTO 1: glifo que no existe en Tabler
    ui.button({ glyph = "no-existe-este-icono", variant = "ghost", onClick = "onCorrecto" }),
    -- DEFECTO 2: variante de boton que no existe
    ui.button({ glyph = "x", variant = "tonal", onClick = "onCorrecto" }),
    -- DEFECTO 3: manejador que no existe
    ui.button({ glyph = "x", variant = "ghost", onClick = "noExisteEsteHandler" }),
    -- DEFECTO 4: manejador declarado como local
    ui.button({ glyph = "x", variant = "ghost", onClick = "helperLocal" }),
    -- DEFECTO 5: clave de traduccion inexistente
    ui.label({ text = tr("clave.que.no.existe") }),
    -- DEFECTO 6: recurso sin liberar
    noctalia.idle.watch(1, function() end),
    -- CONTROL: esto esta bien y no debe dar aviso
    ui.button({ glyph = "x", variant = "ghost", onClick = "onCorrecto" }),
    ui.label({ text = tr("existe") }),
    helper("settings", "existe"),
  })
end

render()
"""

WIDGET = """--!nonstrict
function update()
  return true
end
"""

# Un fichero con un error de sintaxis real: el validador tiene que
# reportarlo, no tragarselo.
ROTO = """--!nonstrict
local function roto()
  return 1 +
end
"""

# Un fichero con anotaciones de tipo de Luau: tiene que compilar tras
# normalizarlo, y el normalizador no puede comerse el "=".
CON_TIPOS = """--!nonstrict
local total: number = 1
local etiquetas: {string: number} = {}

local function suma(a: number, b: number): number
  return a + b
end

local tabla = { clave = 1, otra = 2 }

return { total = total, etiquetas = etiquetas, suma = suma, tabla = tabla }
"""

EN_JSON = {
    "existe": "Existe",
    "prefijo": {
        "uno": "Uno",
        "dos": "Dos",
    },
    "settings": {
        "notes_dir": {
            "label": "Notes Directory",
            "description": "Where notes are stored",
        },
    },
    "clave.muerta": "No la usa nadie",
}

ES_JSON = {
    "existe": "Existe",
    "prefijo": {
        "uno": "Uno",
        "dos": "Dos",
    },
    "settings": {
        "notes_dir": {
            "description": "Donde se guardan las notas",
        },
    },
    "clave.muerta": "No la usa nadie",
}


def build(root: Path) -> Path:
    plugin = root / "probe"
    (plugin / "translations").mkdir(parents=True)
    (plugin / "plugin.toml").write_text(MANIFEST, encoding="utf-8")
    (plugin / "panel.luau").write_text(PANEL, encoding="utf-8")
    (plugin / "widget.luau").write_text(WIDGET, encoding="utf-8")
    (plugin / "roto.luau").write_text(ROTO, encoding="utf-8")
    (plugin / "con_tipos.luau").write_text(CON_TIPOS, encoding="utf-8")
    (plugin / "translations" / "en.json").write_text(
        json.dumps(EN_JSON, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (plugin / "translations" / "es.json").write_text(
        json.dumps(ES_JSON, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return plugin


# -------------------------------------------------------------------- checks


def run(script: str, root: Path) -> dict:
    """Salida JSON de un validador: {herramienta, ficheros_revisados, hallazgos}."""
    result = subprocess.run(
        [sys.executable, str(TOOLS / script), "--json", str(root)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"herramienta": script, "ficheros_revisados": 0, "hallazgos": []}
    if isinstance(data, list):
        return {"herramienta": script, "ficheros_revisados": 0, "hallazgos": data}
    return data


def messages(items: list[dict]) -> str:
    return "\n".join(
        item.get("mensaje") or item.get("problema") or "" for item in items
    )


results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((name, bool(condition), detail))
    print(
        "  %s %s%s"
        % ("OK  " if condition else "FALLO", name, ("  -> " + detail) if detail and not condition else "")
    )
    return bool(condition)


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="noctalia-selftest-"))
    try:
        plugin = build(workdir)

        ui = run("check-ui-resources.py", workdir)
        ui_items = ui.get("hallazgos", [])
        text = messages(ui_items)

        print("check-ui-resources.py")
        ok = True
        # --- guarda anti-vacio: el revisor tiene que decir que ha mirado algo
        ok &= check(
            "el revisor informa de los ficheros revisados",
            isinstance(ui.get("ficheros_revisados"), int) and ui["ficheros_revisados"] > 0,
            str(ui.get("ficheros_revisados")),
        )
        ok &= check(
            "el revisor ha mirado los 4 ficheros del fixture",
            ui.get("ficheros_revisados") == 4,
            str(ui.get("ficheros_revisados")),
        )
        ok &= check("detecta el glifo inexistente", "glifo inexistente: no-existe-este-icono" in text)
        ok &= check("detecta la variante inválida", "variante de botón no válida: tonal" in text)
        ok &= check(
            "detecta el manejador huérfano",
            "manejador 'noExisteEsteHandler'" in text and "huérfano" in text,
        )
        ok &= check(
            "detecta el manejador declarado como local",
            "manejador 'helperLocal'" in text and "local" in text,
        )
        ok &= check(
            "detecta la clave de traducción inexistente",
            "clave de traducción inexistente: clave.que.no.existe" in text,
        )
        ok &= check(
            "detecta el recurso sin liberar",
            "idle.watch()" in text and "unwatch" in text,
        )
        ok &= check(
            "detecta el label_key que falta en en.json",
            "settings.notes_dir.label" in text,
        )
        ok &= check(
            "avisa de la clave sin traducir al español",
            "sin traducir al español" in text,
        )
        ok &= check(
            "avisa de la clave muerta",
            "clave sin usar en el código" in text,
        )
        ok &= check(
            "detecta el error de sintaxis",
            "error de sintaxis" in text,
        )

        print("  control de falsos positivos")
        ok &= check("no marca el glifo válido", "glifo inexistente: x" not in text)
        ok &= check(
            "no marca la variante válida", "variante de botón no válida: ghost" not in text
        )
        ok &= check("no marca el manejador global correcto", "'onCorrecto'" not in text)
        ok &= check(
            "no marca la clave que sí existe",
            "clave de traducción inexistente: existe" not in text,
        )
        ok &= check("no marca el glifo del helper", "glifo inexistente: settings" not in text)

        print("check-locals.py")
        loc = run("check-locals.py", workdir)
        loc_items = loc.get("hallazgos", [])
        ok &= check(
            "el revisor informa de los ficheros revisados",
            loc.get("ficheros_revisados") == 4,
            str(loc.get("ficheros_revisados")),
        )
        ok &= check(
            "no da falsos positivos con un plugin sano",
            not [
                i
                for i in loc_items
                if str(i.get("nombre", "")) != "<sintaxis>"
            ],
            messages(loc_items),
        )
        ok &= check(
            "reporta el error de sintaxis en vez de tragarselo",
            any(str(i.get("nombre", "")) == "<sintaxis>" for i in loc_items),
            messages(loc_items),
        )

        print("check-luau-globals.py")
        glo = run("check-luau-globals.py", workdir)
        glo_items = glo.get("hallazgos", [])
        ok &= check(
            "el revisor informa de los ficheros revisados",
            glo.get("ficheros_revisados") == 4,
            str(glo.get("ficheros_revisados")),
        )
        ok &= check(
            "no da falsos positivos con un plugin sano",
            not [
                i
                for i in glo_items
                if str(i.get("nombre", "")) != "<sintaxis>"
            ],
            messages(glo_items),
        )
        ok &= check(
            "reporta el error de sintaxis en vez de tragarselo",
            any(str(i.get("nombre", "")) == "<sintaxis>" for i in glo_items),
            messages(glo_items),
        )

        print("normalizador de Luau")
        sys.path.insert(0, str(TOOLS))
        import noctalia_api as api

        normalizado = api.normalize(CON_TIPOS)
        ok &= check(
            "conserva el '=' de una anotación de tipo",
            "local total = 1" in normalizado,
            normalizado.splitlines()[1] if len(normalizado.splitlines()) > 1 else "",
        )
        ok &= check(
            "conserva los parámetros de una función anotada",
            "local function suma(a, b)" in normalizado,
            "",
        )
        ok &= check(
            "no toca las claves de una tabla",
            "{ clave = 1, otra = 2 }" in normalizado,
            "",
        )
        ok &= check(
            "el resultado del normalizador compila",
            api.compile_ok(normalizado),
            api.compile_error(normalizado) or "",
        )

        print()
        fallos = [name for name, good, _ in results if not good]
        print(
            "autotest: %s (%d/%d)"
            % ("TODO CORRECTO" if not fallos else "HAY FALLOS", len(results) - len(fallos), len(results))
        )
        return 0 if not fallos else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
