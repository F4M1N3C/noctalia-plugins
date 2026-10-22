#!/usr/bin/env python3
"""Batería de comprobaciones del verificador de plugins.

El verificador decide qué fallos bloquean la pasada y cuáles se informan.
Esa lógica se ha roto varias veces (un fallo sin atribuir se perdía y la
pasada terminaba con "todo bien"), así que aquí se comprueba con fallos
simulados.

Nada de esto toca la instalación real: todo se hace sobre copias
temporales del repositorio, del despliegue y del estado.

Uso:  python3 lyrics-carousel/tools/check-verifier.py [--root RAIZ]
Devuelve 1 si algún escenario no se comporta como debe.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
VERIFIER = os.path.join(HERE, "verify-plugins.py")
DEPLOYED = os.path.expanduser(
    "~/.local/share/noctalia/plugins/lyrics-carousel"
)
EMPTY_BIN = os.path.join(tempfile.gettempdir(), "lyrics-carousel-emptybin")


def run(root, env=None, ui=False, deploy=None, state=None):
    cmd = [sys.executable, VERIFIER, "--root", root]
    if deploy:
        cmd += ["--deploy", deploy]
    if state:
        cmd += ["--state", state]
    if not ui:
        cmd.append("--no-ui")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=1800, env=env
    )
    fallos = [
        line.strip() for line in result.stdout.split("\n") if "fallo de" in line
    ]
    return result.returncode, fallos, result.stdout


def copia_repo(root, con_tools=True):
    """Copia del repositorio: los ficheros de prueba no tocan el original."""
    raiz = tempfile.mkdtemp(prefix="verifier-repo-")
    shutil.copytree(
        os.path.join(root, "lyrics-carousel"), os.path.join(raiz, "lyrics-carousel")
    )
    if con_tools:
        shutil.copytree(os.path.join(root, "tools"), os.path.join(raiz, "tools"))
    else:
        os.makedirs(os.path.join(raiz, "tools"), exist_ok=True)
    return raiz


def copia_despliegue():
    """Copia del plugin desplegado: las pruebas no tocan la instalación."""
    raiz = tempfile.mkdtemp(prefix="verifier-deploy-")
    destino = os.path.join(raiz, "lyrics-carousel")
    shutil.copytree(DEPLOYED, destino)
    return raiz, destino


def estado_temporal():
    """Carpeta de estado vacía: los overrides pendientes van ahí."""
    return tempfile.mkdtemp(prefix="verifier-state-")


def escenario(
    nombre, rc, fallos, esperado_rc, esperado=None, no_esperado=None, salida=None
):
    ok = rc == esperado_rc
    if esperado is not None:
        # Un aviso no es un "fallo": si se pasa la salida, se busca ahi.
        if salida is not None:
            ok = ok and esperado in salida
        else:
            ok = ok and any(esperado in f for f in fallos)
    if no_esperado is not None:
        ok = ok and not any(no_esperado in f for f in fallos)
    print("  %s %-52s rc=%d %s" % ("ok " if ok else "FALLO", nombre, rc, fallos[:2]))
    return ok


def main(argv):
    root = DEFAULT_ROOT
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]

    resultados = []

    print("1) estado normal -> rc 0")
    rc, fallos, salida = run(root)
    resultados.append(escenario("estado normal", rc, fallos, 0))

    print("2) .luau con error de sintaxis en mi plugin -> rc 1, dos detecciones")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_sintaxis.luau")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write('local x = 1\nif x == 1 then\n  print("sin cerrar"\n')
    try:
        rc, fallos, salida = run(raiz)
        resultados.append(
            escenario("error de sintaxis propio", rc, fallos, 1, "fallo de luac")
        )
        # El error tiene que detectarlo tambien el autotest: dos vias
        # independientes, para que no dependa solo de la estatica.
        resultados.append(
            escenario(
                "error de sintaxis en el autotest",
                rc,
                fallos,
                1,
                "fallo de selftest (repo)",
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("3) .luau solo-Luau valido -> sin falsos positivos de sintaxis")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_luau.luau")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("local x: number = 1\nprint(x)\n")
    try:
        rc, fallos, salida = run(raiz)
        # El fichero es valido: la comprobacion de sintaxis no debe
        # llamarlo error. Lo que si falla es la invariante del plugin (sus
        # .luau tienen que compilar tal cual), y eso es lo que mantiene
        # concluyente la comprobacion estatica.
        resultados.append(
            escenario(
                "sintaxis de Luau: sin falso positivo",
                rc,
                fallos,
                1,
                no_esperado="fallo de luac",
            )
        )
        resultados.append(
            escenario(
                "sintaxis de Luau: invariante del plugin",
                rc,
                fallos,
                1,
                esperado="fallo de selftest (repo)",
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("3b) .luau con Luau que ningun normalizador cubre -> sin error")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_generico.luau")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("local x: Array<number> = {}\nprint(x)\n")
    try:
        rc, fallos, salida = run(raiz)
        resultados.append(
            escenario(
                "Luau con genericos: sin falso positivo",
                rc,
                fallos,
                1,
                no_esperado="fallo de luac",
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("4) autotest que falla sin nombrar al plugin -> rc 1")
    deploy, destino = copia_despliegue()
    selftest = os.path.join(destino, "bin", "selftest.py")
    with open(selftest, encoding="utf-8") as handle:
        original = handle.read()
    with open(selftest, "w", encoding="utf-8") as handle:
        handle.write(
            original.replace(
                "    failed = 0\n",
                '    check("simulacion", False, "sin nombrar al plugin")\n    failed = 0\n',
            )
        )
    try:
        rc, fallos, salida = run(root, deploy=deploy)
        resultados.append(
            escenario(
                "autotest sin nombrar",
                rc,
                fallos,
                1,
                "fallo de selftest (despliegue)",
            )
        )
    finally:
        shutil.rmtree(deploy, ignore_errors=True)

    print("5) validador compartido que revienta -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    with open(os.path.join(raiz, "tools", "check-luau-globals.py"), "w") as handle:
        handle.write("import sys\nsys.exit(3)\n")
    try:
        rc, fallos, salida = run(raiz)
        resultados.append(
            escenario("validador que revienta", rc, fallos, 1, "fallo de check-luau-globals")
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("6) sin compilador -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    os.makedirs(EMPTY_BIN, exist_ok=True)
    env = {**os.environ, "PATH": EMPTY_BIN}
    try:
        rc, fallos, salida = run(raiz, env=env)
        resultados.append(escenario("sin compilador", rc, fallos, 1))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("7) sin noctalia no se ejercita nada -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    env = {**os.environ, "PATH": EMPTY_BIN}
    try:
        rc, fallos, salida = run(raiz, env=env, ui=True)
        resultados.append(
            escenario("sin noctalia", rc, fallos, 1, "fallo de ejercicio")
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("8) log de Noctalia inexistente -> rc 1 (infraestructura)")
    spec = importlib.util.spec_from_file_location("verificador", VERIFIER)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    modulo.LOG = os.path.join(tempfile.gettempdir(), "no-existe-noctalia.log")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = modulo.main(["--no-ui"])
        resultados.append(escenario("log inexistente", rc, [], 1))
    except SystemExit:
        resultados.append(escenario("log inexistente", 0, [], 1))

    print("9) .luau con bytes que no son UTF-8 -> la verificacion no revienta")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_bytes.luau")
    with open(probe, "wb") as handle:
        handle.write(b"local x = '\xff\xfe'\nif x == 1 then\n  print(\"sin cerrar\"\n")
    try:
        rc, fallos, salida = run(raiz)
        resultados.append(
            escenario("bytes no UTF-8", rc, fallos, 1, "fallo de luac")
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("10) el ejercicio se hace de verdad (el IPC llega al widget)")
    rc, fallos, salida = run(root, ui=True)
    resultados.append(escenario("el ejercicio se hace", rc, fallos, 0))
    resultados.append(
        escenario("el verificador dice que el ejercicio fue ok", 0, [], 0)
        if "ejercicio propio: ok" in salida
        else escenario("el verificador dice que el ejercicio fue ok", 1, [], 0)
    )

    print("11) con ajustes pendientes -> se avisa y no se pisa nada")
    state = estado_temporal()
    try:
        pendientes = os.path.join(
            state, "plugins", "data", "faminec", "lyrics-carousel", "overrides.json"
        )
        os.makedirs(os.path.dirname(pendientes), exist_ok=True)
        with open(pendientes, "w", encoding="utf-8") as handle:
            handle.write('{"marker": true}')
        rc, fallos, salida = run(root, ui=True, state=state)
        resultados.append(
            escenario("ajustes pendientes: se avisa", rc, fallos, 1, "fallo de ejercicio")
        )
    finally:
        shutil.rmtree(state, ignore_errors=True)

    print("12) despliegue sin autotest -> se avisa (copia desactualizada)")
    deploy, destino = copia_despliegue()
    os.remove(os.path.join(destino, "bin", "selftest.py"))
    try:
        rc, fallos, salida = run(root, deploy=deploy)
        resultados.append(
            escenario(
                "despliegue sin autotest: se avisa",
                rc,
                fallos,
                0,
                salida=salida,
                esperado="desactualizada",
            )
        )
    finally:
        shutil.rmtree(deploy, ignore_errors=True)

    print("13) el log rotado -> rc 1 (no se ha revisado nada)")
    spec = importlib.util.spec_from_file_location("verificador_rotado", VERIFIER)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    log = os.path.join(tempfile.gettempdir(), "verificador-rotado.log")
    with open(log, "w", encoding="utf-8") as handle:
        handle.write("x" * 100)
    modulo.LOG = log
    offset = modulo.log_size()
    with open(log, "w", encoding="utf-8") as handle:
        handle.write("")
    try:
        resultados.append(
            escenario("el log rotado se detecta", 0 if modulo.log_rotated(offset) else 1, [], 0)
        )
    finally:
        if os.path.isfile(log):
            os.remove(log)

    print("14) sin validadores compartidos -> rc 1 (infraestructura)")
    raiz = copia_repo(root, con_tools=False)
    try:
        rc, fallos, salida = run(raiz)
        resultados.append(
            escenario("sin validadores compartidos", rc, fallos, 1)
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    fallos = resultados.count(False)
    print("%d escenario(s), %d fallo(s)" % (len(resultados), fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
