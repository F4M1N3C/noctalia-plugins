#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Control para CMF Buds Pro 2 (B172) en Linux.

Habla el protocolo RFCOMM 0x55 que usa la app Nothing X. El flujo es:
  Bluetooth clasico conectado (A2DP) -> canal RFCOMM -> handshake -> comandos.

Modos:
  budsctl.py daemon ...   demonio persistente con socket Unix + state.json
  budsctl.py rpc '<json>' habla con el demonio
  budsctl.py status       imprime el estado actual
  budsctl.py stop         detiene el demonio

El protocolo se basa en el trabajo de:
  - https://github.com/SoaOaoS/something-x (MIT)
  - https://github.com/maniacx/BudsLink (GPL-3.0)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import traceback

try:
    from local_actions import LocalActionEngine
except Exception:  # pragma: no cover - el motor de atajos es opcional
    LocalActionEngine = None

# ── Protocolo 0x55 ────────────────────────────────────────────────────────────

SOF = 0x55
CTRL_HOST_CRC = 0x0160

CMD_PROTOCOL_GET = 0xC001
CMD_PROTOCOL_SET = 0xF001
CMD_MODEL_GET = 0xC01C
CMD_FIRMWARE_GET = 0xC042
CMD_SERIAL_GET = 0xC006
CMD_BATTERY_GET = 0xC007
CMD_EARPHONE_GET = 0xC00A
CMD_ANC_GET = 0xC01E
CMD_ANC_SET = 0xF00F
CMD_ANC_CONFIG_GET = 0xC01D
CMD_EQ_GET = 0xC01F
CMD_EQ_SET = 0xF010
CMD_LISTENING_MODE_GET = 0xC050
CMD_LISTENING_MODE_SET = 0xF01D
CMD_CUSTOM_EQ_GET = 0xC044
CMD_CUSTOM_EQ_SET = 0xF041
CMD_BASS_GET = 0xC04E
CMD_BASS_SET = 0xF051
CMD_SPATIAL_GET = 0xC04F
CMD_SPATIAL_SET = 0xF052
CMD_IN_EAR_GET = 0xC00E
CMD_IN_EAR_SET = 0xF004
CMD_LATENCY_GET = 0xC041
CMD_LATENCY_SET = 0xF040
CMD_DUAL_GET = 0xC027
CMD_DUAL_SET = 0xF01A
CMD_GESTURES_GET = 0xC018
CMD_GESTURES_SET = 0xF003
CMD_RING_SET = 0xF002
CMD_FIT_TEST_SET = 0xF014
CMD_FIT_TEST_NTFY = 0xE00D

# Notificaciones / respuestas
NTFY_BATTERY = 0xE001
NTFY_ANC = 0xE003
NTFY_STATUS = 0xE002
NTFY_GESTURES = 0x4018

# ANC
ANC_OFF = 5
ANC_STRONG = 1
ANC_MEDIUM = 2
ANC_WEAK = 3
ANC_ADAPTIVE = 4
ANC_TRANSPARENCY = 7

ANC_LEVELS = {
    "high": ANC_STRONG,
    "mid": ANC_MEDIUM,
    "low": ANC_WEAK,
    "adaptive": ANC_ADAPTIVE,
}
ANC_LEVEL_NAMES = {v: k for k, v in ANC_LEVELS.items()}

# Ecualización / listening modes del B172
LISTENING_MODES = {
    "balanced": 0,
    "rock": 1,
    "electronic": 2,
    "pop": 3,
    "vocal": 4,
    "classical": 5,
    "custom": 6,
}
LISTENING_MODE_NAMES = {v: k for k, v in LISTENING_MODES.items()}

# ECU del B172: 3 bandas paramétricas fijas
CUSTOM_EQ_GAIN_OFFSETS = (6, 19, 32)  # mid, treble, bass
CUSTOM_EQ_TEMPLATE = bytes(
    [
        0x03, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x75, 0x44, 0xC3, 0xF5, 0x28, 0x3F, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
        0xC0, 0x5A, 0x45, 0x00, 0x00, 0x80, 0x3F, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x0C, 0x43, 0xCD, 0xCC, 0x4C, 0x3F, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00,
    ]
)

# Gestos del CMF Buds Pro 2 (B172), sacados de BudsLink.
GESTURE_SLOTS = [
    # group, device, type, label
    ("left", 0x02, 0x02, "double"),
    ("left", 0x02, 0x03, "triple"),
    ("left", 0x02, 0x07, "hold"),
    ("left", 0x02, 0x09, "double_hold"),
    ("right", 0x03, 0x02, "double"),
    ("right", 0x03, 0x03, "triple"),
    ("right", 0x03, 0x07, "hold"),
    ("right", 0x03, 0x09, "double_hold"),
    ("case", 0x04, 0x01, "single"),
    ("case", 0x04, 0x02, "double"),
    ("case", 0x04, 0x03, "triple"),
    ("case", 0x04, 0x07, "hold"),
    ("case", 0x04, 0x09, "double_hold"),
    ("case", 0x04, 0x0A, "rotate"),
]
GESTURE_BY_KEY = {(g, t): (d, ty) for g, d, ty, t in GESTURE_SLOTS}

GESTURE_ACTIONS = {
    "no_action": 0x01,
    "play_pause": 0x02,
    "skip_back": 0x08,
    "skip_forward": 0x09,
    "voice_assistant": 0x0B,
    "volume_up": 0x12,
    "volume_down": 0x13,
    "noise_control": 0x0A,
    "game_mode": 0x11,
    "volume_control": 0x17,
}
GESTURE_ACTION_NAMES = {v: k for k, v in GESTURE_ACTIONS.items()}

