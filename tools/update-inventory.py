#!/usr/bin/env python3
"""Actualiza el inventario (PLUGINS.md) con el estado real y la cola de revisión.

Uso:  python3 tools/update-inventory.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "PLUGINS.md"

STAMP = "2026-10-21 18:30"


def counts(text: str) -> dict[str, tuple[int, int]]:
    """Casillas marcadas y totales por sección ### 4.x."""
    out: dict[str, tuple[int, int]] = {}
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        title = block.splitlines()[0]
        body = block.split("\n---")[0]
        boxes = re.findall(r"^- \[( |x|X)\]", body, flags=re.M)
        if not boxes:
            continue
        key = re.search(r"`([^`]+)`", title)
        label = key.group(1) if key else title
        out[label] = (sum(1 for b in boxes if b.lower() == "x"), len(boxes))
    return out


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    data = counts(text)

    # --- 1) corregir los X/N de los encabezados de §4 ----------------------
    def fix_heading(match: re.Match) -> str:
        title = match.group(1)
        key = re.search(r"`([^`]+)`", title)
        label = key.group(1) if key else None
        if label in data:
            done, total = data[label]
            title = re.sub(r"\*\*\d+/\d+\*\*", "**%d/%d**" % (done, total), title)
        return "### " + title

    text = re.sub(r"^### (4\.\d .*)$", fix_heading, text, flags=re.M)

    # --- 2) cabecera ------------------------------------------------------
    text = re.sub(
        r"> Última actualización: \*\*[^*]+\*\*",
        "> Última actualización: **%s**" % STAMP,
        text,
        count=1,
    )
    text = text.replace(
        "> trabajando en paralelo sobre `floating-term`, `wallpaper-carousel`, `cmf-buds`,\n"
        "> `lyrics-carousel`, `notes` y la app móvil).",
        "> trabajando en paralelo sobre `floating-term`, `wallpaper-carousel`, `cmf-buds`,\n"
        "> `lyrics-carousel`, `notes`, `notes-sync` y la app móvil).",
    )

    DOC.write_text(text, encoding="utf-8")
    print("encabezados actualizados:")
    for label, (done, total) in data.items():
        print("  %-22s %d/%d" % (label, done, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
