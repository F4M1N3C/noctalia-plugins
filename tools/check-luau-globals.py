#!/usr/bin/env python3
"""Detecta globales sueltos en código Luau (la causa del "call to a nil value").

En Lua, `local function f()` solo es visible desde su declaración. Si una
función definida antes la llama, la referencia se resuelve al global `f`, que
nunca se asigna → en tiempo de ejecución es `nil` y salta un
"attempt to call a nil value".

Para detectarlo sin adivinar, este revisor compila cada fichero con `luac -l`
y mira el código byte a laella: los globales LEÍDOS (GETTABUP ... _ENV "x") que
nunca se ESCRIBEN (SETTABUP ... _ENV "x") son suspectos.

Uso:  python3 tools/check-luau-globals.py [carpeta ...]
Devuelve 1 si encuentra algo.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# Globales que legítimamente vienen de fuera (API de Noctalia y estándar).
ALLOWED = {
    "noctalia", "ui", "panel", "barWidget",
    "require", "ipairs", "pairs", "next", "pcall", "xpcall", "print",
    "select", "tonumber", "tostring", "type", "unpack", "rawget", "rawset",
    "rawequal", "rawlen", "setmetatable", "getmetatable", "loadstring",
    "collectgarbage", "coroutine", "math", "string", "table", "os", "io",
    "utf8", "bit32", "debug", "self", "_G", "_VERSION",
    # Puntos de entrada que llama Noctalia.
    "onOpen", "onClose", "onConfigChanged", "onIpc", "update", "onClick",
    "onRightClick", "onScroll", "onHover", "onKey", "onFocus", "onBlur",
}

GLOBAL_READ = re.compile(r"GETTABUP\s+\d+\s+\d+\s+\d+\s+;\s+_ENV\s+\"([A-Za-z_][A-Za-z0-9_]*)\"")
GLOBAL_WRITE = re.compile(r"SETTABUP\s+\d+\s+\d+\s+\d+\s+;\s+_ENV\s+\"([A-Za-z_][A-Za-z0-9_]*)\"")

COMPILERS = ["luac5.4", "luac", "luac5.1", "luajit"]


def compiler():
    for name in COMPILERS:
        if subprocess.run(["which", name], capture_output=True).returncode == 0:
            return name
    return ""


def globals_of(path: str, luac: str):
    result = subprocess.run(
        [luac, "-l", "-p", path], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, result.stderr.strip().splitlines()[:1]
    reads = set(GLOBAL_READ.findall(result.stdout))
    writes = set(GLOBAL_WRITE.findall(result.stdout))
    return (reads, writes), []


# --- análisis textual de respaldo (ficheros con sintaxis Luau) ------------

LOCAL_FUNCTION = re.compile(r"^\s*local\s+function\s+([A-Za-z_][A-Za-z0-9_]*)")
LOCAL_DECL = re.compile(r"^\s*local\s+([A-Za-z_][A-Za-z0-9_]*)\b")
ASSIGN_FUNCTION = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*function")
PARAMS = re.compile(r"function\s*[A-Za-z0-9_.:]*\s*\(([^)]*)\)")
CALL = re.compile(r"(?<![\w.:])([A-Za-z_][A-Za-z0-9_]*)\s*\(")
FIELD = re.compile(r"[.:]\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def strip_code(line: str) -> str:
    out = []
    index = 0
    quote = None
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            out.append(" ")
            index += 1
            continue
        if char in "\"'":
            quote = char
            out.append(" ")
            index += 1
            continue
        if char == "-" and line[index : index + 2] == "--":
            break
        out.append(char)
        index += 1
    return "".join(out)


def textual_check(path: str):
    """Detecta llamadas a funciones locales declaradas más abajo."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        raw = handle.read().split("\n")
    lines = [strip_code(line) for line in raw]

    declared = {}
    for number, line in enumerate(lines, start=1):
        for pattern in (LOCAL_FUNCTION, LOCAL_DECL):
            match = pattern.match(line)
            if match:
                name = match.group(1)
                declared.setdefault(name, []).append(number)
    # X = function sin local: es un global (no un error si se escribe).
    globals_written = set()
    for line in lines:
        match = ASSIGN_FUNCTION.match(line)
        if match:
            globals_written.add(match.group(1))
    # Parámetros: se consideran definidos en todo el fichero (aproximación).
    parameters = set()
    for line in lines:
        for match in PARAMS.finditer(line):
            for part in match.group(1).split(","):
                part = part.strip().split("=")[0].strip()
                if part and part.isidentifier():
                    parameters.add(part)

    problems = []
    for number, line in enumerate(lines, start=1):
        for match in CALL.finditer(line):
            name = match.group(1)
            if name in ALLOWED or name in parameters or name in globals_written:
                continue
            if name in declared and min(declared[name]) > number:
                problems.append(
                    (number, name, "referencia adelantada: se declara en la línea %d" % min(declared[name]))
                )
    return problems


def main(argv):
    roots = argv[1:] or ["."]
    luac = compiler()
    if not luac:
        print("no se encontró luac: no se puede revisar", file=sys.stderr)
        return 0

    files = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
            continue
        for current, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            for name in names:
                if name.endswith(".luau"):
                    files.append(os.path.join(current, name))

    problems = 0
    total_problems = 0
    skipped = 0
    for path in sorted(files):
        data, errors = globals_of(path, luac)
        if data is None:
            # Sintaxis específica de Luau: se revisa con el análisis textual.
            problems = textual_check(path)
            if problems:
                print(path)
                for number, name, reason in problems:
                    print("  línea %-5d %-22s %s" % (number, name, reason))
                total_problems += len(problems)
            skipped += 1
            continue
        reads, writes = data
        suspects = sorted(reads - writes - ALLOWED)
        if suspects:
            print(path)
            for name in suspects:
                print("  global leído y nunca escrito: %s" % name)
            problems += len(suspects)
            total_problems += len(suspects)
    print("---")
    print(
        "%d fichero(s) revisados, %d aviso(s), %d revisados solo con texto"
        % (len(files), total_problems, skipped)
    )
    return 1 if total_problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