GESTURE_ALLOWED = {
    ("left", "double"): ["play_pause", "skip_back", "skip_forward", "voice_assistant", "no_action"],
    ("left", "triple"): ["skip_back", "skip_forward", "voice_assistant", "no_action"],
    ("left", "hold"): ["noise_control", "voice_assistant", "no_action"],
    ("left", "double_hold"): ["volume_up", "volume_down", "voice_assistant", "no_action"],
    ("right", "double"): ["play_pause", "skip_back", "skip_forward", "voice_assistant", "no_action"],
    ("right", "triple"): ["skip_back", "skip_forward", "voice_assistant", "no_action"],
    ("right", "hold"): ["noise_control", "voice_assistant", "no_action"],
    ("right", "double_hold"): ["volume_up", "volume_down", "voice_assistant", "no_action"],
    ("case", "single"): ["play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action"],
    ("case", "double"): ["play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action"],
    ("case", "triple"): ["play_pause", "skip_back", "skip_forward", "voice_assistant", "game_mode", "no_action"],
    ("case", "hold"): ["noise_control", "voice_assistant", "game_mode", "no_action"],
    ("case", "double_hold"): ["volume_up", "volume_down", "voice_assistant", "game_mode", "no_action"],
    ("case", "rotate"): ["volume_control", "no_action"],
}

BATTERY_LEFT = 0x02
BATTERY_RIGHT = 0x03
BATTERY_CASE = 0x04
BATTERY_STEREO = 0x06


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def build_frame(cmd: int, payload: bytes = b"", fsn: int = 1) -> bytes:
    header = struct.pack("<BHHH", SOF, CTRL_HOST_CRC, cmd, len(payload)) + bytes([fsn & 0xFF])
    frame = header + payload
    return frame + struct.pack("<H", crc16(frame))


def parse_frames(buf: bytes):
    """Devuelve (frames, resto). Cada frame es (cmd_normalizado, payload)."""
    frames = []
    i = 0
    n = len(buf)
    while i + 8 <= n:
        if buf[i] != SOF:
            i += 1
            continue
        try:
            _, ctrl, cmd, length = struct.unpack_from("<BHHH", buf, i)
        except struct.error:
            break
        crc_len = 2 if (ctrl & 0x20) else 0
        total = 8 + length + crc_len
        if i + total > n:
            break
        payload = buf[i + 8 : i + 8 + length]
        # No descartamos por CRC: algunos firmwares mandan CRC raro y el
        # payload sigue siendo válido. Solo lo comprobamos para el log.
        frames.append((cmd | 0x8000, payload))
        i += total
    return frames, buf[i:]


def eq_float_encode(value: float, preamp: bool = False) -> bytes:
    if preamp and value >= 0:
        return bytes([0x00, 0x00, 0x00, 0x80])
    be = bytearray(struct.pack(">f", float(value)))
    if value != 0.0 and be[0] == 0 and be[1] == 0 and be[2] == 0:
        be[3] |= 0x80
    return bytes(reversed(be))


def eq_float_decode(raw: bytes) -> float:
    try:
        return struct.unpack(">f", bytes(reversed(raw)))[0]
    except Exception:
        return 0.0


MODEL_BY_SKU = {
    "01": "B181", "02": "B181", "03": "B181", "04": "B181", "06": "B181",
    "07": "B181", "08": "B181", "10": "B181",
    "14": "B157", "15": "B157", "16": "B157",
    "17": "B155", "18": "B155", "19": "B155", "27": "B155", "28": "B155", "29": "B155",
    "30": "B163", "31": "B163", "32": "B163", "33": "B163", "34": "B163", "35": "B163",
    "48": "B164", "49": "B164", "50": "B164", "51": "B164", "52": "B164", "53": "B164",
    "54": "B168", "55": "B168", "56": "B168", "57": "B168", "58": "B168", "59": "B168",
    "61": "B171", "62": "B171", "69": "B171", "70": "B171", "74": "B171", "75": "B171",
    "63": "B162", "64": "B162", "65": "B162", "66": "B162", "67": "B162",
    "68": "B162", "71": "B162", "72": "B162", "73": "B162",
    "76": "B172", "77": "B172", "78": "B172", "79": "B172", "80": "B172",
    "81": "B172", "82": "B172", "83": "B172",
}


def model_from_serial(serial: str | None) -> str | None:
    if not serial or len(serial) < 6:
        return None
    return MODEL_BY_SKU.get(serial[4:6])


def model_from_name(name: str | None) -> str | None:
    if not name:
        return None
    n = name.lower()
    if "cmf buds pro 2" in n:
        return "B172"
    if "cmf buds 2 plus" in n or "cmf buds 2+" in n:
        return "B171"
    if "cmf buds 2" in n:
        return "B168"
    if "cmf buds" in n:
        return "B168"
    return None


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


def bt_devices():
    res = run(["bluetoothctl", "devices"], 8)
    out = []
    for line in (res.stdout or "").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            out.append({"mac": parts[1], "name": parts[2].strip()})
    return out


