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
    time.sleep(1.2)
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
