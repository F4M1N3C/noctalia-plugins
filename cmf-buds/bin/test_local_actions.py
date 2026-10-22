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
    print("13) el watcher sobrevive a un error puntual")
    r = Runner([rule("a", "volume_up", 0, "super", "UNO")])
    calls = {"n": 0}

    def on_change(sink):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo simulado")

    watcher = VolumeWatcher(lambda: "sink-falso", on_change)
    watcher.start()
    time.sleep(0.6)
    alive = watcher._thread.is_alive()
    watcher.stop()
    r.check("el hilo sigue vivo tras el error", alive)
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
    return r.failures
    if os.path.exists(path):
        os.unlink(path)


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
        test_gesto_despues_de_restaurar,
        test_pinchazos_muy_juntos,
        test_cambio_propio_por_valor,
        test_gestos_separados,
        test_regla_malformada,
        test_watcher_sobrevive,
        test_recarga,
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
