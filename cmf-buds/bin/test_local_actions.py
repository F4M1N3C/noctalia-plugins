#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas del motor de atajos locales (no necesitan auriculares).

Se simula la señal del dial (un cambio de volumen del sink) y se comprueba
que se ejecuta la regla correcta:

  - la de N pulsaciones manda sobre la de "cualquiera"
  - la de "cualquiera" sigue funcionando como respaldo
  - mandan las reglas mas especificas (SUPER antes que ninguna)
  - una regla con el comando vacio no rompe nada
  - una rafaga de cambios es un solo gesto
  - las reglas editadas fuera del panel se recargan

Uso: python3 bin/test_local_actions.py
"""

from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_actions import LocalActionEngine, VolumeWatcher  # noqa: E402


class FakeEngine(LocalActionEngine):
    """Motor con volumen simulado y comandos registrados."""

    def __init__(self, rules):
        super().__init__("/tmp/cmf-buds-test")
        self.volume = 50
        self.fired = []
        self.rules = rules
        self._rules_mtime = 0.0
        self.modifiers.available = True
        self._last_volume = 50

    def _read_volume(self, sink):
        return self.volume

    def run_command(self, command):
        if command:
            self.fired.append(command)
        return True

    def _restore_volume(self, percent):
        self.volume = int(percent)
        self.note_self_change(int(percent))


def rule(rid, trigger, presses, modifier, command):
    require = [] if modifier in (None, "none") else [modifier]
    return {
        "id": rid,
        "trigger": trigger,
        "presses": presses,
        "modifier": modifier or "none",
        "command": command,
        "enabled": True,
        "notify": False,
        "restore_volume": False,
        "require": require,
        "forbid": [],
    }


def esperar(cond, timeout=10.0, paso=0.02):
    """Espera a que se cumpla la condicion.

    Los tests no duermen un tiempo fijo: esperan a que pase lo que tienen
    que comprobar. Asi no dependen de que la maquina vaya rapido, y una
    comprobacion no puede cumplirse "por casualidad" antes de que la
    situacion que dice comprobar se haya dado.
    """
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(paso)
    return bool(cond())


class Runner:
    def __init__(self, rules):
        self.engine = FakeEngine(rules)
        self.failures = 0

    def evento(self, volume, modifiers, gap=0.16):
        """Un pinchazo del dial.

        'gap' es el tiempo hasta el siguiente: dos pinchazos reales van
        separados 100-250 ms; una rafaga de muescas va pegada.
        """
        self.engine.modifiers.held = set(modifiers)
        self.engine.volume = volume
        self.engine._on_volume_change("fake")
        time.sleep(gap)

    def varios(self, volumes, modifiers, gap=0.16):
        for v in volumes:
            self.evento(v, modifiers, gap)

    def check(self, name, condition, detail=""):
        if condition:
            print("  OK   %s" % name)
        else:
            print("  FALLO %s %s" % (name, detail))
            self.failures += 1

    def calmarse(self):
        # deja expirar la ventana de calma (tras el eco del restore)
        time.sleep(1.6)
        self.engine.fired.clear()


def test_regla_cualquiera_sola():
    print("1) solo hay regla 'cualquiera' (dispara al instante)")
    r = Runner([rule("a", "volume_up", 0, "super", "SUPER")])
    r.evento(60, ["super"])
    # Sin reglas de N pulsaciones, "cualquiera" dispara al empezar el gesto.
    time.sleep(0.2)
    r.check("se ejecuta con SUPER", r.engine.fired == ["SUPER"], r.engine.fired)
    r.calmarse()
    r.evento(70, [])
    time.sleep(0.2)
    r.check("no se ejecuta sin el modificador", r.engine.fired == [], r.engine.fired)
    return r.failures


def test_contador_manda():
    print("2) 'cualquiera' + 3 pulsaciones: manda la de 3, la otra hace de respaldo")
    r = Runner(
        [
            rule("any", "volume_up", 0, "super", "CUALQUIERA"),
            rule("tres", "volume_up", 3, "super", "TRES"),
        ]
    )
    # un solo pinchazo: la de 3 no llega, la de "cualquiera" hace de respaldo
    r.evento(60, ["super"])
    # Con una regla de N pulsaciones pendiente, el respaldo espera a que
    # termine el gesto (si no, se comeria las pulsaciones).
    time.sleep(0.2)
    r.check(
        "el respaldo espera a que termine el gesto",
        r.engine.fired == [],
        r.engine.fired,
    )
    time.sleep(1.0)
    r.check("un pinchazo dispara el respaldo 'cualquiera'", r.engine.fired == ["CUALQUIERA"], r.engine.fired)
    r.calmarse()
    # tres pinchazos: la de 3 gana
    r.evento(65, ["super"], 0.15)
    r.evento(70, ["super"], 0.15)
    r.evento(75, ["super"], 0.05)
    time.sleep(0.3)
    r.check("tres pinchazos disparan la de 3", r.engine.fired == ["TRES"], r.engine.fired)
    time.sleep(1.5)
    r.check("la de 'cualquiera' no se repite", r.engine.fired == ["TRES"], r.engine.fired)
    return r.failures


def test_modificadores_distintos():
    print("3) reglas con modificadores distintos no se pisan")
    r = Runner(
        [
            rule("sin", "volume_up", 0, None, "SIN"),
            rule("con", "volume_up", 3, "super", "CON_SUPER"),
        ]
    )
    r.evento(60, [])
    time.sleep(0.2)
    r.check("sin modificador dispara la suya", r.engine.fired == ["SIN"], r.engine.fired)
    r.calmarse()
    r.evento(65, ["super"], 0.15)
    r.evento(70, ["super"], 0.15)
    r.evento(75, ["super"], 0.05)
    time.sleep(0.3)
    r.check("con SUPER se espera a las 3", r.engine.fired == ["CON_SUPER"], r.engine.fired)
    return r.failures


def test_especificidad():
    print("4) con dos reglas 'cualquiera' manda la mas especifica")
    r = Runner(
        [
            rule("sin", "volume_up", 0, None, "SIN"),
            rule("con", "volume_up", 0, "super", "CON_SUPER"),
        ]
    )
    r.evento(60, ["super"])
    time.sleep(0.2)
    r.check("con SUPER gana la regla de SUPER", r.engine.fired == ["CON_SUPER"], r.engine.fired)
    r.calmarse()
    r.evento(75, [])
    time.sleep(0.2)
    r.check("sin modificador gana la regla sin modificador", r.engine.fired == ["SIN"], r.engine.fired)
    return r.failures


def test_comando_vacio():
    print("5) regla con el comando vacio")
    r = Runner([rule("vacia", "volume_down", 0, "super", "")])
    r.evento(40, ["super"])
    time.sleep(0.2)
    r.check("no ejecuta nada", r.engine.fired == [], r.engine.fired)
    r.check("pero registra el evento", r.engine.last_event is not None)
    return r.failures


def test_rafaga():
    print("6) rafaga de cambios = un solo gesto")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.varios([60, 65, 70, 75, 80], ["super"], 0.02)
    time.sleep(0.3)
    r.check("una sola ejecucion", r.engine.fired == ["UNO"], r.engine.fired)
    return r.failures


def test_gesto_despues_de_restaurar():
    print("8) un gesto despues de restaurar el volumen no se pierde")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.evento(60, ["super"])
    time.sleep(0.2)
    r.check("la primera accion se ejecuta", r.engine.fired == ["UNO"], r.engine.fired)
    # el restore marca el volumen: un gesto nuevo debe detectarse igual
    r.engine._restore_volume(40)
    r.calmarse()
    r.engine.fired.clear()
    r.evento(45, ["super"])
    time.sleep(0.2)
    r.check("el gesto siguiente tambien", r.engine.fired == ["UNO"], r.engine.fired)
    return r.failures


def test_pinchazos_muy_juntos():
    print("9) pinchazos muy juntos (50 ms) se cuentan como varios")
    r = Runner(
        [
            rule("any", "volume_up", 0, "super", "CUALQUIERA"),
            rule("dos", "volume_up", 2, "super", "DOS"),
        ]
    )
    r.evento(60, ["super"], 0.05)
    r.evento(65, ["super"], 0.05)
    time.sleep(0.3)
    r.check("dos pinchazos rapidos disparan la de 2", r.engine.fired == ["DOS"], r.engine.fired)
    return r.failures


def test_cambio_propio_por_valor():
    print("10) nuestro cambio de volumen se reconoce por el valor, no por el tiempo")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.engine.modifiers.held = {"super"}
    # el motor pone el volumen a 40 (como hace el restore)
    r.engine._restore_volume(40)
    # mucho despues, el mismo valor: es nuestro, se ignora
    time.sleep(0.5)
    r.engine.volume = 40
    r.engine._on_volume_change("fake")
    time.sleep(0.2)
    r.check("el mismo valor no cuenta como gesto", r.engine.fired == [], r.engine.fired)
    # un valor distinto si cuenta (separado como dos pinchazos reales)
    time.sleep(0.2)
    r.engine.volume = 55
    r.engine._on_volume_change("fake")
    time.sleep(0.2)
    r.check("otro valor si cuenta", r.engine.fired == ["UNO"], r.engine.fired)
    return r.failures


def test_gestos_separados():
    print("11) gestos separados (mas de la ventana) = una accion cada uno")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.evento(60, ["super"], 0.9)   # gesto 1
    r.evento(65, ["super"], 0.9)   # gesto 2 (fuera de la ventana del gesto 1)
    time.sleep(0.3)
    r.check("dos acciones", r.engine.fired == ["UNO", "UNO"], r.engine.fired)
    return r.failures


def test_regla_malformada():
    print("12) una regla malformada se ignora y no tapa a las demas")
    r = Runner([rule("ok", "volume_up", 0, "super", "BIEN")])
    r.engine.rules.append({"id": "rota", "trigger": "volume_up", "presses": "abc", "require": 5})
    r.evento(60, ["super"])
    time.sleep(0.3)
    r.check("la regla buena se ejecuta", r.engine.fired == ["BIEN"], r.engine.fired)
    r.calmarse()
    r.engine.fired.clear()
    r.evento(70, ["super"])
    time.sleep(0.3)
    r.check("y sigue funcionando", r.engine.fired == ["BIEN"], r.engine.fired)
    return r.failures


def test_watcher_sobrevive():
    print("13) el watcher sobrevive a un error puntual y lo registra")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    calls = {"n": 0}
    logs = []

    def on_change(sink):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo simulado")

    watcher = VolumeWatcher(lambda: "sink-falso", on_change, logs.append)
    # Se inyecta el evento a mano: sin auriculares no hay 'pactl subscribe'
    # que avise de nada, y el camino del error hay que ejercitarlo de verdad.
    try:
        watcher._handle_line("Event 'change' on sink #42", "sink-falso", "42")
        ok = True
    except Exception as exc:
        ok = False
        logs.append("excepcion: %s" % exc)
    r.check("el error no se propaga", ok, logs)
    r.check(
        "el error queda en el log",
        any("fallo simulado" in m for m in logs),
        logs,
    )
    r.check("el evento se intento procesar", calls["n"] == 1, calls)
    return r.failures


def test_watcher_sin_suscripcion():
    print("14) si no se puede suscribir, avisa y sigue reintentando")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []
    original = local_actions.subprocess.Popen

    def boom(cmd, *args, **kwargs):
        # Solo se intercepta la suscripcion: 'subprocess.run' (pactl list)
        # tambien usa Popen por dentro y debe seguir funcionando.
        if cmd[:2] == ["pactl", "subscribe"]:
            raise OSError("pactl no disponible")
        return original(cmd, *args, **kwargs)

    local_actions.subprocess.Popen = boom
    try:
        watcher = VolumeWatcher(lambda: "sink-falso", lambda sink: None, logs.append)
        watcher.start()
        esperar(lambda: any("suscripcion" in m for m in logs))
        alive = watcher._thread.is_alive()
        watcher.stop()
    finally:
        local_actions.subprocess.Popen = original
    r.check("el hilo sigue vivo", alive)
    r.check(
        "avisa del fallo en el log",
        any("suscripcion" in m for m in logs),
        logs,
    )
    return r.failures


class FakeStop:
    """Sustituto del evento de parada: anota las esperas sin dormir."""

    def __init__(self, stop_after=None):
        self.waits = []
        self._stopped = False
        self._stop_after = stop_after

    def is_set(self):
        return self._stopped

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self._stop_after is not None and len(self.waits) >= self._stop_after:
            self._stopped = True
        return self._stopped

    def set(self):
        self._stopped = True


class FakeProc:
    """Proceso 'pactl subscribe' simulado."""

    def __init__(self, lines=(), delay=0.0):
        self.stdout = self._lines(lines, delay)
        self.killed = False

    def _lines(self, lines, delay):
        for line in lines:
            yield line
        if delay:
            time.sleep(delay)

    def kill(self):
        self.killed = True

    def terminate(self):
        self.killed = True


def test_espera_creciente():
    print("15) entre reintentos se espera cada vez mas")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []
    original = local_actions.subprocess.Popen

    def boom(cmd, *args, **kwargs):
        if cmd[:2] == ["pactl", "subscribe"]:
            raise OSError("pactl no disponible")
        return original(cmd, *args, **kwargs)

    local_actions.subprocess.Popen = boom
    try:
        watcher = VolumeWatcher(lambda: "sink-falso", lambda sink: None, logs.append)
        watcher._stop = FakeStop(stop_after=4)
        watcher.start()
        esperar(lambda: len(watcher._stop.waits) >= 4)
        waits = list(watcher._stop.waits)
        watcher.stop()
    finally:
        local_actions.subprocess.Popen = original
    r.check("las esperas crecen: 1, 2, 3, 4", waits == [1.0, 2.0, 3.0, 4.0], waits)
    r.check(
        "el log lleva la cuenta de fallos y cuando reintenta",
        any("(fallo 4): reintento en 4 s" in m for m in logs),
        logs,
    )
    r.check(
        "el numero de fallo y la espera van a juego, en orden",
        [m for m in logs if "fallo" in m]
        == [
            "Watcher: no se pudo abrir la suscripcion: pactl no disponible "
            "(fallo %d): reintento en %d s" % (n, n)
            for n in range(1, 5)
        ],
        [m for m in logs if "fallo" in m],
    )
    return r.failures


def test_contador_se_reinicia():
    print("16) el contador de fallos se reinicia cuando la suscripcion funciona")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []
    llamadas = {"n": 0}
    original = local_actions.subprocess.Popen
    original_healthy = local_actions.HEALTHY_SECONDS
    local_actions.HEALTHY_SECONDS = 0.05

    def fake_popen(cmd, *args, **kwargs):
        if cmd[:2] != ["pactl", "subscribe"]:
            return original(cmd, *args, **kwargs)
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            # El segundo intento es una suscripcion sana: reinicia el
            # contador. Sin ese reinicio, el fallo siguiente seria el nº2.
            return FakeProc(["Event 'change' on sink #42\n"], delay=0.15)
        raise OSError("pactl no disponible")

    local_actions.subprocess.Popen = fake_popen
    try:
        watcher = VolumeWatcher(lambda: "sink-falso", lambda sink: None, logs.append)
        watcher._stop = FakeStop(stop_after=4)
        watcher.start()
        esperar(lambda: len(watcher._stop.waits) >= 4)
        waits = list(watcher._stop.waits)
        watcher.stop()
    finally:
        local_actions.subprocess.Popen = original
        local_actions.HEALTHY_SECONDS = original_healthy
    r.check("el primer fallo espera 1 s", waits[:1] == [1.0], waits)
    r.check(
        "dice que la suscripcion vuelve a funcionar",
        any("vuelve a funcionar" in m for m in logs),
        logs,
    )
    r.check(
        "el fallo siguiente vuelve a ser el nº1 (contador reiniciado)",
        len([m for m in logs if "(fallo 1)" in m]) == 2,
        logs,
    )
    sanas = [i for i, m in enumerate(logs) if "vuelve a funcionar" in m]
    fallos1 = [i for i, m in enumerate(logs) if "(fallo 1)" in m]
    r.check(
        "y la suscripcion sana esta entre los dos fallos",
        len(sanas) == 1 and len(fallos1) == 2 and fallos1[0] < sanas[0] < fallos1[1],
        logs,
    )
    r.check(
        "y el siguiente ya espera mas (2 s)",
        waits[-1:] == [2.0],
        waits,
    )
    return r.failures


def test_suscripcion_corta():
    print("17) una suscripcion que se cierra antes de tiempo cuenta como fallo")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []
    original = local_actions.subprocess.Popen
    original_healthy = local_actions.HEALTHY_SECONDS
    local_actions.HEALTHY_SECONDS = 5.0

    def fake_popen(cmd, *args, **kwargs):
        if cmd[:2] != ["pactl", "subscribe"]:
            return original(cmd, *args, **kwargs)
        # Una suscripcion que se cierra al instante.
        return FakeProc([], delay=0.0)

    local_actions.subprocess.Popen = fake_popen
    try:
        watcher = VolumeWatcher(lambda: "sink-falso", lambda sink: None, logs.append)
        watcher._stop = FakeStop(stop_after=3)
        watcher.start()
        esperar(lambda: len(watcher._stop.waits) >= 3)
        waits = list(watcher._stop.waits)
        watcher.stop()
    finally:
        local_actions.subprocess.Popen = original
        local_actions.HEALTHY_SECONDS = original_healthy
    r.check(
        "avisa de que se cerro antes de tiempo",
        any("se cerro antes de tiempo" in m for m in logs),
        logs,
    )
    r.check("las esperas crecen", waits == [1.0, 2.0, 3.0], waits)
    r.check(
        "el log lleva la cuenta de fallos",
        any("(fallo 3): reintento en 3 s" in m for m in logs),
        logs,
    )
    return r.failures


def test_watcher_resolutor_falla():
    print("18) el watcher sobrevive a un resolutor que falla")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []

    def resolver_falla():
        raise RuntimeError("fallo al resolver el sink")

    watcher = VolumeWatcher(resolver_falla, lambda sink: None, logs.append)
    watcher._stop = FakeStop(stop_after=3)
    watcher.start()
    esperar(lambda: len(watcher._stop.waits) >= 3)
    waits = list(watcher._stop.waits)
    watcher.stop()
    # El hilo debe terminar: se espera a que pase, que comprobarlo en el
    # instante es una carrera y falla de vez en cuando.
    esperar(lambda: not watcher._thread.is_alive(), timeout=5.0)
    alive = watcher._thread.is_alive()
    r.check(
        "se registra el error",
        any("error inesperado" in m for m in logs),
        logs,
    )
    # Lo que prueba que el hilo no murio con la excepcion: sigue reintentando
    # (y por eso las esperas crecen). Si se hubiera muerto, habria una sola.
    r.check("las esperas crecen (sigue reintentando)", waits == [1.0, 2.0, 3.0], waits)
    r.check("y el hilo termina al pararlo", not alive)
    return r.failures


def test_restore_falla_visible():
    print("19) si el restore falla, queda en el log (no muere en silencio)")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    logs = []
    r.engine.log = logs.append

    def proveedor_falla():
        raise RuntimeError("sin sink")

    r.engine._sink_provider = proveedor_falla
    r.engine._restore_volume_delayed(40)
    esperar(lambda: any("No se pudo restaurar" in m for m in logs), timeout=5.0)
    r.check(
        "queda anotado en el log",
        any("No se pudo restaurar el volumen a 40%" in m for m in logs),
        logs,
    )
    return r.failures


def test_no_se_pisan_las_reglas_del_fichero():
    print("20) al guardar no se pisan las reglas del fichero")
    import json

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    path = "/tmp/cmf-buds-test-fichero.json"
    r.engine.rules_path = path
    r.engine._rules_mtime = 0.0
    # Alguien anade una regla al fichero a mano, fuera del panel.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            '{"rules": [%s, %s]}'
            % (
                _json_rule("a", "volume_up", 0, "super", "UNO"),
                _json_rule("manual", "volume_down", 0, "super", "MANUAL"),
            )
        )
    # El panel anade otra regla: no se puede perder la del fichero.
    r.engine.upsert(rule("nueva", "volume_up", 0, "super", "NUEVA"))
    with open(path, "r", encoding="utf-8") as fh:
        ids = [x["id"] for x in json.load(fh)["rules"]]
    r.check("la regla del fichero sigue ahi", "manual" in ids, ids)
    r.check("y se ha anadido la nueva", "nueva" in ids, ids)
    r.check(
        "el panel ve las reglas del fichero",
        "manual" in [x["id"] for x in r.engine.snapshot()["rules"]],
    )
    if os.path.exists(path):
        os.unlink(path)
    return r.failures


def test_gesto_no_se_pierde():
    print("21) si el cierre del gesto falla, queda en el log")
    # Con una regla de 3 pulsaciones, un solo pinchazo NO dispara nada: la
    # accion se decide al cerrar el gesto (el temporizador que lo dispara).
    r = Runner([
        rule("any", "volume_up", 0, "super", "CUALQUIERA"),
        rule("tres", "volume_up", 3, "super", "TRES"),
    ])
    logs = []
    r.engine.log = logs.append

    def falla():
        raise RuntimeError("fallo simulado")

    # Se rompe a proposito el cierre del gesto: si no esta protegido, el
    # hilo del temporizador muere y el gesto se pierde sin que nadie se entere.
    r.engine._fire_gesture = falla
    r.evento(60, ["super"])
    esperar(lambda: any("No se pudo cerrar el gesto" in m for m in logs), timeout=5.0)
    r.check(
        "queda anotado en el log",
        any("No se pudo cerrar el gesto" in m for m in logs),
        logs,
    )
    r.check("el gesto no se ejecuto", r.engine.fired == [], r.engine.fired)
    # Y el motor sigue funcionando: se restituye el cierre y otro gesto va bien.
    r.engine._fire_gesture = LocalActionEngine._fire_gesture.__get__(r.engine)
    r.engine.fired.clear()
    r.evento(70, ["super"])
    esperar(lambda: r.engine.fired == [], timeout=0.5)
    time.sleep(1.2)
    r.check("el motor sigue vivo", r.engine.fired == ["CUALQUIERA"], r.engine.fired)
    return r.failures


def test_lector_cierra_el_socket():
    print("22) el lector cierra el socket al morir (el descriptor no se fuga)")
    import socket as _socket

    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    a, b = _socket.socketpair()
    link = budsctl.BudsLink("00:00:00:00:00:00")
    link.sock = a
    link.running = True
    logs = []
    link.log = logs.append
    original = budsctl.parse_frames

    def falla(buf):
        raise RuntimeError("fallo simulado")

    budsctl.parse_frames = falla
    b.sendall(b"\x99\x99\x99\x99")
    try:
        link._read_loop()
    finally:
        budsctl.parse_frames = original
    r.check("el socket queda cerrado", a.fileno() == -1, a.fileno())
    r.check("el enlace queda desconectado", not link.connected)
    r.check(
        "queda anotado en el log",
        any("Error inesperado en el lector" in m for m in logs),
        logs,
    )
    b.close()
    return r.failures


def test_reconectar_cierra_el_enlace_anterior():
    print("23) al reconectar se cierra el enlace anterior (su socket no queda vivo)")
    import socket as _socket

    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    a, b = _socket.socketpair()
    anterior = budsctl.BudsLink("00:00:00:00:00:00")
    anterior.sock = a
    anterior.connected = True
    budsctl.BudsDaemon._cerrar_enlace_anterior(anterior)
    r.check("el socket del enlace anterior queda cerrado", a.fileno() == -1, a.fileno())
    r.check("el enlace anterior queda desconectado", not anterior.connected)
    r.check("no se conecta con un enlace nulo", budsctl.BudsDaemon._cerrar_enlace_anterior(None) is None)
    b.close()
    return r.failures


def test_tramas_rfcmm():
    print("24) las tramas se construyen, se parsean y la basura no revienta")
    import random

    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    payload = b"\x01\x02\x03"
    frame = budsctl.build_frame(0xC001, payload, 7)
    frames, resto = budsctl.parse_frames(frame)
    r.check("la trama se parsea", len(frames) == 1, frames)
    r.check("el payload es correcto", bool(frames) and frames[0][1] == payload, frames)
    r.check("no queda resto", resto == b"", resto)
    r.check(
        "el CRC de la trama es el calculado",
        frame[-2:] == budsctl.struct.pack("<H", budsctl.crc16(frame[:-2])),
    )
    basura = bytes(random.randrange(256) for _ in range(64))
    try:
        frames2, resto2 = budsctl.parse_frames(basura)
        ok = isinstance(frames2, list) and isinstance(resto2, bytes)
    except Exception as exc:
        ok = False
        frames2 = exc
    r.check("la basura no revienta", ok, frames2)
    medio = frame[:5]
    frames3, resto3 = budsctl.parse_frames(medio)
    r.check(
        "una trama incompleta espera mas datos",
        frames3 == [] and resto3 == medio,
        (frames3, resto3),
    )
    r.check(
        "el buffer se acota (no crece sin limite)",
        budsctl._acotar_buffer(b"x" * (budsctl.MAX_BUFFER + 1)) == b"",
    )
    r.check(
        "un buffer normal se respeta",
        budsctl._acotar_buffer(b"x" * 10) == b"x" * 10,
    )
    return r.failures


def test_ecodec_y_modelo():
    print("25) el codec de floats del ecualizador y la deteccion de modelo")
    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    for valor in (0.0, 1.0, -1.0, 0.5, 12.0, -7.25):
        codificado = budsctl.eq_float_encode(valor)
        recuperado = budsctl.eq_float_decode(codificado)
        r.check(
            "el float %s hace ida y vuelta" % valor,
            abs(recuperado - valor) < 1e-6,
            (valor, recuperado),
        )
    r.check(
        "el preamp tiene su codificacion propia",
        budsctl.eq_float_encode(0.0, preamp=True) == bytes([0x00, 0x00, 0x00, 0x80]),
    )
    r.check(
        "decodificar basura no revienta",
        budsctl.eq_float_decode(b"") == 0.0 and budsctl.eq_float_decode(b"x") == 0.0,
    )
    r.check(
        "el modelo se detecta por el nombre",
        budsctl.model_from_name("CMF Buds Pro 2") == "B172"
        and budsctl.model_from_name("cmf buds 2 plus") == "B171"
        and budsctl.model_from_name("CMF Buds 2") == "B168"
        and budsctl.model_from_name("CMF Buds") == "B168",
    )
    r.check(
        "un nombre desconocido no da modelo",
        budsctl.model_from_name("otra cosa") is None
        and budsctl.model_from_name(None) is None
        and budsctl.model_from_name("") is None,
    )
    r.check(
        "el modelo se detecta por el numero de serie",
        budsctl.model_from_serial("1234769999") == "B172"
        and budsctl.model_from_serial("1234") is None
        and budsctl.model_from_serial(None) is None,
    )
    return r.failures


def test_codigos_de_modificadores():
    print("26) los codigos de tecla se traducen al modificador correcto")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    esperados = {
        125: "super",   # KEY_LEFTMETA
        126: "super",   # KEY_RIGHTMETA
        29: "ctrl",     # KEY_LEFTCTRL
        97: "ctrl",     # KEY_RIGHTCTRL
        56: "alt",      # KEY_LEFTALT
        100: "alt",     # KEY_RIGHTALT
        42: "shift",    # KEY_LEFTSHIFT
        54: "shift",    # KEY_RIGHTSHIFT
    }
    for codigo, nombre in esperados.items():
        r.check(
            "el codigo %d es %s" % (codigo, nombre),
            local_actions._modifier_de_evento(1, codigo) == nombre,
            local_actions._modifier_de_evento(1, codigo),
        )
    r.check(
        "una tecla normal no es modificador",
        local_actions._modifier_de_evento(1, 30) is None,
    )
    r.check(
        "un evento que no es de teclado no es modificador",
        local_actions._modifier_de_evento(0, 125) is None
        and local_actions._modifier_de_evento(2, 125) is None,
    )
    # Los nombres que usa el motor son los mismos que los de las reglas:
    # si no, las reglas que exigen SUPER no se dispararian nunca.
    r.check(
        "los nombres del motor coinciden con los de las reglas",
        set(local_actions.MODIFIER_CODES.values()) == {"super", "ctrl", "alt", "shift"},
    )
    return r.failures


def test_aviso_del_atajo():
    print("27) el aviso del atajo se lanza y, si falla, queda en el log")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.engine.rules[0]["notify"] = True
    logs = []
    r.engine.log = logs.append
    llamadas = []
    original = local_actions.subprocess.Popen

    def fake_popen(cmd, *args, **kwargs):
        llamadas.append(cmd)
        return None

    local_actions.subprocess.Popen = fake_popen
    try:
        r.evento(60, ["super"])
        time.sleep(0.3)
    finally:
        local_actions.subprocess.Popen = original
    r.check(
        "se avisa con notify-send",
        any(isinstance(c, list) and c and c[0] == "notify-send" for c in llamadas),
        llamadas,
    )
    r.check("el atajo se ejecuto", r.engine.fired == ["UNO"], r.engine.fired)

    # Y si el aviso falla, no se pierde en silencio. Antes hay que dejar
    # pasar la ventana del gesto, si no el segundo pinchazo forma parte del
    # primero y no vuelve a dispararse.
    r.calmarse()
    logs.clear()
    r.engine.log = logs.append

    def falla(*args, **kwargs):
        raise OSError("sin notify-send")

    local_actions.subprocess.Popen = falla
    try:
        r.evento(70, ["super"])
        time.sleep(0.3)
    finally:
        local_actions.subprocess.Popen = original
    r.check(
        "el fallo del aviso queda anotado",
        any("No se pudo mostrar el aviso" in m for m in logs),
        logs,
    )
    return r.failures


def test_contrato_luau_motor():
    print("28) la UI y el motor usan los mismos nombres")
    import re
    import tomllib

    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def lista_de(texto, nombre):
        m = re.search(r"local %s = \{([^}]*)\}" % nombre, texto)
        if m is None:
            return None
        return re.findall(r'"([^"]+)"', m.group(1))

    with open(os.path.join(raiz, "lib", "panel_ui.luau"), encoding="utf-8") as fh:
        ui = fh.read()
    with open(os.path.join(raiz, "lib", "common.luau"), encoding="utf-8") as fh:
        comun = fh.read()
    with open(os.path.join(raiz, "plugin.toml"), "rb") as fh:
        manifiesto = tomllib.load(fh)

    modificadores_ui = lista_de(ui, "MODIFIERS")
    r.check(
        "los modificadores de la UI son los que el motor entiende",
        set(modificadores_ui or []) == set(local_actions.MODIFIER_CODES.values()) | {"none", "no_super"},
        modificadores_ui,
    )
    disparadores_ui = lista_de(ui, "TRIGGERS")
    r.check(
        "los disparadores de la UI son los del motor",
        tuple(disparadores_ui or []) == tuple(local_actions.TRIGGERS),
        (disparadores_ui, local_actions.TRIGGERS),
    )
    nombres_ui = lista_de(ui, "TRIGGER_NAMES")
    r.check(
        "todos los disparadores tienen nombre en la UI",
        set(disparadores_ui or []) >= set(local_actions.TRIGGERS),
        nombres_ui,
    )
    import budsctl as _budsctl

    niveles_ui = set(re.findall(r'level == "(\w+)"', ui))
    r.check(
        "los niveles de ANC de la UI son los del demonio",
        niveles_ui == set(_budsctl.ANC_LEVELS),
        (sorted(niveles_ui), sorted(_budsctl.ANC_LEVELS)),
    )
    paneles_ui = re.findall(r'(\w+) = "(faminec/cmf-buds:panel-[\w-]+)"', comun)
    paneles_manifiesto = {p["id"] for p in manifiesto["panel"]}
    r.check(
        "los paneles de la UI son los del manifiesto",
        {v for k, v in paneles_ui} == {"faminec/cmf-buds:" + p for p in paneles_manifiesto},
        (paneles_ui, paneles_manifiesto),
    )
    return r.failures


def _acciones_permitidas_luau(texto):
    """Extrae del Luau {grupo: {gesto: [acciones]}}."""
    bloque = re.search(r"local ACTION_ALLOWED = \{(.*?)\n\}", texto, re.S)
    if bloque is None:
        return None
    salida = {}
    grupo = None
    for linea in bloque.group(1).splitlines():
        m = re.match(r"\s*(\w+) = \{(.*)$", linea)
        if m is None:
            continue
        nombre, resto = m.group(1), m.group(2)
        if resto.strip() in ("", "}"):
            # Linea de grupo: abre una tabla de gestos.
            grupo = nombre
            salida[grupo] = {}
        elif grupo is not None:
            salida[grupo][nombre] = re.findall(r'"([^"]+)"', resto)
    return salida


def test_gestos_permitidos():
    print("29) la lista de acciones permitidas es la misma en la UI y en el demonio")
    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(raiz, "lib", "common.luau"), encoding="utf-8") as fh:
        comun = fh.read()
    ui = _acciones_permitidas_luau(comun)
    r.check("se pudo leer la lista de la UI", ui is not None and len(ui) > 0, ui)
    # El demonio indexa por (grupo, gesto); se reagrupa para comparar.
    demonio = {}
    for (grupo, gesto), acciones in budsctl.GESTURE_ALLOWED.items():
        demonio.setdefault(grupo, {})[gesto] = set(acciones)
    r.check(
        "los grupos son los mismos",
        set(ui or {}) == set(demonio),
        (sorted((ui or {}).keys()), sorted(demonio.keys())),
    )
    diferencias = []
    for grupo, gestos in (ui or {}).items():
        for gesto, acciones in gestos.items():
            otras = set(demonio.get(grupo, {}).get(gesto, []))
            if set(acciones) != otras:
                diferencias.append((grupo, gesto, sorted(set(acciones) ^ otras)))
    r.check(
        "las acciones permitidas son las mismas en los dos sitios",
        not diferencias,
        diferencias,
    )
    # Y el demonio no acepta una accion no permitida para ese gesto.
    permitidas = budsctl.GESTURE_ALLOWED[("left", "double")]
    no_permitida = next(
        (a for a in budsctl.GESTURE_ACTIONS if a not in permitidas),
        None,
    )
    r.check(
        "el demonio rechaza una accion no permitida para ese gesto",
        no_permitida is not None,
        permitidas,
    )
    error = None
    try:
        budsctl.BudsDaemon._comprobar_gesture("left", "double", no_permitida)
    except ValueError as exc:
        error = str(exc)
    r.check("y avisa del motivo", error is not None and "no est" in error, error)
    error2 = None
    try:
        budsctl.BudsDaemon._comprobar_gesture("left", "double", "play_pause")
    except ValueError as exc:
        error2 = str(exc)
    r.check("una accion permitida pasa", error2 is None, error2)
    error3 = None
    try:
        budsctl.BudsDaemon._comprobar_gesture("left", "inventado", "play_pause")
    except ValueError as exc:
        error3 = str(exc)
    r.check("un gesto inexistente se rechaza", error3 is not None, error3)
    # El nivel de ANC invalido tambien se rechaza (antes caia a "strong" en
    # silencio y el estado guardaba el nivel invalido).
    exc4 = None
    try:
        budsctl.BudsDaemon._comprobar_anc("anc", "inventado")
    except Exception as exc:
        exc4 = exc
    r.check(
        "un nivel de ANC invalido se rechaza con un error claro",
        isinstance(exc4, ValueError) and "nivel" in str(exc4),
        exc4,
    )
    r.check(
        "un nivel de ANC valido se acepta",
        budsctl.BudsDaemon._comprobar_anc("anc", "high") is not None
        and budsctl.BudsDaemon._comprobar_anc("off") is not None
        and budsctl.BudsDaemon._comprobar_anc("transparency") is not None,
    )
    error5 = None
    try:
        budsctl.BudsDaemon._comprobar_anc("inventado")
    except ValueError as exc:
        error5 = str(exc)
    r.check("un modo de ANC invalido se rechaza", error5 is not None, error5)
    return r.failures


def test_ajustes_invalidos():
    print("30) los ajustes invalidos se rechazan, no se cambian en silencio")
    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    exc = None
    try:
        budsctl.BudsDaemon._comprobar_lado("centro")
    except Exception as e:
        exc = e
    r.check("un lado inválido se rechaza", isinstance(exc, ValueError), exc)
    r.check(
        "los lados validos se aceptan",
        budsctl.BudsDaemon._comprobar_lado("left") == 0x02
        and budsctl.BudsDaemon._comprobar_lado("right") == 0x03,
    )
    # El volumen se recorta antes de marcarlo como nuestro cambio: si se
    # marcara el valor sin recortar, no coincidiria con el volumen real y el
    # motor creeria que el cambio era un gesto del usuario.
    import inspect

    fuente = inspect.getsource(budsctl.BudsDaemon.set_volume)
    r.check(
        "el cambio se marca con el volumen ya recortado",
        "note_self_change(pct)" in fuente
        and "note_self_change(percent)" not in fuente,
        fuente,
    )
    return r.failures


def test_apagado_de_anillos():
    print("31) el anillo que no se puede apagar se reintenta")
    import budsctl

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    demonio = budsctl.BudsDaemon.__new__(budsctl.BudsDaemon)
    demonio.ring_until = {"left": 10.0, "right": 0}
    intentos = []

    def falla(side, enabled):
        intentos.append((side, enabled))
        raise RuntimeError("sin enlace")

    demonio.ring = falla
    demonio._apagar_anillos(100.0)
    r.check("se intenta apagar el anillo que toca", intentos == [("left", False)], intentos)
    r.check(
        "si falla, no se da por apagado (se reintentara)",
        demonio.ring_until.get("left") == 10.0,
        demonio.ring_until,
    )
    r.check("el que no tocaba se queda igual", demonio.ring_until.get("right") == 0)
    # Si funciona, se marca como apagado.
    demonio.ring_until = {"left": 10.0}
    demonio.ring = lambda side, enabled: intentos.append((side, enabled))
    demonio._apagar_anillos(100.0)
    r.check("si funciona, se marca como apagado", demonio.ring_until.get("left") == 0, demonio.ring_until)
    return r.failures


def test_la_marca_caduca():
    print("32) la marca de cambio nuestro caduca (no se traga un gesto posterior)")
    import local_actions

    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    e = r.engine
    e.modifiers.held = {"super"}
    # 1) El eco del dispositivo (el mismo valor) se ignora siempre.
    e.note_self_change(40)
    e.volume = 40
    e._on_volume_change("fake")
    time.sleep(0.3)
    r.check("el eco del dispositivo se ignora", e.fired == [], e.fired)

    # 2) Dentro del plazo, un +1 del usuario cae en la tolerancia del eco y
    # se confunde con el: el gesto se pierde.
    e.fired.clear()
    e.note_self_change(40)
    e.volume = 41
    e._on_volume_change("fake")
    time.sleep(0.3)
    r.check("dentro del plazo, un +1 se confunde con el eco", e.fired == [], e.fired)

    # 3) Pasado el plazo, un +1 ya es un gesto del usuario y no se traga.
    e.fired.clear()
    e.note_self_change(40)
    time.sleep(local_actions.SELF_CHANGE_TTL + 0.4)
    e.volume = 41
    e._on_volume_change("fake")
    time.sleep(0.3)
    r.check("un gesto posterior no se traga", e.fired == ["UNO"], e.fired)
    return r.failures


def test_recarga():
    print("7) las reglas editadas fuera del panel se recargan")
    path = "/tmp/cmf-buds-test-rules.json"
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    r.engine.rules_path = path
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"rules": [%s]}' % _json_rule("b", "volume_up", 0, "super", "DESDE_FICHERO"))
    r.evento(60, ["super"])
    time.sleep(0.2)
    r.check("usa la regla del fichero", r.engine.fired == ["DESDE_FICHERO"], r.engine.fired)
    if os.path.exists(path):
        os.unlink(path)
    return r.failures


def _json_rule(rid, trigger, presses, modifier, command):
    import json

    return json.dumps(rule(rid, trigger, presses, modifier, command))


def main():
    print("Pruebas del motor de atajos locales\n")
    total = 0
    for test in (
        test_regla_cualquiera_sola,
        test_contador_manda,
        test_modificadores_distintos,
        test_especificidad,
        test_comando_vacio,
        test_rafaga,
        test_recarga,
        test_gesto_despues_de_restaurar,
        test_pinchazos_muy_juntos,
        test_cambio_propio_por_valor,
        test_gestos_separados,
        test_regla_malformada,
        test_watcher_sobrevive,
        test_watcher_sin_suscripcion,
        test_espera_creciente,
        test_contador_se_reinicia,
        test_suscripcion_corta,
        test_watcher_resolutor_falla,
        test_restore_falla_visible,
        test_no_se_pisan_las_reglas_del_fichero,
        test_gesto_no_se_pierde,
        test_lector_cierra_el_socket,
        test_reconectar_cierra_el_enlace_anterior,
        test_tramas_rfcmm,
        test_ecodec_y_modelo,
        test_codigos_de_modificadores,
        test_aviso_del_atajo,
        test_contrato_luau_motor,
        test_gestos_permitidos,
        test_ajustes_invalidos,
        test_apagado_de_anillos,
        test_la_marca_caduca,
    ):
        total += test()
    print("")
    if total:
        print("%d FALLOS" % total)
        return 1
    print("Todo correcto")
    return 0

if __name__ == "__main__":
    sys.exit(main())