def bt_info(mac: str):
    res = run(["bluetoothctl", "info", mac], 8)
    info = {"mac": mac, "name": "", "alias": "", "connected": False, "battery": None, "icon": ""}
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Alias:"):
            info["alias"] = line.split(":", 1)[1].strip()
        elif line.startswith("Connected:"):
            info["connected"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Icon:"):
            info["icon"] = line.split(":", 1)[1].strip()
        elif line.startswith("Battery Percentage:"):
            try:
                info["battery"] = int(line.split("(")[1].split(")")[0].strip().rstrip("%"))
            except Exception:
                pass
    if not info["name"]:
        info["name"] = info["alias"] or "CMF Buds Pro 2"
    return info


def pick_device(preferred_mac: str = "", preferred_name: str = ""):
    devices = bt_devices()
    if preferred_mac:
        info = bt_info(preferred_mac)
        info["name"] = info["name"] or preferred_name or info["mac"]
        return info
    candidates = []
    for dev in devices:
        name = (dev.get("name") or "").lower()
        info = bt_info(dev["mac"])
        if preferred_name and preferred_name.lower() in (dev.get("name") or "").lower():
            candidates.insert(0, info)
            continue
        if any(key in name for key in ("cmf buds", "nothing ear", "cmf headphone", "nothing headphone", "ear (")):
            candidates.append(info)
    if not candidates:
        return None
    candidates.sort(key=lambda d: (not d.get("connected"), 0 if "cmf buds pro 2" in d.get("name", "").lower() else 1))
    return candidates[0]


# ── Enlace RFCOMM ─────────────────────────────────────────────────────────────


class BudsLink:
    PROBE_CHANNELS = [15, 17, 16, 18, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

    def __init__(self, mac: str, log=None):
        self.mac = mac
        self.sock: socket.socket | None = None
        self.fsn = 0
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.reader = None
        self.running = False
        self.connected = False
        self.log = log or (lambda *a: None)

    # -- conexión ------------------------------------------------------------
    def open(self):
        last_exc = None
        for ch in self.PROBE_CHANNELS:
            try:
                sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                sock.settimeout(3.5)
                sock.connect((self.mac, ch))
            except OSError as exc:
                last_exc = exc
                try:
                    sock.close()
                except Exception:
                    pass
                continue
            try:
                sock.sendall(build_frame(CMD_PROTOCOL_GET, b"", 1))
                sock.settimeout(2.0)
                data = b""
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and len(data) < 4:
                    chunk = sock.recv(512)
                    if not chunk:
                        break
                    data += chunk
                if not data or data[:1] != b"\x55":
                    sock.close()
                    continue
                # Handshake: activar protocolo
                sock.sendall(build_frame(CMD_PROTOCOL_SET, b"", 2))
                sock.settimeout(1.2)
                frames, _ = parse_frames(data)
                activated = False
                deadline = time.monotonic() + 2.5
                buf = b""
                while time.monotonic() < deadline:
                    try:
                        chunk = sock.recv(1024)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    fs, buf = parse_frames(buf)
                    frames += fs
                    if any(cmd == CMD_PROTOCOL_SET for cmd, _ in frames):
                        activated = True
                        break
                self.fsn = 2
                self.sock = sock
                self.connected = True
                self.log(f"RFCOMM conectado en canal {ch} (activado={activated})")
                sock.settimeout(1.0)
                self.running = True
                self.reader = threading.Thread(target=self._read_loop, name="buds-reader", daemon=True)
                self.reader.start()
                return True
            except OSError as exc:
                last_exc = exc
                try:
                    sock.close()
                except Exception:
                    pass
                continue
        self.connected = False
        raise RuntimeError(f"No se pudo abrir RFCOMM: {last_exc}")

    def close(self):
        self.running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    # -- envío / recepción ---------------------------------------------------
    def _read_loop(self):
        buf = b""
        while self.running and self.sock:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                frames, buf = parse_frames(buf)
                for cmd, payload in frames:
                    self._handle(cmd, payload)
            except socket.timeout:
                continue
            except OSError:
                break
        self.connected = False
        self.log("RFCOMM desconectado")
        with self.pending_lock:
            for wait in self.pending.values():
                wait["event"].set()

    def _handle(self, cmd, payload):
        with self.pending_lock:
            wait = self.pending.get(cmd)
            if wait is not None:
                wait["payload"] = payload
                wait["event"].set()
        self_on_frame = getattr(self, "on_frame", None)
        if self_on_frame:
            try:
                self_on_frame(cmd, payload)
            except Exception:
                self.log("Error en on_frame: " + traceback.format_exc())

    def request(self, cmd, payload=b"", timeout=1.5):
        if not self.connected or not self.sock:
            raise RuntimeError("RFCOMM no conectado")
        wait = {"event": threading.Event(), "payload": None}
        with self.pending_lock:
            self.pending[cmd] = wait
        self.fsn = (self.fsn + 1) & 0xFF
        frame = build_frame(cmd, payload, self.fsn)
        try:
            with self.send_lock:
                self.sock.sendall(frame)
        except OSError as exc:
            with self.pending_lock:
                self.pending.pop(cmd, None)
            raise RuntimeError(f"Error enviando comando: {exc}")
        ok = wait["event"].wait(timeout)
        with self.pending_lock:
            self.pending.pop(cmd, None)
        if not ok:
            raise TimeoutError(f"Sin respuesta para 0x{cmd:04X}")
        return wait["payload"] or b""

    def send(self, cmd, payload=b"", timeout=1.0, ignore_timeout=True):
        try:
            return self.request(cmd, payload, timeout)
        except TimeoutError:
            if ignore_timeout:
                return b""
            raise


# ── Estado ────────────────────────────────────────────────────────────────────


def empty_state():
    return {
        "ok": True,
        "connected": False,
        "audio_connected": False,
        "device": {
            "name": "",
            "alias": "",
            "mac": "",
            "model": "",
            "firmware": "",
            "serial": "",
        },
        "battery": {
            "left": None,
            "right": None,
            "case": None,
            "charging": {"left": False, "right": False, "case": False},
            "bluez": None,
        },
        "anc": {"mode": "unknown", "level": "high"},
        "eq": {"preset": "balanced", "preset_index": 0, "kind": "listening", "custom": {"bass": 0, "mid": 0, "treble": 0}},
        "bass": {"enabled": False, "level": 1},
        "spatial": None,
        "in_ear": None,
        "low_latency": None,
        "dual_connection": None,
        "gestures": {},
        "fit_test": {"running": False, "left": None, "right": None},
        "ring": {"left": False, "right": False},
        "volume": {"percent": None, "muted": False, "sink": "", "description": ""},
        "model": "B172",
        "updated_at": 0,
        "error": "",
        "daemon_pid": 0,
    }


class BudsDaemon:
    def __init__(self, args):
        self.args = args
        self.state_path = os.path.abspath(os.path.expanduser(args.state))
        self.socket_path = os.path.abspath(os.path.expanduser(args.socket))
        self.log_path = os.path.abspath(os.path.expanduser(args.log)) if args.log else ""
        self.poll = max(15, int(args.poll))
        self.idle_timeout = max(60, int(args.idle_timeout))
        self.preferred_mac = (args.device_mac or "").strip()
        self.preferred_name = (args.device_name or "").strip()
        self.state = empty_state()
        self.state["daemon_pid"] = os.getpid()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.link: BudsLink | None = None
        self.last_client = time.time()
        self.last_full = 0.0
        self.last_connect_attempt = 0.0
        self.connect_backoff = 5.0
        self.ring_until = {"left": 0.0, "right": 0.0}
        self.dirty = True
        self._lock_file = None
        self._server = None
        self._started_at = time.time()
        self._save_lock = threading.Lock()
        self.local = None
        if LocalActionEngine is not None:
            try:
                self.local = LocalActionEngine(
                    os.path.dirname(self.state_path), log=self.log
                )
            except Exception as exc:
                self.log("No se pudo crear el motor de acciones locales: %s" % exc)

    # -- logging -------------------------------------------------------------
    def log(self, msg):
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg) + "\n"
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 300_000:
                os.replace(self.log_path, self.log_path + ".old")
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass

    # -- persistencia --------------------------------------------------------
    def save(self):
        with self.lock:
            self.state["updated_at"] = int(time.time() * 1000)
            self.state["daemon_pid"] = os.getpid()
            if self.local is not None:
                try:
                    self.state["local_actions"] = self.local.snapshot()
                except Exception:
                    pass
            data = json.dumps(self.state, ensure_ascii=False, separators=(",", ":"))
        tmp = self.state_path + f".{os.getpid()}.tmp"
        # Varios hilos (monitor, RPC, lector RFCOMM) pueden guardar a la vez.
        # Sin este candado, un hilo puede borrar el temporal de otro con el
        # os.replace y la escritura falla con ENOENT.
        with self._save_lock:
            try:
                os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(data)
                os.replace(tmp, self.state_path)
            except Exception as exc:
                self.log(f"No se pudo guardar state: {exc}")

    # -- dispositivo ---------------------------------------------------------
    def _refresh_device_info(self):
        info = None
        try:
            info = pick_device(self.preferred_mac, self.preferred_name)
        except Exception as exc:
            self.log(f"pick_device: {exc}")
        with self.lock:
            if info is None:
                self.state["audio_connected"] = False
                self.state["error"] = "No encuentro los CMF Buds. Empareja/conecta los auriculares."
                return False
            dev = self.state["device"]
            dev["name"] = info.get("name") or dev.get("name") or "CMF Buds Pro 2"
            dev["alias"] = info.get("alias") or dev["name"]
            dev["mac"] = info.get("mac") or dev.get("mac")
            self.state["audio_connected"] = bool(info.get("connected"))
            if info.get("battery") is not None:
                self.state["battery"]["bluez"] = info["battery"]
                if self.state["battery"]["left"] is None:
                    self.state["battery"]["left"] = info["battery"]
            # El nombre es más fiable que el serial: la tabla de SKU de
            # something-x no conoce todos los prefijos del B172.
            model = model_from_name(dev["name"]) or self.state.get("model") or model_from_serial(dev.get("serial")) or "B172"
            dev["model"] = model
            self.state["model"] = model
            return True

    def connect(self, force_bt=False):
        now = time.time()
        if self.link and self.link.connected:
            return True
        if now - self.last_connect_attempt < self.connect_backoff:
            return False
        self.last_connect_attempt = now
        self.connect_backoff = min(30.0, self.connect_backoff + 5.0)
        try:
            info = pick_device(self.preferred_mac, self.preferred_name)
        except Exception:
            info = None
        if info is None:
            self.log("No hay dispositivo Nothing/CMF emparejado")
            with self.lock:
                self.state["error"] = "No encuentro los CMF Buds. Empareja los auriculares primero."
                self.state["connected"] = False
            self.save()
            return False
        mac = info["mac"]
        with self.lock:
            self.state["device"]["mac"] = mac
            self.state["device"]["name"] = info.get("name") or self.state["device"]["name"]
            self.state["device"]["alias"] = info.get("alias") or self.state["device"]["name"]
            self.state["audio_connected"] = bool(info.get("connected"))
            if info.get("battery") is not None:
                self.state["battery"]["bluez"] = info["battery"]
                if self.state["battery"]["left"] is None:
                    self.state["battery"]["left"] = info["battery"]
            model = model_from_name(self.state["device"]["name"]) or self.state.get("model") or "B172"
            self.state["device"]["model"] = model
            self.state["model"] = model
        if not info.get("connected"):
            if force_bt:
                self.log(f"Conectando Bluetooth a {mac}")
                run(["bluetoothctl", "connect", mac], 20)
                time.sleep(2)
                info = bt_info(mac)
                with self.lock:
                    self.state["audio_connected"] = bool(info.get("connected"))
            else:
                with self.lock:
                    self.state["connected"] = False
                    self.state["error"] = "Los auriculares están desconectados. Pulsa Conectar."
                self.save()
                return False
        try:
            link = BudsLink(mac, self.log)
            link.on_frame = self.on_frame
            link.open()
            self.link = link
            with self.lock:
                self.state["connected"] = True
                self.state["error"] = ""
            self.log("Enlace listo")
            self.query_all()
            return True
        except Exception as exc:
            self.log(f"connect: {exc}")
            with self.lock:
                self.state["connected"] = False
                msg = str(exc)
                if "busy" in msg.lower() or "device or resource busy" in msg.lower():
                    msg = "Canal ocupado. Cierra Nothing X en el teléfono o desconecta el móvil."
                self.state["error"] = msg
            self.save()
            return False

    def disconnect(self):
        if self.link:
            self.link.close()
        self.link = None
        with self.lock:
            self.state["connected"] = False
        self.save()

    # -- parseo --------------------------------------------------------------
    def on_frame(self, cmd, payload):
        changed = False
        with self.lock:
            st = self.state
            if cmd in (CMD_BATTERY_GET, NTFY_BATTERY):
                if len(payload) >= 3:
                    count = payload[0]
                    for i in range(1, 1 + count * 2, 2):
                        if i + 1 >= len(payload):
                            break
                        btype, bval = payload[i], payload[i + 1]
                        pct = bval & 0x7F
                        charging = bool(bval & 0x80)
                        key = {BATTERY_LEFT: "left", BATTERY_RIGHT: "right", BATTERY_CASE: "case"}.get(btype)
                        if btype == BATTERY_STEREO:
                            st["battery"]["left"] = pct
                            st["battery"]["right"] = pct
                            changed = True
                        elif key:
                            st["battery"][key] = pct
                            st["battery"]["charging"][key] = charging
                            changed = True
            elif cmd in (CMD_ANC_GET, NTFY_ANC):
                # payload: tripletes (tipo, valor, pad)
                for i in range(0, len(payload) - 1, 3):
                    t, val = payload[i], payload[i + 1]
                    if t == 1:
                        if val == ANC_TRANSPARENCY:
                            st["anc"]["mode"] = "transparency"
                        elif val in (ANC_OFF, 0):
                            st["anc"]["mode"] = "off"
                        elif 1 <= val <= 4:
                            st["anc"]["mode"] = "anc"
                            st["anc"]["level"] = ANC_LEVEL_NAMES.get(val, "high")
                        changed = True
                    elif t == 2 and 1 <= val <= 4:
                        st["anc"]["level"] = ANC_LEVEL_NAMES.get(val, st["anc"]["level"])
                        changed = True
            elif cmd == CMD_LISTENING_MODE_GET:
                if payload:
                    idx = payload[0]
                    name = LISTENING_MODE_NAMES.get(idx)
                    if name:
                        st["eq"]["preset"] = name
                        st["eq"]["preset_index"] = idx
                        st["eq"]["kind"] = "listening"
                        changed = True
            elif cmd == CMD_EQ_GET:
                if payload:
                    idx = payload[0]
                    names = {0: "balanced", 1: "more_bass", 2: "more_treble", 3: "voice"}
                    st["eq"]["preset"] = names.get(idx, "balanced")
                    st["eq"]["preset_index"] = idx
                    st["eq"]["kind"] = "classic"
                    changed = True
            elif cmd == CMD_CUSTOM_EQ_GET:
                if len(payload) >= 36:
                    gains = [eq_float_decode(payload[o : o + 4]) for o in CUSTOM_EQ_GAIN_OFFSETS]
                    mid, treble, bass = gains
                    st["eq"]["custom"] = {
                        "bass": max(-6, min(6, round(bass))),
                        "mid": max(-6, min(6, round(mid))),
                        "treble": max(-6, min(6, round(treble))),
                    }
                    changed = True
            elif cmd == CMD_BASS_GET:
                if len(payload) >= 2:
                    st["bass"]["enabled"] = payload[0] == 1
                    st["bass"]["level"] = max(1, min(5, round(payload[1] / 2)))
                    changed = True
            elif cmd == CMD_SPATIAL_GET:
                if payload:
                    st["spatial"] = payload[0] == 1
                    changed = True
            elif cmd == CMD_IN_EAR_GET:
                if len(payload) >= 3:
                    # BudsLink usa payload[2] para el ajuste.
                    st["in_ear"] = payload[2] == 1
                    changed = True
            elif cmd == CMD_LATENCY_GET:
                if payload:
                    st["low_latency"] = payload[0] == 1
                    changed = True
            elif cmd == CMD_DUAL_GET:
                if payload:
                    st["dual_connection"] = payload[0] == 1
                    changed = True
            elif cmd == CMD_GESTURES_GET:
                if payload:
                    count = payload[0]
                    gestures = {}
                    off = 1
                    for _ in range(count):
                        if off + 3 >= len(payload):
                            break
                        dev, btn, typ, action = payload[off : off + 4]
                        # El estuche manda dos grupos: 04/01 es el dial
                        # (single, double, triple, hold, rotate) y 04/09 es
                        # un botón interno que la app no expone. Ignoramos
                        # el segundo para no pisar los gestos del dial.
                        if dev == 0x04 and btn != 0x01:
                            off += 4
                            continue
                        group = {0x02: "left", 0x03: "right", 0x04: "case"}.get(dev, "case")
                        tname = {
                            0x01: "single", 0x02: "double", 0x03: "triple",
                            0x07: "hold", 0x09: "double_hold", 0x0A: "rotate",
                        }.get(typ)
                        aname = GESTURE_ACTION_NAMES.get(action)
                        if tname and aname:
                            gestures[f"{group}.{tname}"] = aname
                        off += 4
                    st["gestures"] = gestures
                    changed = True
            elif cmd == CMD_FIRMWARE_GET:
                txt = payload.decode("utf-8", "replace").strip("\x00 \n")
                if txt:
                    st["device"]["firmware"] = txt
                    changed = True
            elif cmd == CMD_SERIAL_GET:
                raw = payload.decode("utf-8", "replace").strip("\x00")
                for line in raw.splitlines():
                    parts = line.split(",", 2)
                    if len(parts) == 3 and parts[1] == "4" and parts[2].strip():
                        st["device"]["serial"] = parts[2].strip()
                        # Solo usar el serial si el nombre no identificó ya el modelo.
                        if not model_from_name(st["device"].get("name")):
                            model = model_from_serial(parts[2].strip())
                            if model:
                                st["device"]["model"] = model
                                st["model"] = model
                        changed = True
                        break
            elif cmd == CMD_MODEL_GET:
                if len(payload) >= 2:
                    mid = payload[0] | (payload[1] << 8)
                    st["device"]["model"] = f"{mid:04X}" if mid else st["device"]["model"]
                    changed = True
            elif cmd == CMD_FIT_TEST_NTFY:
                if len(payload) >= 2:
                    st["fit_test"]["left"] = payload[0]
                    st["fit_test"]["right"] = payload[1]
                    st["fit_test"]["running"] = False
                    changed = True
            elif cmd == CMD_ANC_SET:
                # ACK del set; el evento 0xE003 llegará luego
                pass
        if changed:
            self.save()

    # -- comandos ------------------------------------------------------------
    def query_all(self):
        if not self.link or not self.link.connected:
            return False
        cmds = [
            (CMD_BATTERY_GET, b""),
            (CMD_ANC_GET, b"\x03"),
            (CMD_LISTENING_MODE_GET, b""),
            (CMD_CUSTOM_EQ_GET, b""),
            (CMD_BASS_GET, b""),
            (CMD_SPATIAL_GET, b""),
            (CMD_IN_EAR_GET, b""),
            (CMD_LATENCY_GET, b""),
            (CMD_DUAL_GET, b""),
            (CMD_GESTURES_GET, b""),
            (CMD_FIRMWARE_GET, b""),
            (CMD_SERIAL_GET, b""),
        ]
        for cmd, payload in cmds:
            try:
                self.link.request(cmd, payload, timeout=1.2)
            except TimeoutError:
                self.log(f"Timeout consultando 0x{cmd:04X}")
            except Exception as exc:
                self.log(f"query 0x{cmd:04X}: {exc}")
                break
            time.sleep(0.04)
        with self.lock:
            self.state["connected"] = bool(self.link and self.link.connected)
            if self.state["connected"]:
                self.state["error"] = ""
        self.last_full = time.time()
        self.refresh_volume()
        self.save()
        return True

    def set_anc(self, mode: str, level: str | None = None):
        if mode == "off":
            val = ANC_OFF
        elif mode == "transparency":
            val = ANC_TRANSPARENCY
        elif mode == "anc":
            val = ANC_LEVELS.get(level or "high", ANC_STRONG)
        else:
            raise ValueError("modo ANC inválido")
        self._require_link()
        self.link.send(CMD_ANC_SET, bytes([0x01, val, 0x00]), 1.2)
        with self.lock:
            self.state["anc"]["mode"] = mode
            if mode == "anc" and level:
                self.state["anc"]["level"] = level
        # El GET de ANC tarda un poco en reflejar el cambio; si lo consultamos
        # ya, devuelve el modo anterior y pisa el estado optimista. El evento
        # 0xE003 llega solo y actualiza el estado real.
        self.save()
        return self.state

    def set_eq(self, preset: str):
        self._require_link()
        if preset not in LISTENING_MODES:
            raise ValueError("preset inválido")
        idx = LISTENING_MODES[preset]
        self.link.send(CMD_LISTENING_MODE_SET, bytes([idx, 0x00]), 1.2)
        with self.lock:
            self.state["eq"]["preset"] = preset
            self.state["eq"]["preset_index"] = idx
        time.sleep(0.2)
        try:
            self.link.request(CMD_CUSTOM_EQ_GET, b"", 1.0)
        except Exception:
            pass
        self.save()
        return self.state

    def set_custom_eq(self, bass: int, mid: int, treble: int):
        self._require_link()
        bass, mid, treble = (max(-6, min(6, int(v))) for v in (bass, mid, treble))
        gains = (mid, treble, bass)
        buf = bytearray(CUSTOM_EQ_TEMPLATE)
        buf[1:5] = eq_float_encode(-max(gains), preamp=True)
        for off, gain in zip(CUSTOM_EQ_GAIN_OFFSETS, gains):
            buf[off : off + 4] = eq_float_encode(float(gain))
        self.link.send(CMD_CUSTOM_EQ_SET, bytes(buf), 1.4)
        # La app escribe la curva y después activa el modo "Custom"; si no,
        # el firmware guarda los valores pero sigue sonando el preset actual.
        self.link.send(CMD_LISTENING_MODE_SET, bytes([LISTENING_MODES["custom"], 0x00]), 1.2)
        with self.lock:
            self.state["eq"]["custom"] = {"bass": bass, "mid": mid, "treble": treble}
            self.state["eq"]["preset"] = "custom"
            self.state["eq"]["preset_index"] = LISTENING_MODES["custom"]
        self.save()
        return self.state

    def set_bass(self, enabled: bool, level: int | None = None):
        self._require_link()
        level = max(1, min(5, int(level if level is not None else self.state["bass"]["level"])))
        self.link.send(CMD_BASS_SET, bytes([1 if enabled else 0, level * 2]), 1.2)
        with self.lock:
            self.state["bass"]["enabled"] = bool(enabled)
            self.state["bass"]["level"] = level
        self.save()
        return self.state

    def set_toggle(self, key: str, value: bool):
        self._require_link()
        if key == "spatial":
            self.link.send(CMD_SPATIAL_SET, bytes([1 if value else 0]), 1.2)
        elif key == "in_ear":
            self.link.send(CMD_IN_EAR_SET, bytes([0x01, 0x01, 1 if value else 0]), 1.2)
        elif key == "low_latency":
            self.link.send(CMD_LATENCY_SET, bytes([0x01 if value else 0x02, 0x00]), 1.2)
        elif key == "dual_connection":
            self.link.send(CMD_DUAL_SET, bytes([1 if value else 0]), 1.2)
        else:
            raise ValueError("ajuste desconocido")
        with self.lock:
            self.state[key] = bool(value)
        time.sleep(0.15)
        self.save()
        return self.state

    def set_gesture(self, group: str, gesture_type: str, action: str):
        self._require_link()
        key = (group, gesture_type)
        if key not in GESTURE_BY_KEY:
            raise ValueError("gesto inválido")
        if action not in GESTURE_ACTIONS:
            raise ValueError("acción inválida")
        device, typ = GESTURE_BY_KEY[key]
        self.link.send(CMD_GESTURES_SET, bytes([0x01, device, 0x01, typ, GESTURE_ACTIONS[action]]), 1.2)
        with self.lock:
            self.state["gestures"][f"{group}.{gesture_type}"] = action
        self.save()
        return self.state

    def ring(self, side: str, enabled: bool):
        self._require_link()
        device = 0x02 if side == "left" else 0x03
        self.link.send(CMD_RING_SET, bytes([device, 1 if enabled else 0]), 1.2)
        with self.lock:
            self.state["ring"][side] = bool(enabled)
            self.ring_until[side] = time.time() + 15 if enabled else 0
        self.save()
        return self.state

    def fit_test(self, start: bool):
        self._require_link()
        self.link.send(CMD_FIT_TEST_SET, bytes([1 if start else 0]), 1.2)
        with self.lock:
            self.state["fit_test"]["running"] = bool(start)
            if start:
                self.state["fit_test"]["left"] = None
                self.state["fit_test"]["right"] = None
        self.save()
        return self.state

    def _require_link(self):
        if not self.link or not self.link.connected:
            raise RuntimeError("Auriculares no conectados por RFCOMM")

    # -- volumen -------------------------------------------------------------
    def _sink(self):
        mac = self.state["device"].get("mac", "").replace(":", "_")
        res = run(["pactl", "list", "sinks", "short"], 6)
        sinks = []
        for line in (res.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                sinks.append(parts[1])
        if mac:
            for name in sinks:
                if f"bluez_output.{mac}" in name:
                    return name
        res = run(["pactl", "get-default-sink"], 5)
        return (res.stdout or "").strip() or (sinks[0] if sinks else "")

    def refresh_volume(self):
        sink = self._sink()
        pct = None
        muted = False
        desc = ""
        if sink:
            res = run(["pactl", "get-sink-volume", sink], 6)
            for tok in (res.stdout or "").split():
                if tok.endswith("%"):
                    try:
                        pct = int(tok.rstrip("%"))
                        break
                    except ValueError:
                        pass
            res = run(["pactl", "get-sink-mute", sink], 6)
            muted = "yes" in (res.stdout or "").lower()
            res = run(["pactl", "list", "sinks"], 6)
            current = None
            for line in (res.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("Name:"):
                    current = line.split(":", 1)[1].strip()
                elif line.startswith("Description:") and current == sink:
                    desc = line.split(":", 1)[1].strip()
                    break
        with self.lock:
            self.state["volume"] = {"percent": pct, "muted": muted, "sink": sink, "description": desc}
        return self.state["volume"]

    def set_volume(self, percent: int | None = None, mute: str | None = None):
        sink = self._sink()
        if not sink:
            raise RuntimeError("No hay sink de audio")
        if self.local is not None:
            self.local.note_self_change()
        if percent is not None:
            pct = max(0, min(150, int(percent)))
            run(["pactl", "set-sink-volume", sink, f"{pct}%"], 6)
        if mute == "toggle":
            run(["pactl", "set-sink-mute", sink, "toggle"], 6)
        elif mute in ("on", "off"):
            run(["pactl", "set-sink-mute", sink, "1" if mute == "on" else "0"], 6)
        self.refresh_volume()
        self.save()
        return self.state

    # -- lazo principal ------------------------------------------------------
    def monitor(self):
        while not self.stop_event.is_set():
            now = time.time()
            try:
                if self.link is None or not self.link.connected:
                    self.connect()
                else:
                    if now - self.last_full >= self.poll:
                        self.query_all()
                # apagar anillos automáticamente
                for side, until in list(self.ring_until.items()):
                    if until and now >= until:
                        try:
                            self.ring(side, False)
                        except Exception:
                            pass
                        self.ring_until[side] = 0
                if self.link is None or not self.link.connected:
                    self.refresh_volume()
                    self.save()
            except Exception as exc:
                self.log("monitor: " + traceback.format_exc())
                with self.lock:
                    self.state["error"] = str(exc)
                self.save()
            if now - self.last_client > self.idle_timeout:
                self.log("Sin clientes; cerrando demonio")
                self.stop_event.set()
                break
            self.stop_event.wait(1.0 if (self.link and self.link.connected) else 3.0)

    # -- RPC -----------------------------------------------------------------
    def handle_rpc(self, req):
        cmd = (req or {}).get("cmd", "status")
        self.last_client = time.time()
        if cmd == "ping":
            return {"ok": True, "state": self.snapshot()}
        if cmd == "status":
            self.refresh_volume()
            return {"ok": True, "state": self.snapshot()}
        if cmd == "refresh":
            if self.link and self.link.connected:
                self.query_all()
            else:
                self.connect(force_bt=True)
            return {"ok": True, "state": self.snapshot()}
        if cmd == "connect":
            self.connect(force_bt=True)
            return {"ok": True, "state": self.snapshot()}
        if cmd == "anc":
            return {"ok": True, "state": self.set_anc(req.get("mode", "anc"), req.get("level"))}
        if cmd == "eq":
            return {"ok": True, "state": self.set_eq(req.get("preset", "balanced"))}
        if cmd == "custom_eq":
            return {"ok": True, "state": self.set_custom_eq(req.get("bass", 0), req.get("mid", 0), req.get("treble", 0))}
        if cmd == "bass":
            return {"ok": True, "state": self.set_bass(bool(req.get("enabled", False)), req.get("level"))}
        if cmd == "toggle":
            return {"ok": True, "state": self.set_toggle(req.get("key", ""), bool(req.get("value", False)))}
        if cmd == "gesture":
            return {"ok": True, "state": self.set_gesture(req.get("group", "left"), req.get("gesture", "double"), req.get("action", "no_action"))}
        if cmd == "ring":
            return {"ok": True, "state": self.ring(req.get("side", "left"), bool(req.get("on", True)))}
        if cmd == "fit_test":
            return {"ok": True, "state": self.fit_test(bool(req.get("start", True)))}
        if cmd == "volume":
            return {"ok": True, "state": self.set_volume(req.get("percent"), req.get("mute"))}
        if cmd == "local_rules":
            return {"ok": True, "state": self.snapshot(), "local_actions": self._local_snapshot()}
        if cmd == "local_rule_set":
            if self.local is None:
                raise RuntimeError("El motor de acciones locales no está disponible")
            rule = req.get("rule") or {}
            saved = self.local.upsert(dict(rule))
            return {"ok": True, "state": self.snapshot(), "local_actions": self._local_snapshot(), "rule": saved}
        if cmd == "local_rule_delete":
            if self.local is None:
                raise RuntimeError("El motor de acciones locales no está disponible")
            self.local.delete(req.get("id", ""))
            return {"ok": True, "state": self.snapshot(), "local_actions": self._local_snapshot()}
        if cmd == "local_test":
            if self.local is None:
                raise RuntimeError("El motor de acciones locales no está disponible")
            command = (req.get("command") or "").strip()
            if not command:
                raise ValueError("Falta el comando")
            ok = self.local.run_command(command)
            return {"ok": ok, "state": self.snapshot(), "local_actions": self._local_snapshot()}
        if cmd == "shutdown":
            threading.Thread(target=self.shutdown, daemon=True).start()
            return {"ok": True, "state": self.snapshot()}
        raise ValueError("comando desconocido")

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def _local_snapshot(self):
        if self.local is None:
            return {"rules": [], "last": {}, "modifiers": [], "modifiers_available": False}
        try:
            return self.local.snapshot()
        except Exception as exc:
            self.log("snapshot local: %s" % exc)
            return {"rules": [], "last": {}, "modifiers": [], "modifiers_available": False}

    # -- ciclo de vida -------------------------------------------------------
    def shutdown(self):
        self.stop_event.set()
        self.disconnect()
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def run(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        # lock exclusivo
        lock_path = self.socket_path + ".lock"
        self._lock_file = open(lock_path, "a+")
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"ok": True, "already_running": True}))
            return 0
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError:
            pass
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                daemon.last_client = time.time()
                try:
                    line = self.rfile.readline(65536)
                    if not line:
                        return
                    req = json.loads(line.decode("utf-8"))
                    resp = daemon.handle_rpc(req)
                except Exception as exc:
                    daemon.log("rpc: " + traceback.format_exc())
                    resp = {"ok": False, "error": str(exc), "state": daemon.snapshot()}
                try:
                    self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                except Exception:
                    pass

        class Server(socketserver.ThreadingUnixStreamServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(self.socket_path, Handler)
        try:
            os.chmod(self.socket_path, 0o600)
        except OSError:
            pass

        def on_sig(_signum, _frame):
            self.stop_event.set()
            threading.Thread(target=self._server.shutdown, daemon=True).start()

        import signal
        signal.signal(signal.SIGTERM, on_sig)
        signal.signal(signal.SIGINT, on_sig)

        self.log(f"Demonio iniciado (pid {os.getpid()}, socket {self.socket_path})")
        threading.Thread(target=self.monitor, name="buds-monitor", daemon=True).start()
        if self.local is not None:
            try:
                self.local.start(self._sink)
            except Exception as exc:
                self.log("No se pudo iniciar el motor de acciones locales: %s" % exc)
        try:
            self._server.serve_forever(poll_interval=0.5)
        finally:
            self.stop_event.set()
            if self.local is not None:
                try:
                    self.local.stop()
                except Exception:
                    pass
            self.disconnect()
            try:
                self._server.server_close()
            except Exception:
                pass
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
            if self._lock_file:
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            self.log("Demonio detenido")
        return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def default_paths():
    state_home = os.environ.get("NOCTALIA_STATE_HOME") or os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    data = os.path.join(state_home, "noctalia", "plugins", "data", "faminec", "cmf-buds")
    return {
        "state": os.path.join(data, "state.json"),
        "socket": os.path.join(data, "daemon.sock"),
        "log": os.path.join(data, "daemon.log"),
    }


def rpc_call(socket_path, req, timeout=8.0):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(socket_path)
    sock.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()
    return json.loads(data.decode("utf-8"))


def ensure_daemon(args, paths):
    socket_path = os.path.abspath(os.path.expanduser(args.socket or paths["socket"]))
    try:
        return rpc_call(socket_path, {"cmd": "ping"}, 1.0)
    except Exception:
        pass
    # arrancar en segundo plano
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "daemon",
        "--state", os.path.abspath(os.path.expanduser(args.state or paths["state"])),
        "--socket", socket_path,
        "--log", os.path.abspath(os.path.expanduser(args.log or paths["log"])),
        "--poll", str(getattr(args, "poll", 60)),
        "--idle-timeout", str(getattr(args, "idle_timeout", 300)),
        "--device-mac", getattr(args, "device_mac", "") or "",
        "--device-name", getattr(args, "device_name", "") or "",
    ]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise RuntimeError(f"No se pudo iniciar el demonio: {exc}")
    deadline = time.time() + 4
    last = None
    while time.time() < deadline:
        try:
            return rpc_call(socket_path, {"cmd": "ping"}, 1.0)
        except Exception as exc:
            last = exc
            time.sleep(0.2)
    raise RuntimeError(f"El demonio no arrancó: {last}")


def main(argv=None):
    paths = default_paths()
    parser = argparse.ArgumentParser(description="Control de CMF Buds Pro 2")
    sub = parser.add_subparsers(dest="command")

    p_daemon = sub.add_parser("daemon")
    p_daemon.add_argument("--state", default=paths["state"])
    p_daemon.add_argument("--socket", default=paths["socket"])
    p_daemon.add_argument("--log", default=paths["log"])
    p_daemon.add_argument("--poll", type=int, default=60)
    p_daemon.add_argument("--idle-timeout", type=int, default=300)
    p_daemon.add_argument("--device-mac", default="")
    p_daemon.add_argument("--device-name", default="")

    for name in ("status", "stop", "rpc"):
        p = sub.add_parser(name)
        p.add_argument("--state", default=paths["state"])
        p.add_argument("--socket", default=paths["socket"])
        p.add_argument("--log", default=paths["log"])
        p.add_argument("payload", nargs="?")
        p.add_argument("--poll", type=int, default=60)
        p.add_argument("--idle-timeout", type=int, default=300)
        p.add_argument("--device-mac", default="")
        p.add_argument("--device-name", default="")

    args = parser.parse_args(argv)
    if args.command == "daemon":
        daemon = BudsDaemon(args)
        return daemon.run()

    if args.command == "stop":
        try:
            rpc_call(args.socket, {"cmd": "shutdown"}, 2.0)
            print(json.dumps({"ok": True}))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
        return 0

    if args.command == "rpc":
        try:
            req = json.loads(args.payload or "{}")
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"JSON inválido: {exc}"}))
            return 2
        try:
            res = rpc_call(args.socket, req)
        except Exception:
            try:
                ensure_daemon(args, paths)
                res = rpc_call(args.socket, req)
            except Exception as exc:
                print(json.dumps({"ok": False, "error": str(exc), "state": None}))
                return 1
        print(json.dumps(res, ensure_ascii=False))
        return 0

    # status
    try:
        res = rpc_call(args.socket, {"cmd": "status"})
    except Exception:
        try:
            ensure_daemon(args, paths)
            res = rpc_call(args.socket, {"cmd": "status"})
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc), "state": None}))
            return 1
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
