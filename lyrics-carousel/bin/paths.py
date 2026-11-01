"""Rutas del estado de Noctalia que usa el plugin.

El settings.toml y los overrides viven en el directorio de estado de
Noctalia. Ese directorio cambia si el usuario mueve el estado con
NOCTALIA_STATE_HOME o XDG_STATE_HOME: si el plugin no lo respeta, leeria
(y escribiria) los ajustes de otra instalacion.

Este modulo lo usan el script y el helper: las dos piezas tienen que
buscar exactamente el mismo sitio o una escribiria donde la otra lee.
"""

from __future__ import annotations

import os

PLUGIN_ID = "faminec/lyrics-carousel"


def state_dir() -> str:
    """Directorio de estado de Noctalia (el que contiene settings.toml).

    Noctalia usa la raiz del estado como si fuera el HOME: con
    NOCTALIA_STATE_HOME o XDG_STATE_HOME, el settings.toml queda en
    <raiz>/noctalia/settings.toml.
    """
    # LYRICS_CAROUSEL_STATE manda sobre todo lo demas: es el gancho que
    # usan las pruebas para apuntar a un directorio temporal.
    directo = os.environ.get("LYRICS_CAROUSEL_STATE", "").strip()
    if directo:
        return os.path.expanduser(directo)
    base = (
        os.environ.get("NOCTALIA_STATE_HOME", "").strip()
        or os.environ.get("XDG_STATE_HOME", "").strip()
        or os.path.expanduser("~/.local/state")
    )
    return os.path.join(os.path.expanduser(base), "noctalia")


def settings_path() -> str:
    """Ruta del settings.toml de Noctalia."""
    return os.path.join(state_dir(), "settings.toml")


def data_dir() -> str:
    """Directorio de datos del plugin (donde vive overrides.json)."""
    return os.path.join(state_dir(), "plugins", "data", *PLUGIN_ID.split("/"))


def overrides_path() -> str:
    """Ruta del fichero de overrides.

    Se puede redirigir con LYRICS_CAROUSEL_OVERRIDES (la usa el autotest
    para no tocar el estado real). Una variable vacia se ignora: si no, la
    ruta seria "" y no se podria leer nada.
    """
    alternativa = os.environ.get("LYRICS_CAROUSEL_OVERRIDES", "").strip()
    if alternativa:
        return os.path.expanduser(alternativa)
    return os.path.join(data_dir(), "overrides.json")
