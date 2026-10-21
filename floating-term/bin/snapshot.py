#!/usr/bin/env python3
"""Capturas de las ventanas flotantes para el panel de Noctalia.

El plugin escribe un JSON con las zonas que quiere capturar y este script las
toma con `grim` (la zona de la salida donde vive la ventana) y las recorta al
tamaño de la miniatura.

Cada elemento del lote:

    {
      "output": "DP-1",      # conector de la salida (opcional)
      "x": 120, "y": 140,     # origen de la zona, relativo a la salida
      "w": 900, "h": 520,     # tamaño de la zona
      "width": 320,           # tamaño final de la miniatura
      "height": 190,
      "out": "/ruta/thumb.png"
    }
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def output_scale(output: str) -> float:
    """Factor de escala de la salida (Hyprland), 1.0 si no se puede saber."""
    try:
        result = subprocess.run(
            ["hyprctl", "monitors", "-j"],
            capture_output=True,
            text=True,
            timeout=4.0,
        )
        monitors = json.loads(result.stdout)
    except Exception:  # noqa: BLE001 - sin hyprctl se asume escala 1
        return 1.0
    if not isinstance(monitors, list):
        return 1.0
    for monitor in monitors:
        if isinstance(monitor, dict) and monitor.get("name") == output:
            try:
                return float(monitor.get("scale") or 1.0)
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def capture(item: dict) -> None:
    out = str(item["out"])
    x = int(item["x"])
    y = int(item["y"])
    w = int(item["w"])
    h = int(item["h"])
    target_w = max(16, int(item.get("width", 320)))
    target_h = max(16, int(item.get("height", 190)))

    if w <= 0 or h <= 0:
        raise ValueError("ventana sin tamaño")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix="fterm-", suffix=".png")
    os.close(handle)

    command = ["grim"]
    output = item.get("output")
    if output:
        # `grim` no admite `-o` y `-g` a la vez: si se indica la salida se
        # captura entera y el recorte se hace aquí, con Pillow.
        command += ["-o", str(output), raw]
    else:
        command += ["-g", f"{x},{y} {w}x{h}", raw]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        from PIL import Image

        with Image.open(raw) as image:
            image = image.convert("RGB")
            if output:
                # Recorte manual: la captura viene a la escala de la salida,
                # mientras que la zona está en coordenadas lógicas.
                scale = output_scale(output)
                if scale != 1.0:
                    box = (
                        int(round(x * scale)),
                        int(round(y * scale)),
                        int(round((x + w) * scale)),
                        int(round((y + h) * scale)),
                    )
                    box = (
                        max(0, box[0]),
                        max(0, box[1]),
                        min(image.width, box[2]),
                        min(image.height, box[3]),
                    )
                    if box[2] > box[0] and box[3] > box[1]:
                        image = image.crop(box)
            if image.size != (target_w, target_h):
                image = image.resize((target_w, target_h), Image.LANCZOS)
            image.save(out)
    finally:
        try:
            os.unlink(raw)
        except OSError:
            pass


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: snapshot.py <lote.json>", file=sys.stderr)
        return 2

    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        items = json.load(handle)

    failures = 0
    for item in items:
        try:
            capture(item)
        except Exception as exc:  # noqa: BLE001 - un fallo no debe parar el lote
            failures += 1
            print(f"snapshot: {item.get('out')}: {exc}", file=sys.stderr)

    return 1 if failures and failures == len(items) else 0


if __name__ == "__main__":
    sys.exit(main())
