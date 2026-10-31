#!/usr/bin/env python3
"""Detecta el fallo 'local usado antes de su declaración' en ficheros Luau.

En Lua/Luau un `local` solo existe desde su punto de declaración hacia
adelante. Si una función anterior lo menciona, el nombre se compila como
GLOBAL: en tiempo de ejecución vale nil y la llamada revienta con
"attempt to call a nil value" (o devuelve nil en silencio).

Metodo: se compila el fichero y se mira el bytecode. Un nombre declarado como
local en el fichero pero leido con GETTABUP (global) es un bug; tambien
importa que se ASIGNE como global, porque entonces el local nunca cambia.

Los ficheros con sintaxis solo-Luau (+=, continue, if-expresion) se normalizan
antes de compilar.

Complementa a check-luau-globals.py: aquel avisa de cualquier global leído y
nunca escrito; este solo avisa cuando el nombre **existe como local** en el
fichero, que es el caso inequívoco.

Uso:  python3 tools/check-locals.py [carpeta ...]
Devuelve 1 si encuentra algo.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import noctalia_api as api  # noqa: E402
from noctalia_api import normalize  # noqa: E402

# --------------------------------------------------------------------- analizar

# En Lua 5.2+ la lectura de un global es GETTABUP ... ; _ENV "nombre"
# (GETGLOBAL ya no existe). Una lectura de un local capturado es GETUPVAL y
# de un local normal GETLOCAL: ninguna de las dos es un bug.
GETGLOBAL_RE = re.compile(r'GETTABUP\s+\d+\s+\d+\s+\d+\s*;\s*_ENV\s+"([^"]+)"')
# Asignar a un global que en el fichero es `local`: la asignacion se va al
# global y el local nunca cambia. Misma causa raiz.
SETGLOBAL_RE = re.compile(r'SETTABUP\s+\d+\s+\d+\s+\d+\s*;\s*_ENV\s+"([^"]+)"')

# Un local puede declarar varios nombres: "local a, b = 1, 2"
LOCAL_MULTI_RE = re.compile(r"^\s*local\s+([A-Za-z_][\w,\s\[\]'\"-]*?)\s*(?:=[^=]|$)")
LOCAL_FUNCTION_RE = re.compile(r"^\s*local\s+function\s+([A-Za-z_]\w*)")


def declared_locals(text: str) -> dict[str, int]:
    """Nombres declarados como local y línea de la declaración."""
    locals_: dict[str, int] = {}
    for number, line in enumerate(text.split("\n"), 1):
        match = LOCAL_FUNCTION_RE.match(line)
        if match:
            locals_.setdefault(match.group(1), number)
            continue
        match = LOCAL_MULTI_RE.match(line)
        if not match:
            continue
        raw = match.group(1)
        for part in raw.split(","):
            name = part.strip().split("=")[0].strip()
            # Solo el primer nombre vale: "local a, b = ..." declara los dos,
            # pero "local x, y = f()" tambien. Se limpian los indices.
            name = re.sub(r"\[[^\]]*\]", "", name).strip()
            name = name.split(".")[0].strip()
            if re.fullmatch(r"[A-Za-z_]\w*", name):
                locals_.setdefault(name, number)
    return locals_


def analyze(path: Path):
    """(hallazgos, motivo).

    Los hallazgos son (nombre, linea_local, linea_uso, problema). Si el fichero
    tiene un **error de sintaxis real**, se devuelve como motivo: un error de
    sintaxis nunca se traga (si se tragara, el fichero se quedaría sin revisar
    sin que nadie se enterase).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    locals_ = declared_locals(text)
    if not locals_:
        return None, "sin locals"

    listing, syntax_error = api.luau_bytecode(text)
    if listing is None:
        return None, "error de sintaxis: %s" % syntax_error

    hits: list[tuple[str, int, int, str]] = []
    for number, line in enumerate(listing.split("\n"), 1):
        match = GETGLOBAL_RE.search(line)
        if match:
            name = match.group(1)
            if name in locals_:
                hits.append(
                    (name, locals_[name], 0, "leido como global (el local no existe aun)")
                )
        match = SETGLOBAL_RE.search(line)
        if match:
            name = match.group(1)
            if name in locals_:
                hits.append(
                    (name, locals_[name], 0, "asignado como global (el local no cambia)")
                )
    return sorted(set(hits)), "ok"


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.add_argument("roots", nargs="*", default=["."])
    args = parser.parse_args(argv[1:])

    if not api.luac():
        print("no se encontró luac: no se puede revisar", file=sys.stderr)
        return 0

    files: list[Path] = []
    for raw in (args.roots or ["."]):
        root = Path(raw)
        if root.is_dir():
            files += api.luau_files(root)
        elif root.is_file():
            files.append(root)

    findings: list[dict] = []
    skipped = 0
    root = Path((args.roots or ["."])[0])
    for path in sorted(files):
        hits, motivo = analyze(path)
        if hits is None:
            if motivo.startswith("error de sintaxis"):
                # Un error de sintaxis es un FALLO, no una excusa para no
                # revisar el fichero: se reporta como error.
                findings.append(
                    {
                        "fichero": str(path),
                        "nombre": "<sintaxis>",
                        "linea_local": 0,
                        "problema": motivo,
                    }
                )
            else:
                skipped += 1
                print("  ??  %s  (%s)" % (path, motivo), file=sys.stderr)
            continue
        for name, line_local, _linea_uso, que in hits:
            findings.append(
                {
                    "fichero": str(path),
                    "nombre": name,
                    "linea_local": line_local,
                    "problema": que,
                }
            )

    if args.json:
        print(
            json.dumps(
                {
                    "herramienta": "check-locals.py",
                    "ficheros_revisados": len(files),
                    "plugins_revisados": len(api.plugin_dirs(Path(root))),
                    "hallazgos": findings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        current = None
        for item in findings:
            if item["fichero"] != current:
                current = item["fichero"]
                print(current)
            print(
                "  línea %-5d '%s': %s"
                % (item["linea_local"], item["nombre"], item["problema"])
            )
        print("---")
        print(
            "%d fichero(s) revisados, %d aviso(s), %d sin comprobar"
            % (len(files), len(findings), skipped)
        )

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
