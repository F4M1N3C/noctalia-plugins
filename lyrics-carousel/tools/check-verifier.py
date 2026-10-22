#!/usr/bin/env python3
"""Batería de comprobaciones del verificador de plugins.

El verificador decide qué fallos bloquean la pasada y cuáles se informan.
Esa lógica se ha roto varias veces (un fallo sin atribuir se perdía y la
pasada terminaba con "todo bien"), así que aquí se comprueba con fallos
simulados.

Las comprobaciones se hacen sobre el resultado estructurado del
verificador (--json), no sobre el texto de sus mensajes: así se
comprueba el comportamiento y no mis palabras.

Nada de esto toca la instalación real: todo se hace sobre copias
temporales del repositorio, del despliegue y del estado.

Uso:  python3 lyrics-carousel/tools/check-verifier.py [--root RAIZ]
Devuelve 1 si algún escenario no se comporta como debe.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
VERIFIER = os.path.join(HERE, "verify-plugins.py")
DEPLOYED = os.path.expanduser("~/.local/share/noctalia/plugins/lyrics-carousel")
OWNER = "lyrics-carousel"
EMPTY_BIN = os.path.join(tempfile.gettempdir(), "lyrics-carousel-emptybin")


CODIGO_INCOHERENTE = []


def run(root, env=None, ui=False, deploy=None, state=None):
    """Ejecuta el verificador y devuelve (codigo, resultado en JSON)."""
    cmd = [sys.executable, VERIFIER, "--root", root, "--json"]
    if deploy:
        cmd += ["--deploy", deploy]
    if state:
        cmd += ["--state", state]
    if not ui:
        cmd.append("--no-ui")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=1800, env=env
    )
    try:
        datos = json.loads(result.stdout)
    except ValueError:
        datos = {}
    # El codigo de salida y el del JSON tienen que coincidir: si no, el
    # resultado estructurado miente.
    declarado = datos.get("codigo")
    if declarado is not None and declarado != result.returncode:
        print(
            "  FALLO el codigo de salida (%d) no coincide con el del JSON (%s)"
            % (result.returncode, declarado)
        )
        CODIGO_INCOHERENTE.append(True)
    return result.returncode, datos


def fallos_propios(datos):
    """Fallos atribuidos a este plugin."""
    return [f for f in datos.get("fallos", []) if f.get("plugin") == OWNER]


def fallos_infra(datos):
    """Fallos de la propia verificacion (no tienen dueño: no son de nadie)."""
    return [f for f in datos.get("fallos", []) if f.get("tipo") == "infra"]


def avisos_propios(datos):
    return [a for a in datos.get("avisos", []) if a.get("plugin") == OWNER]


def autotest(datos, donde):
    for a in datos.get("autotests", []):
        if a.get("donde") == donde:
            return a
    return None


def hay_etiqueta(lista, etiqueta):
    return any(f.get("etiqueta") == etiqueta for f in lista)


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


def escenario(nombre, ok, detalle=""):
    print("  %s %-52s %s" % ("ok " if ok else "FALLO", nombre, detalle))
    return ok


def main(argv):
    root = DEFAULT_ROOT
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]

    resultados = []

    print("1) estado normal -> rc 0 y sin fallos propios")
    rc, datos = run(root)
    resultados.append(
        escenario(
            "estado normal",
            rc == 0 and not fallos_propios(datos),
            "rc=%d fallos=%d" % (rc, len(fallos_propios(datos))),
        )
    )

    print("2) .luau con error de sintaxis en mi plugin -> dos detecciones")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_sintaxis.luau")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write('local x = 1\nif x == 1 then\n  print("sin cerrar"\n')
    try:
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "error de sintaxis: lo ve la comprobacion estatica",
                rc == 1 and hay_etiqueta(fallos_propios(datos), "luac"),
                "fallos=%s" % [f["etiqueta"] for f in fallos_propios(datos)],
            )
        )
        resultados.append(
            escenario(
                "error de sintaxis: lo ve tambien el autotest",
                rc == 1 and (autotest(datos, "repo") or {}).get("ok") is False,
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
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "sintaxis de Luau: no es un error de sintaxis",
                rc == 1 and not hay_etiqueta(fallos_propios(datos), "luac"),
                "fallos=%s" % [f["etiqueta"] for f in fallos_propios(datos)],
            )
        )
        resultados.append(
            escenario(
                "sintaxis de Luau: se rompe la invariante del plugin",
                rc == 1 and (autotest(datos, "repo") or {}).get("ok") is False,
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
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "Luau con genericos: no es un error de sintaxis",
                rc == 1 and not hay_etiqueta(fallos_propios(datos), "luac"),
            )
        )
        resultados.append(
            escenario(
                "Luau con genericos: se avisa",
                rc == 1 and hay_etiqueta(avisos_propios(datos), "luac"),
                "avisos=%s" % [a["etiqueta"] for a in avisos_propios(datos)],
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("4) autotest que falla sin nombrar al plugin -> se detecta")
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
        rc, datos = run(root, deploy=deploy)
        resultados.append(
            escenario(
                "autotest sin nombrar",
                rc == 1 and (autotest(datos, "despliegue") or {}).get("ok") is False,
            )
        )
    finally:
        shutil.rmtree(deploy, ignore_errors=True)

    print("5) validador compartido que reventa -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    with open(os.path.join(raiz, "tools", "check-luau-globals.py"), "w") as handle:
        handle.write("import sys\nsys.exit(3)\n")
    try:
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "validador que revienta",
                rc == 1
                and hay_etiqueta(fallos_infra(datos), "check-luau-globals.py"),
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("6) sin compilador -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    os.makedirs(EMPTY_BIN, exist_ok=True)
    env = {**os.environ, "PATH": EMPTY_BIN}
    try:
        rc, datos = run(raiz, env=env)
        resultados.append(
            escenario(
                "sin compilador",
                rc == 1 and hay_etiqueta(fallos_infra(datos), "luac"),
                "infra=%s" % [f["etiqueta"] for f in fallos_infra(datos)],
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("7) sin noctalia no se ejercita nada -> rc 1 (infraestructura)")
    raiz = copia_repo(root)
    env = {**os.environ, "PATH": EMPTY_BIN}
    try:
        rc, datos = run(raiz, env=env, ui=True)
        resultados.append(
            escenario(
                "sin noctalia",
                rc == 1
                and any(
                    f.get("etiqueta") == "ejercicio de los plugins"
                    for f in fallos_infra(datos)
                ),
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("8) log de Noctalia inexistente -> rc 1 (infraestructura)")
    spec = importlib.util.spec_from_file_location("verificador", VERIFIER)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    modulo.LOG = os.path.join(tempfile.gettempdir(), "no-existe-noctalia.log")
    try:
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = modulo.main(["--no-ui", "--json"])
        try:
            datos = json.loads(salida.getvalue())
        except ValueError:
            datos = {}
        resultados.append(
            escenario(
                "log inexistente",
                rc == 1 and hay_etiqueta(fallos_infra(datos), "log de Noctalia"),
                "infra=%s" % [f["etiqueta"] for f in fallos_infra(datos)],
            )
        )
    except SystemExit:
        resultados.append(escenario("log inexistente", False))

    print("9) .luau con bytes que no son UTF-8 -> la verificacion no revienta")
    raiz = copia_repo(root)
    probe = os.path.join(raiz, "lyrics-carousel", "tmp_bytes.luau")
    with open(probe, "wb") as handle:
        handle.write(b"local x = '\xff\xfe'\nif x == 1 then\n  print(\"sin cerrar\"\n")
    try:
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "bytes no UTF-8",
                rc == 1 and hay_etiqueta(fallos_propios(datos), "luac"),
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print("10) el ejercicio se hace de verdad (el IPC llega al widget)")
    rc, datos = run(root, ui=True)
    resultados.append(
        escenario("el ejercicio se hace", rc == 0 and datos.get("ejercicio") == "ok")
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
        rc, datos = run(root, ui=True, state=state)
        resultados.append(
            escenario(
                "ajustes pendientes: se avisa",
                rc == 1 and bool(datos.get("ejercicio_problemas")),
                "%s" % datos.get("ejercicio_problemas"),
            )
        )
    finally:
        shutil.rmtree(state, ignore_errors=True)

    print("11b) una escritura que no ocurre -> se detecta")
    spec = importlib.util.spec_from_file_location("verificador_escritura", VERIFIER)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    destino = os.path.join(tempfile.gettempdir(), "verificador-escritura.json")
    if os.path.isfile(destino):
        os.remove(destino)
    resultados.append(
        escenario(
            "escritura que no ocurre: se detecta",
            not modulo.escritura_realizada(destino, ["marker"]),
        )
    )
    with open(destino, "w", encoding="utf-8") as handle:
        handle.write('{"marker": true}')
    resultados.append(
        escenario(
            "escritura realizada: se reconoce",
            modulo.escritura_realizada(destino, ["marker"]),
        )
    )
    resultados.append(
        escenario(
            "escritura de otra clave: no se reconoce",
            not modulo.escritura_realizada(destino, ["karaoke"]),
        )
    )
    viejo = modulo.estado_overrides(destino)
    resultados.append(
        escenario(
            "fichero viejo: no se da por buena",
            not modulo.escritura_realizada(destino, ["marker"], viejo),
        )
    )
    with open(destino, "w", encoding="utf-8") as handle:
        handle.write('{"marker": false}')
    resultados.append(
        escenario(
            "fichero cambiado: se reconoce",
            modulo.escritura_realizada(destino, ["marker"], viejo),
        )
    )
    os.remove(destino)

    print("12) despliegue sin autotest -> se avisa (copia desactualizada)")
    deploy, destino = copia_despliegue()
    os.remove(os.path.join(destino, "bin", "selftest.py"))
    try:
        rc, datos = run(root, deploy=deploy)
        resultados.append(
            escenario(
                "despliegue sin autotest: se avisa",
                rc == 0
                and hay_etiqueta(avisos_propios(datos), "selftest (despliegue)"),
                "%s" % [a.get("etiqueta") for a in avisos_propios(datos)],
            )
        )
    finally:
        shutil.rmtree(deploy, ignore_errors=True)

    print("13) el log rotado -> se detecta")
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
        resultados.append(escenario("el log rotado se detecta", modulo.log_rotated(offset)))
    finally:
        if os.path.isfile(log):
            os.remove(log)

    print("14) sin validadores compartidos -> rc 1 (infraestructura)")
    raiz = copia_repo(root, con_tools=False)
    try:
        rc, datos = run(raiz)
        resultados.append(
            escenario(
                "sin validadores compartidos",
                rc == 1
                and any(
                    f.get("etiqueta") == "validadores compartidos"
                    for f in datos.get("fallos", [])
                ),
            )
        )
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    fallos = resultados.count(False)
    print(
        "%d escenario(s), %d fallo(s), %d incoherencia(s) de codigo"
        % (len(resultados), fallos, len(CODIGO_INCOHERENTE))
    )
    return 1 if (fallos or CODIGO_INCOHERENTE) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
