#!/usr/bin/env python3
"""Comprueba que los callbacks del carrusel no se pasan del presupuesto de CPU.

El shell aborta un callback que se pasa de su presupuesto (25 ms) y deja el
panel a medias (la galeria sin pintar). El plugin mide su propio coste con
os.clock() y lo deja en el log como "wc-budget ... cost=X ms"; este script lo
comprueba (y abre el panel si se le pide, para tener datos frescos).

Uso:
  bin/check-callback-budget.py            # mide lo que haya en el log
  bin/check-callback-budget.py --open     # abre y cierra el panel y lo mide
  bin/check-callback-budget.py --budget 20

Sale con codigo 1 si algun callback se pasa del presupuesto.
"""

import argparse
import os
import re
import subprocess
import sys
import time

LOG = os.path.expanduser("~/.cache/noctalia/noctalia.log")
PANEL = "faminec/wallpaper-carousel:panel"
COST = re.compile(r"wc-budget\s+(?P<name>[a-zA-Z ]+?)\s+cost=(?P<cost>[0-9.]+)\s*ms")


def read_costs(path):
    """Devuelve [(nombre, ms)] de las marcas de presupuesto del log."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if "wc-budget" not in line:
                    continue
                m = COST.search(line)
                if m:
                    out.append((m.group("name").strip(), float(m.group("cost"))))
    except OSError:
        return out
    return out


def open_and_close(rounds=3):
    for _ in range(rounds):
        subprocess.run(["noctalia", "msg", "panel-toggle", PANEL],
                       capture_output=True, check=False)
        time.sleep(2.5)
        subprocess.run(["noctalia", "msg", "panel-toggle", PANEL],
                       capture_output=True, check=False)
        time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=15.0,
                    help="presupuesto por callback en ms (el del shell son 25)")
    ap.add_argument("--open", action="store_true",
                    help="abre y cierra el panel antes de medir")
    ap.add_argument("--log", default=LOG)
    args = ap.parse_args()

    if args.open:
        open_and_close()

    if not os.path.exists(args.log):
        print("no hay log en %s" % args.log, file=sys.stderr)
        return 1

    costs = read_costs(args.log)
    if not costs:
        print("no hay marcas de presupuesto en el log: abre el panel primero")
        return 1

    fallos = 0
    peor = 0.0
    print("presupuesto: %.1f ms (el del shell son 25)" % args.budget)
    for name, ms in costs[-40:]:
        estado = "OK " if ms <= args.budget else "MAL"
        peor = max(peor, ms)
        print("  %s %-18s %7.2f ms" % (estado, name, ms))
        if ms > args.budget:
            fallos += 1

    if fallos:
        print("FALLO: %d callbacks se pasan del presupuesto (peor: %.1f ms)"
              % (fallos, peor), file=sys.stderr)
        return 1
    print("todos los callbacks dentro del presupuesto (peor: %.1f ms)" % peor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
