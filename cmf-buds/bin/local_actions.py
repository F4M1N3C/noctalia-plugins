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
# (Sin ventana temporal: nuestro cambio de volumen se reconoce por el valor
# que ponemos, no por cuando lo hicimos. Una ventana de tiempo se comia los
# gestos del usuario que llegaban justo despues de restaurar el volumen.)
# Red de seguridad minima contra eventos duplicados. La identidad de un
# evento la da el valor (dos eventos con el mismo volumen son el mismo), asi
# que esta ventana solo tiene que ser mas pequena que el intervalo entre dos
# pinchazos reales (100-250 ms): con 200 ms un triple rapido se contaba como
# un solo gesto; con 60 ms todavia se perdian pinchazos muy juntos.
EVENT_GAP = 0.03
# Tras disparar un atajo se ignoran los eventos hasta que el volumen se
# estabiliza: al restaurar el volumen, los auriculares devuelven el suyo y
# generan un eco que dispararia el atajo otra vez (workspace +1 y -1).
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

# Tiempo que vive la marca de "cambio hecho por nosotros". Solo debe
# absorber el eco del dispositivo: si viviera para siempre, el primer gesto
# del usuario que cayera dentro de +-1 se tragaria.
SELF_CHANGE_TTL = 2.0

# Disparadores que el motor puede generar. La UI usa los mismos nombres:
# si se desincronizasen, las reglas de la UI no se dispararian nunca.
TRIGGERS = ("volume_up", "volume_down")

MODIFIER_LABELS = {
    "super": "SUPER",
    "ctrl": "CTRL",
    "alt": "ALT",
    "shift": "SHIFT",
}

# Tamano de struct input_event en Linux x86_64: timeval(16) + u16 + u16 + s32
INPUT_EVENT_SIZE = 24
INPUT_EVENT_FORMAT = "llHHi"

# Linea de 'pactl subscribe' que avisa de un cambio en un sink.
SINK_EVENT_PATTERN = re.compile(r"Event 'change' on sink #(\d+)")

# Tiempo que una suscripcion debe aguantar sin errores para darse por buena.
# Si se cierra antes, es un fallo mas (si no, se reiniciaria en bucle).
HEALTHY_SECONDS = 5.0


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


