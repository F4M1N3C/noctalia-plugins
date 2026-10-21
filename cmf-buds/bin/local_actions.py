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
# Dos eventos del mismo tipo dentro de esta ventana son el mismo gesto.
GESTURE_WINDOW = 0.5
# Tras disparar un atajo se ignoran los eventos hasta que el volumen se
# estabiliza: al restaurar el volumen, los auriculares devuelven el suyo y
# generan un eco que dispararia el atajo otra vez (workspace +1 y -1).
QUIET_STABLE = 1.2
QUIET_MAX = 6.0
# Margen (%%) para el ajuste final del volumen: si el usuario ha cambiado el
# volumen a proposito durante la ventana de calma, no se toca.
SETTLE_TOLERANCE = 8
# Espera antes de restaurar el volumen: PipeWire aplica el volumen con una
# rampa de ~0.5 s, y un cambio emitido durante la rampa se pierde (el
# destino de la rampa gana). Hay que esperar a que termine.
RESTORE_DELAY = 0.8
# Reintentos del restore si el volumen no se queda donde debe.
RESTORE_ATTEMPTS = 2

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

    def __init__(self, log=None):
        self.held = set()
        self.available = False
        self.log = log or (lambda msg: None)
        self._fds = {}       # fd -> ruta
        self._by_path = {}   # ruta -> fd
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
        self._by_path.clear()

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
            self._by_path[path] = fd
        self.available = bool(self._fds)

    def _refresh_devices(self):
        """Reescanea /dev/input.

        Un nodo puede pasar a apuntar a otro dispositivo (por ejemplo, si se
        reinicia un teclado virtual: el nodo /dev/input/eventN se recrea). Sin
        este refresco, el fd antiguo queda colgado al dispositivo borrado y los
        modificadores dejan de detectarse para siempre.
        """
        paths = _list_event_devices()
        current = set(paths)
        for path in paths:
            fd = self._by_path.get(path)
            if fd is not None:
                try:
                    if os.fstat(fd).st_ino == os.stat(path).st_ino:
                        continue
                except OSError:
                    pass
                # el nodo apunta a otro dispositivo: se reabre
                try:
                    os.close(fd)
                except OSError:
                    pass
                self._fds.pop(fd, None)
                self._by_path.pop(path, None)
            try:
                nfd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._fds[nfd] = path
            self._by_path[path] = nfd
        for fd, path in list(self._fds.items()):
            if path not in current:
                try:
                    os.close(fd)
                except OSError:
                    pass
                self._fds.pop(fd, None)
                self._by_path.pop(path, None)
        self.available = bool(self._fds)

    def _loop(self):
        try:
            self._open_devices()
        except Exception as exc:
            self.log("No se pudieron abrir los dispositivos de entrada: %s" % exc)
            return
        if not self._fds:
            self.log("Sin dispositivos de entrada: no se detectaran modificadores")
            return
        buf_size = INPUT_EVENT_SIZE
        last_refresh = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now - last_refresh > 2.0:
                    last_refresh = now
                    self._refresh_devices()
                ready, _, _ = select.select(list(self._fds.keys()), [], [], 0.5)
                for fd in ready:
                    try:
                        data = os.read(fd, buf_size * 32)
                    except Exception:
                        continue
                    # Solo eventos completos: si sobra un resto, se ignora.
                    usable = len(data) - (len(data) % buf_size)
                    for off in range(0, usable, buf_size):
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
            except Exception as exc:
                # Nunca dejar morir el hilo: si pasara, los modificadores se
                # quedarian congelados y los atajos dejarian de funcionar.
                self.log("Lector de modificadores: %s" % exc)
                time.sleep(0.1)


