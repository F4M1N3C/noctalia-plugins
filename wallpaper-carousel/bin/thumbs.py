#!/usr/bin/env python3
"""Generate skewed wallpaper cards for the Noctalia wallpaper carousel.

The reference carousel (reddit.com/r/hyprland/comments/1vjqvrr, by
u/HyperSpazdik, and github.com/motor-dev/wallpaperCarousel) draws every
wallpaper as a parallelogram leaning to the right, so the row reads as a 3D
ribbon.  Noctalia's declarative UI has no transform props, so the shear is
baked into the thumbnail: the wallpaper is drawn upright and masked with the
parallelogram, and the result is stored as an RGBA PNG.

The plugin passes one JSON file describing the pending cards.  Keeping the
whole batch in a single process avoids paying Python/Pillow startup for every
card and lets JPEGs decode through Pillow's draft mode at a useful size.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageOps


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalized_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        source = os.path.expanduser(str(raw["source"]))
        output = os.path.expanduser(str(raw["output"]))
        width = int(raw["width"])
        height = int(raw["height"])
        offset = clamp(float(raw.get("offset", 0.0)), -1.0, 1.0)
        zoom = max(1.0, min(2.0, float(raw.get("zoom", 1.35))))
        skew = clamp(float(raw.get("skew", 0.35)), -0.9, 0.9)
        darken = clamp(float(raw.get("darken", 0.0)), 0.0, 1.0)
    except (KeyError, TypeError, ValueError):
        return None
    if width < 16 or height < 16 or not os.path.isfile(source):
        return None
    return {
        "source": source,
        "output": output,
        "width": width,
        "height": height,
        "offset": offset,
        "zoom": zoom,
        "skew": skew,
        "darken": darken,
    }


def render(item: dict[str, Any]) -> None:
    source = item["source"]
    output = item["output"]
    width = item["width"]
    height = item["height"]
    offset = item["offset"]
    zoom = item["zoom"]
    skew = item["skew"]
    darken = item["darken"]

    # Si la miniatura ya está en caché no se vuelve a generar: así el plugin
    # puede pedir un rango amplio de tarjetas sin repetir trabajo.
    if os.path.exists(output):
        return

    os.makedirs(os.path.dirname(output), exist_ok=True)
    temp = output + ".tmp"

    with Image.open(source) as opened:
        # Ask JPEG decoders for a smaller frame before loading the full 4K
        # source.  The final crop is at most a few hundred pixels wide.
        try:
            opened.draft("RGB", (int(width * zoom * 1.5), int(height * zoom * 1.5)))
        except Exception:
            pass
        image = ImageOps.exif_transpose(opened)
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Scale to cover a canvas slightly larger than the card, then slide the
        # crop window horizontally according to the card's position.  This is the
        # parallax: left cards reveal the left side, right cards the right side.
        virtual_width = width * zoom
        virtual_height = height * zoom
        scale = max(virtual_width / image.width, virtual_height / image.height)
        scaled_width = max(width, math.ceil(image.width * scale))
        scaled_height = max(height, math.ceil(image.height * scale))
        image = image.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

        extra_x = max(0, scaled_width - width)
        extra_y = max(0, scaled_height - height)
        left = int(round(extra_x * (0.5 + 0.45 * offset)))
        top = int(round(extra_y * 0.5))
        image = image.crop((left, top, left + width, top + height))

        if darken > 0:
            # Composite over black instead of using ImageEnhance so the result
            # is predictable and doesn't shift saturation.
            black = Image.new("RGB", image.size, (0, 0, 0))
            image = Image.blend(image, black, darken)

        # The parallelogram.  The card leans to the right: its bottom edge is
        # shifted left by `skew * height` pixels, so the shape is the sheared
        # rectangle [skew*height, width] x [0, height]:
        #
        #     top-left  (skew*h, 0)      top-right    (width, 0)
        #     bottom-left (0, height)    bottom-right (width - skew*h, height)
        #
        # Everything outside it is transparent, which is what makes the row
        # read as a skewed ribbon instead of a plain strip of rectangles.
        shift = skew * height
        canvas = image.convert("RGBA")
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(
            [
                (shift, 0.0),
                (float(width), 0.0),
                (float(width) - shift, float(height)),
                (0.0, float(height)),
            ],
            fill=255,
        )
        canvas.putalpha(mask)

        # PNG, not WebP: Noctalia's image loader only ships the JPEG, PNG and
        # SVG handlers, so a WebP would render as an empty placeholder.
        canvas.save(temp, "PNG", optimize=True)
    os.replace(temp, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", help="JSON file with a list of thumbnail jobs")
    args = parser.parse_args()

    try:
        with open(args.batch, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"could not read batch: {error}", file=sys.stderr)
        return 2

    if not isinstance(payload, list):
        print("batch must be a JSON array", file=sys.stderr)
        return 2

    done = 0
    failed = 0
    for raw in payload:
        if not isinstance(raw, dict):
            failed += 1
            continue
        item = normalized_item(raw)
        if item is None:
            failed += 1
            continue
        try:
            render(item)
            done += 1
        except Exception as error:  # noqa: BLE001 - report and keep the batch alive
            failed += 1
            print(f"{item['source']}: {error}", file=sys.stderr)

    print(json.dumps({"done": done, "failed": failed}))
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
