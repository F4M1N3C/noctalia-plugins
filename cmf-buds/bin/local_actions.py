"""Acciones locales para los CMF Buds.

Los auriculares no guardan comandos arbitrarios: el firmware solo acepta una
lista fija de acciones (reproducir, siguiente, volumen, ANC...). Lo que llega
al PC es la *accion resultante*, no la pulsacion cruda.

Por eso las macros se construyen en el PC:

* El daemon vigila el sink de los auriculares con ``pactl subscribe``. Cuando
  la accion elegida en el auricular es "volumen +/-" (por ejemplo el triple
  toque del boton del estuche), el PC recibe la tecla AVRCP y el volumen del
  sink cambia solo -> ese cambio es la senal.
* Se agrupan las senales en multitactiles (doble, triple...) con una ventana
  de tiempo.
* Se consulta el estado de los modificadores (SUPER, CTRL, ALT, SHIFT) leyendo
  /dev/input/event* directamente, para poder exigir "SUPER mantenido".
* Si hay una regla que encaja, se ejecuta el comando local.
"""

from __future__ import annotations

import json
import os
import re
import select
import struct
import subprocess
import threading
import time

# Ventana para agrupar varias pulsaciones en una (multitactil).
GROUP_WINDOW = 0.7
# Dos senales mas juntas que esto cuentan como la misma pulsacion.
REPEAT_GAP = 0.12
# Ignorar cambios de volumen provocados por nosotros mismos.
SELF_CHANGE_GRACE = 1.0
# Separacion minima entre dos eventos del mismo tipo (evita dobles).
EVENT_GAP = 0.2

MODIFIER_CODES = {
    125: "super",
    126: "super",
    29: "ctrl",
    97: "ctrl",
    56: "alt",
    100: "alt",
    42: "shift",
    54: "shift",
}

MODIFIER_LABELS = {
    "super": "SUPER",
    "ctrl": "CTRL",
    "alt": "ALT",
    "shift": "SHIFT",
}

# Tamano de struct input_event en Linux x86_64: timeval(16) + u16 + u16 + s32
INPUT_EVENT_SIZE = 24
INPUT_EVENT_FORMAT = "llHHi"


def _run(cmd, timeout=6):
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
        )
    except Exception:
        return None


def _list_event_devices():
    try:
        return [
            os.path.join("/dev/input", name)
            for name in os.listdir("/dev/input")
            if name.startswith("event")
        ]
    except Exception:
        return []


class ModifierTracker:
    """Estado de los modificadores del teclado leido de /dev/input/event*."""

    def __init__(self):
        self.held = set()
        self.available = False
        self._fds = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        for fd in list(self._fds.keys()):
            try:
                os.close(fd)
            except Exception:
                pass
        self._fds.clear()

    def modifiers(self):
        with self._lock:
            return sorted(self.held)

    def is_held(self, name):
        with self._lock:
            return name in self.held

    def _open_devices(self):
        for path in sorted(_list_event_devices()):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except Exception:
                continue
            self._fds[fd] = path
        self.available = bool(self._fds)

    def _loop(self):
        self._open_devices()
        if not self._fds:
            return
        buf_size = INPUT_EVENT_SIZE
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select(list(self._fds.keys()), [], [], 0.5)
            except Exception:
                break
            for fd in ready:
                try:
                    data = os.read(fd, buf_size * 32)
                except Exception:
                    continue
                for off in range(0, len(data) - buf_size + 1, buf_size):
                    try:
                        _, _, etype, code, value = struct.unpack(
                            INPUT_EVENT_FORMAT, data[off : off + buf_size]
                        )
                    except Exception:
                        continue
                    if etype != 1:  # EV_KEY
                        continue
                    name = MODIFIER_CODES.get(code)
                    if not name:
                        continue
                    with self._lock:
                        if value == 1:
                            self.held.add(name)
                        elif value == 0:
                            self.held.discard(name)