class VolumeWatcher:
    """Detecta cambios de volumen del sink de los auriculares."""

    def __init__(self, sink_resolver, on_change, log=None):
        self.sink_resolver = sink_resolver
        self.on_change = on_change
        self.log = log or (lambda msg: None)
        self._proc = None
        self._stop = threading.Event()
        self._reported_no_sink = None
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
                # Sin auriculares conectados no hay nada que vigilar: se avisa
                # una sola vez para no llenar el log.
                if self._reported_no_sink != sink:
                    self._reported_no_sink = sink
                    self.log("Watcher: todavia no hay sink de los auriculares")
                self._stop.wait(2.0)
                continue
            sink_id = self._sink_id(sink)
            if self._reported_no_sink is not None:
                self._reported_no_sink = None
            self.log("Watcher: vigilando %s (id %s)" % (sink, sink_id))
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
                        # El sink se recrea cuando los auriculares se
                        # reconectan y cambia su id: se resuelve de nuevo.
                        refreshed = self._sink_id(sink)
                        if not refreshed or refreshed != match.group(1):
                            continue
                        self.log("Watcher: el sink cambio de id a %s" % refreshed)
                        sink_id = refreshed
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
        self.last_event = {}
        self.last_action = {}
        self._pending = None
        self._timer = None
        self._lock = threading.RLock()
        self._self_change_at = 0.0
        self._last_event = {}
        self._last_fire = {}
        self._quiet_until = 0.0
        self._quiet_last_event = 0.0
        self._quiet_started = 0.0
        self._restore_target = None
        self.modifiers = ModifierTracker(self.log)
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
        # Valor inicial: sin esto el primer cambio no tiene con que restaurar.
        try:
            sink = sink_provider()
            if sink:
                self._last_volume = self._read_volume(sink)
        except Exception:
            pass
        self.modifiers.start()
        self.watcher = VolumeWatcher(sink_provider, self._on_volume_change, self.log)
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
        now = time.time()
        if now - self._self_change_at < SELF_CHANGE_GRACE:
            self._last_volume = self._read_volume(sink)
            return
        value = self._read_volume(sink)
        if value is None:
            # El sink ya no existe (auriculares desconectados): sin referencia
            # de volumen no se puede calcular ningun cambio.
            self._last_volume = None
            return
        previous = self._last_volume
        self._last_volume = value
        if previous is None:
            return
        delta = value - previous
        if delta == 0:
            return
        with self._lock:
            # Eco del restore: el auricular devuelve su volumen y genera otro
            # cambio. Mientras siga OSCILANDO se ignoran los eventos; cuando el
            # volumen se calma, los atajos vuelven a armarse.
            if self._quiet_started:
                if (
                    now - self._quiet_last_event >= QUIET_STABLE
                    or now - self._quiet_started >= QUIET_MAX
                ):
                    self._quiet_started = 0.0
                    self._settle_volume()
                else:
                    self._quiet_last_event = now
                    return
        self._register("volume_up" if delta > 0 else "volume_down", sink, previous)

    def _settle_volume(self):
        """Tras el eco, deja el volumen donde estaba antes del gesto."""
        target = self._restore_target
        self._restore_target = None
        if target is None or not self._sink_provider:
            return
        try:
            sink = self._sink_provider()
            if not sink:
                return
            current = self._read_volume(sink)
            if current is None or current == int(target):
                return
            if abs(current - int(target)) > SETTLE_TOLERANCE:
                # Cambio grande: probablemente el usuario, no el eco.
                self.log(
                    "Volumen cambiado por el usuario (%s%% -> %s%%): no se restaura"
                    % (target, current)
                )
                return
            self._restore_volume_delayed(int(target))
        except Exception as exc:
            self.log("No se pudo ajustar el volumen: %s" % exc)

    # -- agrupacion de pulsaciones -----------------------------------------
    def _register(self, trigger, sink=None, previous_volume=None):
        now = time.time()
        with self._lock:
            # Si el eco se ha calmado, volver a armar los atajos.
            if self._quiet_started and (
                now - self._quiet_last_event >= QUIET_STABLE
                or now - self._quiet_started >= QUIET_MAX
            ):
                self._quiet_started = 0.0
                self._settle_volume()
            # Una misma tecla puede generar varios eventos: ignorar repetidos.
            if now - self._last_event.get(trigger, 0.0) < EVENT_GAP:
                return
            self._last_event[trigger] = now
            modifiers = self.modifiers.modifiers()
            # Reglas "cualquier numero de pulsaciones": se ejecutan al instante.
            any_rule = self._matching_rule(trigger, 0, modifiers, True)
            if any_rule is not None and not self._has_counted_rules(trigger):
                # Un gesto = una accion (varias muescas seguidas = una).
                if now - self._last_fire.get(trigger, 0.0) >= GESTURE_WINDOW:
                    self.last_event = {
                        "trigger": trigger,
                        "presses": 1,
                        "modifiers": modifiers,
                        "at": int(time.time() * 1000),
                    }
                    self._last_fire[trigger] = now
                    self._quiet_started = now
                    self._quiet_last_event = now
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
    def _has_counted_rules(self, trigger):
        """True si el gesto tiene alguna regla con un numero de pulsaciones.

        Si las hay, mandan sobre la regla "cualquiera": si no, esta se
        comeria los eventos y la de N pulsaciones nunca llegaria a dispararse.
        """
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("trigger") != trigger:
                continue
            if int(rule.get("presses", 1)) > 0:
                return True
        return False

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
            self.last_event = {
                "trigger": pending["trigger"],
                "presses": pending["count"],
                "modifiers": modifiers,
                "at": int(time.time() * 1000),
            }
            return
        self._run_rule(rule, pending["trigger"], pending["count"], modifiers, pending.get("volume"))

    def _run_rule(self, rule, trigger, count, modifiers, previous_volume):
        command = (rule.get("command") or "").strip()
        if rule.get("restore_volume") and previous_volume is not None:
            self._restore_target = int(previous_volume)
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
            self._restore_volume_delayed(previous_volume)
        self.last_action = info
        self.log(
            "Accion local: %s | %s | mods=%s | vol=%s | -> %s"
            % (
                trigger,
                "x%d" % count,
                "+".join(modifiers) if modifiers else "-",
                self._last_volume,
                command or "(sin comando)",
            )
        )
        if rule.get("notify", True) and command:
            self._notify(info, command)

    def _restore_volume_delayed(self, percent):
        """Restaura el volumen esperando a que termine la rampa de PipeWire y
        comprueba que el valor se quedase; si no, reintenta."""

        def _apply(attempts):
            if not self._sink_provider:
                return
            sink = self._sink_provider()
            if not sink:
                return
            self.note_self_change()
            _run(["pactl", "set-sink-volume", sink, "%d%%" % int(percent)], 6)
            time.sleep(0.3)
            current = self._read_volume(sink)
            self.log(
                "Restore: %d%% -> %s%%" % (int(percent), current)
            )
            if current is None or current == int(percent):
                return
            if attempts > 0:
                self.log(
                    "El volumen no se quedo en %d%% (esta en %s%%): reintento"
                    % (int(percent), current)
                )
                time.sleep(RESTORE_DELAY)
                _apply(attempts - 1)

        timer = threading.Timer(RESTORE_DELAY, _apply, args=(RESTORE_ATTEMPTS,))
        timer.daemon = True
        timer.start()

    def _restore_volume(self, percent):
        if not self._sink_provider:
            return
        sink = self._sink_provider()
        if not sink:
            return
        self.note_self_change()
        res = _run(["pactl", "set-sink-volume", sink, "%d%%" % int(percent)], 6)
        self.log(
            "Restaurando volumen a %d%% en %s (rc=%s)"
            % (int(percent), sink, res.returncode if res else "error")
        )

    def _output_name(self):
        """Nombre del monitor enfocado (para el marcador {output})."""
        res = _run(["hyprctl", "-j", "activeworkspace"], 5)
        if res:
            try:
                data = json.loads(res.stdout or "{}")
                if data.get("monitor"):
                    return str(data["monitor"])
            except Exception:
                pass
        res = _run(["hyprctl", "monitors", "-j"], 5)
        if res:
            try:
                for mon in json.loads(res.stdout or "[]"):
                    if mon.get("focused"):
                        return str(mon.get("name", ""))
            except Exception:
                pass
        return ""

    def run_command(self, command):
        # Se ejecuta en un hilo aparte: el watcher no debe quedarse bloqueado
        # esperando al comando, y asi podemos registrar si falla.
        def _exec():
            try:
                cmd = command
                if "{output}" in cmd:
                    cmd = cmd.replace("{output}", self._output_name())
                res = subprocess.run(
                    ["/bin/sh", "-c", cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                err = (res.stderr or "").strip()
                out = (res.stdout or "").strip()
                self.log(
                    "Comando: %s | rc=%s | out=%s | err=%s"
                    % (cmd, res.returncode, out[:120], err[:200])
                )
            except Exception as exc:
                self.log("No se pudo ejecutar '%s': %s" % (command, exc))

        try:
            threading.Thread(target=_exec, daemon=True).start()
            return True
        except Exception as exc:
            self.log("No se pudo lanzar '%s': %s" % (command, exc))
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
                    # El nombre del tema del sistema es "audio-headphones";
                    # "headphones" no existe y el toast salía sin icono.
                    "audio-headphones",
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
            "last_event": self.last_event,
            "last_action": self.last_action,
            "modifiers": self.modifiers.modifiers(),
            "modifiers_available": self.modifiers.available,
        }