def _as_int(value, default=None):
    """Convierte a entero; None si el dato no es un numero valido."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value):
    """Devuelve una lista de modificadores aunque el dato venga raro."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _modifier_de_evento(etype, code):
    """Nombre del modificador de un evento de teclado, o None.

    Aparte para poder comprobarlo: si un codigo se cambiara, las reglas que
    exigen SUPER dejarian de dispararse nunca y no habria ningun error.
    """
    if etype != 1:  # EV_KEY
        return None
    return MODIFIER_CODES.get(code)


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
                self.log("Dispositivo recreado, reabierto: %s" % path)
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
                        name = _modifier_de_evento(etype, code)
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
        self._failures = 0
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

    def _retry_delay(self):
        """Espera antes del siguiente intento.

        Se calcula con el numero de fallos *anteriores*: el primer fallo
        espera 1 s, el segundo 2 s, el tercero 3 s... hasta un tope de 10 s.
        """
        return min(1.0 + self._failures, 10.0)

    def _fail(self, message):
        """Anota un fallo y devuelve cuanto hay que esperar antes de reintentar."""
        delay = self._retry_delay()
        self._failures += 1
        self.log(
            "%s (fallo %d): reintento en %.0f s"
            % (message, self._failures, delay)
        )
        return delay

    def _sink_id(self, sink):
        res = _run(["pactl", "list", "sinks", "short"], 6)
        if not res:
            return None
        for line in (res.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == sink:
                return parts[0].strip()
        return None

    def _handle_line(self, line, sink, sink_id):
        """Procesa una linea de 'pactl subscribe'.

        Devuelve el id del sink vigilado (puede cambiar si los auriculares se
        reconectan). Un error al procesar el evento se registra y no se propaga:
        si se propagara, el hilo del watcher moriria y los atajos dejarian de
        funcionar sin decir nada.
        """
        match = SINK_EVENT_PATTERN.search(line or "")
        if not match:
            return sink_id
        if sink_id and match.group(1) != sink_id:
            # El sink se recrea cuando los auriculares se reconectan y cambia
            # su id: se resuelve de nuevo.
            refreshed = self._sink_id(sink)
            if not refreshed or refreshed != match.group(1):
                return sink_id
            self.log("Watcher: el sink cambio de id a %s" % refreshed)
            sink_id = refreshed
        try:
            self.on_change(sink)
        except Exception as exc:
            self.log("Watcher: error al procesar un cambio: %s" % exc)
        return sink_id

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._watch()
            except Exception as exc:
                # Ninguna excepcion puede matar este hilo: si lo hiciera, los
                # atajos dejarian de funcionar sin decir nada (pasaba con el
                # resolutor del sink, que estaba fuera de cualquier try).
                delay = self._fail("Watcher: error inesperado: %s" % exc)
                self._stop.wait(delay)

    def _watch(self):
        """Una vuelta del watcher.

        Va aparte del bucle para que cualquier excepcion se pueda registrar y
        reintentar, en vez de matar el hilo en silencio.
        """
        sink = self.sink_resolver()
        if not sink:
            # Sin auriculares conectados no hay nada que vigilar: se avisa
            # una sola vez para no llenar el log.
            if self._reported_no_sink != sink:
                self._reported_no_sink = sink
                self.log("Watcher: todavia no hay sink de los auriculares")
            self._stop.wait(2.0)
            return
        sink_id = self._sink_id(sink)
        if self._reported_no_sink is not None:
            self._reported_no_sink = None
        try:
            self._proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            # Sin suscripcion no hay atajos: se avisa y se reintenta con
            # la espera creciente (1 s, 2 s, 3 s... hasta 10 s).
            delay = self._fail(
                "Watcher: no se pudo abrir la suscripcion: %s" % exc
            )
            self._stop.wait(delay)
            return
        self.log("Watcher: vigilando %s (id %s)" % (sink, sink_id))
        started = time.monotonic()
        try:
            for line in self._proc.stdout:
                if self._stop.is_set():
                    break
                sink_id = self._handle_line(line, sink, sink_id)
        except Exception as exc:
            # Un error aqui aborta la suscripcion. Antes se tragaba en
            # silencio y el bucle se reiniciaba una y otra vez: con un
            # fallo persistente los atajos no funcionaban nunca y no
            # habia ni una linea en el log.
            delay = self._fail(
                "Watcher: error en la suscripcion: %s" % exc
            )
        else:
            if self._stop.is_set():
                delay = 0.0
            elif (time.monotonic() - started) < HEALTHY_SECONDS:
                # 'pactl subscribe' se cerraria solo: es un fallo mas, no
                # un reinicio normal (si no, se repetiria en bucle).
                delay = self._fail(
                    "Watcher: la suscripcion se cerro antes de tiempo"
                )
            else:
                # Solo se da por buena si ha aguantado sin errores: aqui
                # se reinicia el contador de fallos y el siguiente reintento
                # vuelve a ser como el primero.
                if self._failures:
                    self.log("Watcher: la suscripcion vuelve a funcionar")
                self._failures = 0
                delay = self._retry_delay()
        finally:
            try:
                if self._proc:
                    self._proc.kill()
            except Exception:
                pass
            self._proc = None
        if not self._stop.is_set():
            self._stop.wait(delay)


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
        self._self_set_volume = None
        self._self_set_at = 0.0
        self._last_event = {}
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
            try:
                self._rules_mtime = os.path.getmtime(self.rules_path)
            except OSError:
                self._rules_mtime = 0.0
        except Exception as exc:
            self.log("No se pudieron leer las reglas: %s" % exc)
            self.rules = []
        return self.rules

    def reload_rules_if_changed(self):
        """Recarga las reglas si el fichero ha cambiado.

        El motor no debe decidir sobre una vista obsoleta: si las reglas se
        editan a mano (o desde otra sesion) fuera del panel, el siguiente
        gesto tiene que usar ya las reglas nuevas.
        """
        try:
            mtime = os.path.getmtime(self.rules_path)
        except OSError:
            return
        if mtime == getattr(self, "_rules_mtime", 0.0):
            return
        before = len(self.rules)
        self.load()
        self.log("Reglas recargadas (%d -> %d)" % (before, len(self.rules)))

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
            # El fichero es la fuente de verdad: si alguien anadio o cambio
            # reglas a mano despues de la ultima recarga, hay que volver a
            # leerlas antes de guardar, o se perderian.
            self.reload_rules_if_changed()
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
            self.reload_rules_if_changed()
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
        except Exception as exc:
            # No es critico (el valor inicial solo sirve de referencia), pero
            # si falla conviene saberlo: sin el, el primer gesto no tendria
            # contra que restaurar el volumen.
            self.log("No se pudo leer el volumen inicial: %s" % exc)
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
    def note_self_change(self, value=None):
        """Marca un cambio de volumen hecho por nosotros.

        Con 'value' se guarda el volumen que hemos puesto: luego se puede
        distinguir nuestro cambio (mismo valor) de un gesto del usuario, sin
        depender de una ventana de tiempo que se comería los gestos.

        Ademas se actualiza la referencia del volumen: si no, el siguiente
        gesto real se calcularia contra una base obsoleta y se dispararia el
        atajo equivocado (o ninguno) sin decir nada.
        """
        if value is not None:
            try:
                self._self_set_volume = int(value)
                self._self_set_at = time.time()
                self._last_volume = self._self_set_volume
            except (TypeError, ValueError):
                pass

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
        value = self._read_volume(sink)
        if value is None:
            # El sink ya no existe (auriculares desconectados): sin referencia
            # de volumen no se puede calcular ningun cambio.
            self._last_volume = None
            return
        previous = self._last_volume
        self._last_volume = value
        if previous is None:
            # Sin referencia no se puede saber cuanto ha cambiado el volumen:
            # se reinicia la referencia y se avisa (no es un gesto).
            if not getattr(self, "_no_baseline_logged", False):
                self._no_baseline_logged = True
                self.log("Sin referencia de volumen: se reinicia la referencia")
            return
        self._no_baseline_logged = False
        delta = value - previous
        if delta == 0:
            return
        if (
            self._self_set_volume is not None
            and (time.time() - self._self_set_at) <= SELF_CHANGE_TTL
            and abs(value - self._self_set_volume) <= 1
        ):
            # Es el valor exacto que pusimos nosotros: se ignora (el evento
            # que genera nuestra propia escritura).
            return
        # Es un cambio de verdad: nuestra marca deja de ser valida.
        self._self_set_volume = None
        self._register(TRIGGERS[0] if delta > 0 else TRIGGERS[1], sink, previous)

    # -- agrupacion de pulsaciones -----------------------------------------
    def _register(self, trigger, sink=None, previous_volume=None):
        now = time.time()
        with self._lock:
            # Una misma tecla puede generar varios eventos: ignorar repetidos.
            if now - self._last_event.get(trigger, 0.0) < EVENT_GAP:
                return
            self._last_event[trigger] = now
            self.reload_rules_if_changed()
            modifiers = self.modifiers.modifiers()

            # Conteo de pulsaciones del gesto en curso. Un gesto nuevo (han
            # pasado GROUP_WINDOW desde la ultima pulsacion) empieza de cero,
            # incluida la marca de "ya disparo".
            pending = self._pending
            if (
                pending
                and pending["trigger"] == trigger
                and now - pending["last"] <= GROUP_WINDOW
            ):
                count = pending["count"] + 1
                first = pending["first"]
                already_fired = pending.get("fired", False)
            else:
                count = 1
                first = now
                already_fired = False
            pending = {
                "trigger": trigger,
                "count": count,
                "first": first,
                "last": now,
                "modifiers": modifiers,
                "volume": self._read_volume(sink) if sink else None,
                "fired": already_fired,
            }
            self._pending = pending

            # Que regla toca con este gesto.
            rules = self._applicable_rules(trigger, modifiers)
            exact = [item for item in rules if item[0] == count]
            fallback = [item for item in rules if item[0] == 0]
            # Una regla de N pulsaciones que aun puede cumplirse hace esperar a
            # la regla "cualquiera": si no, esta se comeria los eventos y la
            # de N pulsaciones no llegaria a dispararse nunca.
            blocking = [item for item in rules if item[0] > count]

            chosen = None
            chosen_presses = 0
            if exact:
                chosen = exact[0][2]
                chosen_presses = exact[0][0]
            elif fallback and not blocking:
                chosen = fallback[0][2]
                chosen_presses = 0

            if chosen is not None:
                # Un gesto = una accion. La regla "cualquiera" dispara al
                # empezar el gesto y el resto de muescas del mismo gesto ya no
                # repiten la accion, sin necesidad de ninguna ventana de
                # tiempo: lo que lo decide es el estado del gesto.
                if pending.get("fired"):
                    return
                pending["fired"] = True
                self.last_event = {
                    "trigger": trigger,
                    "presses": count,
                    "modifiers": modifiers,
                    "at": int(time.time() * 1000),
                }
                self._run_rule(chosen, trigger, count, modifiers, previous_volume)
                return

            if not rules and not getattr(self, "_no_rule_logged", None) == trigger:
                # Habia reglas para este gesto pero ninguna encaja (p.ej. el
                # modificador no esta pulsado): se avisa una vez para que no
                # parezca que los atajos estan rotos.
                self._no_rule_logged = trigger
                self.log(
                    "El gesto %s no encaja con ninguna regla (modificadores: %s)"
                    % (trigger, ",".join(sorted(modifiers)) or "ninguno")
                )
            elif rules:
                self._no_rule_logged = None

            if blocking and not getattr(self, "_shadow_logged", None) == trigger:
                self._shadow_logged = trigger
                self.log(
                    "El gesto %s tiene una regla de %d pulsaciones: la regla "
                    "'cualquiera' espera a que termine el gesto"
                    % (trigger, blocking[0][0])
                )
            elif not blocking:
                self._shadow_logged = None

            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
            self._timer = threading.Timer(GROUP_WINDOW, self._fire)
            self._timer.daemon = True
            self._timer.start()

    # -- evaluacion de reglas ------------------------------------------------
    def _applicable_rules(self, trigger, modifiers):
        """Reglas que pueden aplicarse a este gesto con estos modificadores.

        Cada elemento es (presses, especificidad, regla):
          - presses == 0: regla "cualquiera", que hace de respaldo.
          - presses  > 0: regla de N pulsaciones.

        Se ordenan poniendo delante las de N pulsaciones (y entre ellas, la
        mas especifica) y la de "cualquiera" al final. Todo se evalua contra
        el juego de reglas vigente en cada evento, no contra una vista
        guardada: asi una regla anadida o quitada desde el panel se respeta
        desde el siguiente gesto.
        """
        out = []
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            try:
                if not rule.get("enabled", True):
                    continue
                if rule.get("trigger") != trigger:
                    continue
                require = [m for m in _as_list(rule.get("require")) if m]
                forbid = [m for m in _as_list(rule.get("forbid")) if m]
                presses = _as_int(rule.get("presses"))
                if presses is None or presses < 0:
                    # Regla malformada (editada a mano): se ignora entera, para
                    # que no tape a las reglas bien escritas.
                    self.log(
                        "Regla ignorada por 'presses' invalido: %s"
                        % rule.get("presses")
                    )
                    continue
                for key in ("require", "forbid"):
                    if key in rule and not isinstance(rule[key], (list, tuple)):
                        self.log("Regla ignorada por '%s' invalido" % key)
                        presses = None
                        break
                if presses is None:
                    continue
            except Exception as exc:
                # Una regla malformada (editada a mano) no puede tumbar el
                # motor: se avisa y se sigue con el resto.
                self.log("Regla invalida ignorada: %s" % exc)
                continue
            if any(m not in modifiers for m in require):
                continue
            if any(m in modifiers for m in forbid):
                continue
            out.append((presses, len(require), rule))
        out.sort(key=lambda item: (0 if item[0] > 0 else 1, -item[1], item[0]))
        return out

    def _pick_rule(self, rules, count):
        """Regla que toca para un gesto con 'count' pulsaciones.

        Mandan las de N pulsaciones exactas; si no hay ninguna, se usa la de
        "cualquiera" como respaldo.
        """
        exact = [item for item in rules if item[0] == count]
        if exact:
            return exact[0][2]
        fallback = [item for item in rules if item[0] == 0]
        if fallback:
            return fallback[0][2]
        return None

    def _fire(self):
        """Cierre del gesto: el contador ya no va a crecer.

        Va en un temporizador: si algo falla aqui, el gesto se pierde, y sin
        esta cubierta nadie se enteraria.
        """
        try:
            self._fire_gesture()
        except Exception as exc:
            self.log("No se pudo cerrar el gesto: %s" % exc)

    def _fire_gesture(self):
        with self._lock:
            pending = self._pending
            self._pending = None
        if not pending:
            return
        # Los modificadores del principio del gesto: si el usuario los suelta
        # antes de que se cierre la ventana, la regla sigue acknowledging.
        if pending.get("fired"):
            # El gesto ya disparo su accion: no hay nada mas que hacer.
            return
        modifiers = pending.get("modifiers") or self.modifiers.modifiers()
        rules = self._applicable_rules(pending["trigger"], modifiers)
        rule = self._pick_rule(rules, pending["count"])
        if rule is None:
            self.last_event = {
                "trigger": pending["trigger"],
                "presses": pending["count"],
                "modifiers": modifiers,
                "at": int(time.time() * 1000),
            }
            return
        self._run_rule(
            rule, pending["trigger"], pending["count"], modifiers, pending.get("volume")
        )

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
            try:
                if not self._sink_provider:
                    return
                sink = self._sink_provider()
                if not sink:
                    return
                self.note_self_change(int(percent))
                res = _run(
                    ["pactl", "set-sink-volume", sink, "%d%%" % int(percent)], 6
                )
                if res is None or res.returncode != 0:
                    self.log(
                        "No se pudo restaurar el volumen a %d%% en %s (rc=%s)"
                        % (int(percent), sink, res.returncode if res else "error")
                    )
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
            except Exception as exc:
                # Este hilo es un temporizador: si muere en silencio, el
                # volumen se queda donde no toca y el usuario no sabe por que.
                self.log(
                    "No se pudo restaurar el volumen a %d%%: %s"
                    % (int(percent), exc)
                )

        timer = threading.Timer(RESTORE_DELAY, _apply, args=(RESTORE_ATTEMPTS,))
        timer.daemon = True
        timer.start()

    def _restore_volume(self, percent):
        if not self._sink_provider:
            return
        sink = self._sink_provider()
        if not sink:
            return
        self.note_self_change(int(percent))
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
        except Exception as exc:
            # El atajo ya se ha ejecutado; solo falla el aviso.
            self.log("No se pudo mostrar el aviso del atajo: %s" % exc)

    # -- estado --------------------------------------------------------------
    def snapshot(self):
        # El panel tiene que ver el fichero tal y como esta: si las reglas se
        # han editado a mano (o desde otra sesion), la vista en memoria puede
        # estar vieja.
        with self._lock:
            self.reload_rules_if_changed()
            rules = list(self.rules)
        return {
            "rules": rules,
            "last_event": self.last_event,
            "last_action": self.last_action,
            "modifiers": self.modifiers.modifiers(),
            "modifiers_available": self.modifiers.available,
        }
