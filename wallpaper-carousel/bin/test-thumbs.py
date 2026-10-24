#!/usr/bin/env python3
"""Regression tests for bin/thumbs.py (card shapes and cache behaviour)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "thumbs.py")

checks = 0
failures = 0


def check(condition: bool, message: str) -> None:
    global checks, failures
    checks += 1
    if not condition:
        failures += 1
        print(f"FAIL: {message}", file=sys.stderr)


def alpha(image: Image.Image, x: int, y: int) -> int:
    return image.getpixel((x, y))[3]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "wallpaper.png")
        Image.new("RGB", (200, 200), (160, 90, 40)).save(source)

        width, height = 120, 160
        jobs = []
        outputs = {}
        for shape in ("skew", "rect", "square", "triangle", "ellipse", "banana"):
            output = os.path.join(tmp, f"{shape}.png")
            outputs[shape] = output
            jobs.append(
                {
                    "source": source,
                    "output": output,
                    "width": width,
                    "height": height,
                    "offset": 0.0,
                    "zoom": 1.35,
                    "skew": 0.35,
                    "shape": shape,
                }
            )
        batch = os.path.join(tmp, "batch.json")
        with open(batch, "w", encoding="utf-8") as handle:
            json.dump(jobs, handle)

        result = subprocess.run(
            [sys.executable, HELPER, batch], capture_output=True, text=True, check=False
        )
        check(result.returncode == 0, f"helper exits 0, got {result.returncode}: {result.stderr}")

        for shape, path in outputs.items():
            check(os.path.isfile(path), f"{shape}: output exists")
            if not os.path.isfile(path):
                continue
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            check(image.size == (width, height), f"{shape}: keeps the card size")

        def corner(shape: str, x: int, y: int) -> int:
            with Image.open(outputs[shape]) as opened:
                return alpha(opened.convert("RGBA"), x, y)

        check(corner("rect", 1, 1) == 255, "rect: top-left is opaque")
        check(corner("square", 2, 2) == 0, "square: outside the square is transparent")
        check(corner("square", 60, 80) == 255, "square: the centre stays opaque")
        check(corner("triangle", 2, 2) == 0, "triangle: top-left corner is transparent")
        check(corner("triangle", 60, 150) == 255, "triangle: the base is opaque")
        check(corner("ellipse", 2, 2) == 0, "ellipse: corner is transparent")
        check(corner("ellipse", 60, 80) == 255, "ellipse: the centre stays opaque")
        check(corner("skew", 2, 2) == 0, "skew: top-left corner is transparent")
        check(corner("skew", 60, 80) == 255, "skew: the centre stays opaque")
        check(corner("banana", 2, 2) == 0, "unknown shape falls back to skew")

        # Cache: a second run must not rewrite existing thumbnails.
        before = {path: os.stat(path).st_mtime_ns for path in outputs.values()}
        result = subprocess.run(
            [sys.executable, HELPER, batch], capture_output=True, text=True, check=False
        )
        check(result.returncode == 0, "second run exits 0")
        for path, stamp in before.items():
            check(os.stat(path).st_mtime_ns == stamp, f"cached thumbnail is not rewritten: {os.path.basename(path)}")

        # Parallax: left and right crops differ.
        left = os.path.join(tmp, "left.png")
        right = os.path.join(tmp, "right.png")
        wide = os.path.join(tmp, "wide.png")
        Image.new("RGB", (600, 200), (0, 0, 0)).save(wide)
        # Paint the left third red and the right third blue so the crops differ.
        with Image.open(wide) as opened:
            painted = opened.convert("RGB")
        for x in range(600):
            for y in range(200):
                if x < 200:
                    painted.putpixel((x, y), (255, 0, 0))
                elif x >= 400:
                    painted.putpixel((x, y), (0, 0, 255))
        painted.save(wide)
        jobs = [
            {
                "source": wide,
                "output": left,
                "width": width,
                "height": height,
                "offset": -1.0,
                "skew": 0.0,
                "shape": "rect",
            },
            {
                "source": wide,
                "output": right,
                "width": width,
                "height": height,
                "offset": 1.0,
                "skew": 0.0,
                "shape": "rect",
            },
        ]
        with open(batch, "w", encoding="utf-8") as handle:
            json.dump(jobs, handle)
        subprocess.run([sys.executable, HELPER, batch], check=True)
        with Image.open(left) as opened:
            left_pixel = opened.convert("RGB").getpixel((10, 80))
        with Image.open(right) as opened:
            right_pixel = opened.convert("RGB").getpixel((10, 80))
        check(left_pixel != right_pixel, "parallax buckets produce different crops")

    if failures:
        print(f"{failures}/{checks} checks failed", file=sys.stderr)
        return 1
    print(f"{checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