class VolumeWatcher:
    """Detecta cambios de volumen del sink de los auriculares."""

    def __init__(self, sink_resolver, on_change):
        self.sink_resolver = sink_resolver
        self.on_change = on_change
        self._proc = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        proc = self._proc
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

    def _sink_id(self, sink):
        res = _run(["pactl", "list", "sinks", "short"], 6)
        if not res:
            return None
        for line in (res.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == sink:
                return parts[0].strip()
        return None

    def _loop(self):
        while not self._stop.is_set():
            sink = self.sink_resolver()
            if not sink:
                self._stop.wait(2.0)
                continue
            sink_id = self._sink_id(sink)
            try:
                self._proc = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except Exception:
                self._stop.wait(3.0)
                continue
            pattern = re.compile(r"Event 'change' on sink #(\d+)")
            try:
                for line in self._proc.stdout:
                    if self._stop.is_set():
                        break
                    match = pattern.search(line or "")
                    if not match:
                        continue
                    if sink_id and match.group(1) != sink_id:
                        continue
                    self.on_change(sink)
            except Exception:
                pass
            finally:
                try:
                    if self._proc:
                        self._proc.kill()
                except Exception:
                    pass
                self._proc = None
            if not self._stop.is_set():
                self._stop.wait(1.0)


class LocalActionEngine:
    """Reglas de atajo: senal de los auriculares + modificadores -> comando."""

    def __init__(self, data_dir, log=None, notify=True):
        self.data_dir = data_dir
        self.rules_path = os.path.join(data_dir, "local_actions.json")
        self.log = log or (lambda msg: None)
        self.notify_enabled = notify
        self.rules = []
        self.last = {}
        self._pending = None
        self._timer = None
        self._lock = threading.RLock()
        self._self_change_at = 0.0
        self._last_event = {}
        self._last_fire = {}
        self.modifiers = ModifierTracker()
        self.watcher = None
        self._sink_provider = None
        self._last_volume = None

    # -- persistencia --------------------------------------------------------
    def load(self):
        try:
            with open(self.rules_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.rules = data.get("rules", []) if isinstance(data, dict) else []
        except Exception:
            self.rules = []
        return self.rules

    def save(self):
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.rules_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"rules": self.rules}, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.rules_path)

    def set_rules(self, rules):
        with self._lock:
            self.rules = rules or []
            self.save()
        return self.rules

    def upsert(self, rule):
        with self._lock:
            rid = str(rule.get("id") or "")
            if not rid:
                rid = "r%d" % (int(time.time() * 1000) % 10000000)
                rule["id"] = rid
            found = False
            for idx, existing in enumerate(self.rules):
                if str(existing.get("id")) == rid:
                    self.rules[idx] = rule
                    found = True
                    break
            if not found:
                self.rules.append(rule)
            self.save()
        return rule

    def delete(self, rid):
        with self._lock:
            self.rules = [r for r in self.rules if str(r.get("id")) != str(rid)]
            self.save()
        return self.rules

    # -- arranque ------------------------------------------------------------
    def start(self, sink_provider):
        self._sink_provider = sink_provider
        self.load()
        self.modifiers.start()
        self.watcher = VolumeWatcher(sink_provider, self._on_volume_change)
        self.watcher.start()
        self.log("Motor de acciones locales activo")

    def stop(self):
        if self._timer:
            try:
                self._timer.cancel()
            except Exception:
                pass
        if self.watcher:
            self.watcher.stop()
        self.modifiers.stop()

    # -- volumen -------------------------------------------------------------
    def note_self_change(self):
        self._self_change_at = time.time()

    def _read_volume(self, sink):
        res = _run(["pactl", "get-sink-volume", sink], 6)
        if not res:
            return None
        for token in (res.stdout or "").split():
            if token.endswith("%"):
                try:
                    return int(float(token.rstrip("%")))
                except ValueError:
                    return None
        return None

    def _on_volume_change(self, sink):
        if time.time() - self._self_change_at < SELF_CHANGE_GRACE:
            self._last_volume = self._read_volume(sink)
            return
        value = self._read_volume(sink)
        if value is None:
            return
        previous = self._last_volume
        self._last_volume = value
        if previous is None:
            return
        delta = value - previous
        if delta == 0:
            return
        self._register("volume_up" if delta > 0 else "volume_down", sink, previous)

    # -- agrupacion de pulsaciones -----------------------------------------
    def _register(self, trigger, sink=None, previous_volume=None):
        now = time.time()
        with self._lock:
            # Una misma tecla puede generar varios eventos: ignorar repetidos.
            if now - self._last_event.get(trigger, 0.0) < EVENT_GAP:
                return
            self._last_event[trigger] = now
            modifiers = self.modifiers.modifiers()
            # Reglas "cualquier numero de pulsaciones": se ejecutan al instante.
            any_rule = self._matching_rule(trigger, 0, modifiers, True)
            if any_rule is not None:
                if now - self._last_fire.get(trigger, 0.0) >= EVENT_GAP:
                    self._last_fire[trigger] = now
                    self._run_rule(any_rule, trigger, 1, modifiers, previous_volume)
                return
            pending = self._pending
            if (
                pending
                and pending["trigger"] == trigger
                and now - pending["last"] <= REPEAT_GAP
            ):
                # repeticion de la misma tecla: no cuenta como pulsacion nueva
                return
            if (
                pending
                and pending["trigger"] == trigger
                and now - pending["last"] <= GROUP_WINDOW
            ):
                pending["count"] += 1
                pending["last"] = now
            else:
                pending = {
                    "trigger": trigger,
                    "count": 1,
                    "first": now,
                    "last": now,
                    "volume": self._read_volume(sink) if sink else None,
                }
                self._pending = pending
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
            self._timer = threading.Timer(GROUP_WINDOW, self._fire)
            self._timer.daemon = True
            self._timer.start()

    # -- ejecucion -----------------------------------------------------------
    def _matching_rule(self, trigger, count, modifiers, any_ok=False):
        candidates = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("trigger") != trigger:
                continue
            presses = int(rule.get("presses", 1))
            if presses == 0:
                if not any_ok:
                    continue
            elif presses != count:
                continue
            require = [m for m in rule.get("require", []) if m]
            forbid = [m for m in rule.get("forbid", []) if m]
            if any(m not in modifiers for m in require):
                continue
            if any(m in modifiers for m in forbid):
                continue
            candidates.append((len(require), rule))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _fire(self):
        with self._lock:
            pending = self._pending
            self._pending = None
        if not pending:
            return
        modifiers = self.modifiers.modifiers()
        rule = self._matching_rule(pending["trigger"], pending["count"], modifiers)
        if rule is None:
            self.last = {
                "trigger": pending["trigger"],
                "presses": pending["count"],
                "modifiers": modifiers,
                "at": int(time.time() * 1000),
                "command": None,
                "ran": False,
            }
            return
        self._run_rule(rule, pending["trigger"], pending["count"], modifiers, pending.get("volume"))

    def _run_rule(self, rule, trigger, count, modifiers, previous_volume):
        command = (rule.get("command") or "").strip()
        info = {
            "trigger": trigger,
            "presses": count,
            "modifiers": modifiers,
            "at": int(time.time() * 1000),
            "command": command,
            "rule_id": rule.get("id"),
            "ran": False,
        }
        if command:
            self.run_command(command)
            info["ran"] = True
        if rule.get("restore_volume") and previous_volume is not None:
            self._restore_volume(previous_volume)
        self.last = info
        self.log(
            "Accion local: "
            + ", ".join([trigger, "x%d" % count] + modifiers)
            + " -> "
            + (command or "(sin comando)")
        )
        if rule.get("notify", True) and command:
            self._notify(info, command)

    def _restore_volume(self, percent):
        if not self._sink_provider:
            return
        sink = self._sink_provider()
        if not sink:
            return
        self.note_self_change()
        _run(["pactl", "set-sink-volume", sink, "%d%%" % int(percent)], 6)

    def run_command(self, command):
        try:
            subprocess.Popen(
                ["/bin/sh", "-c", command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception as exc:
            self.log("No se pudo ejecutar '%s': %s" % (command, exc))
            return False

    def _notify(self, info, command):
        mods = " + ".join(MODIFIER_LABELS.get(m, m.upper()) for m in info["modifiers"])
        body = "%s x%d" % (info["trigger"], info["presses"])
        if mods:
            body += " con " + mods
        body += " -> " + command
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "-a",
                    "Noctalia - CMF Buds",
                    "-i",
                    "headphones",
                    "Atajo de los auriculares",
                    body,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass

    # -- estado --------------------------------------------------------------
    def snapshot(self):
        return {
            "rules": list(self.rules),
            "last": self.last,
            "modifiers": self.modifiers.modifiers(),
            "modifiers_available": self.modifiers.available,
        }
