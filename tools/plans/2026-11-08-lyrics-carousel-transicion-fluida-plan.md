# Plan: transición del carrusel fluida a 60 fps y relleno sin resplandor

> **Para agentes:** SUB-SKILL OBLIGATORIA: usar superpowers:executing-plans (o
> superpowers:subagent-driven-development) para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para seguir el avance.

**Objetivo:** que el carrusel se mueva a 60 fps reales con ritmo regular y que la línea
cantada se vea como el brillo de cada letra, sin halo difuminado.

**Arquitectura:** cuatro cambios pequeños e independientes: (1) el bucle principal pasa a
ritmo de paso fijo, con el plazo contado desde el inicio del frame; (2) `_draw_karaoke`
deja de componer la capa difuminada y se queda con el relleno nítido; (3) la caché de
fuentes pasa a indexar por cuartos de píxel para que el tamaño sea continuo; (4) la curva
del scroll pasa a `smootherstep`. Todo lo verificable queda en funciones puras para que
el autotest las pueda comprobar sin terminal.

**Stack:** Python 3 (Pillow), Lua 5.4 (panel), bash (validadores).

**Spec:** `tools/specs/2026-11-08-lyrics-carousel-transicion-fluida-design.md`

## Restricciones globales

- La resolución de la imagen es **nativa** (1200×820): no se baja ni se escala.
- El bucle late a **60 Hz** (`MOTION_FPS`); no se sube a 120.
- La ventana de la transición sigue siendo `GHOST_SECONDS = 0.9 s`, recortada al 80 % del
  hueco hasta la línea siguiente.
- El relleno de lo cantado se mantiene con su **rampa de alfa** en el límite (sin borde
  duro); lo que desaparece es el halo difuminado.
- Nada de lo que se toca puede dejar el renglón principal invisible (fue el bug de la
  versión anterior).
- Todo cambio de comportamiento va con su test en `bin/selftest.py` **antes** del código.

## Foco de revisión

1. **Línea siguiente muy cerca** (hueco < 1,2 s): la anticipación se recorta al 80 % del
   hueco; con 60 fps la transición puede caer dentro de una ventana más corta y el
   movimiento tiene que seguir siendo continuo, sin saltos.
2. **Karaoke apagado**: el renglón principal se dibuja por `_draw_centered`, no por
   `_draw_karaoke`; el crecimiento gradual y el cambio de color tienen que seguir igual y
   no debe aparecer halo en esa ruta.
3. **Cambio de tipografía desde el panel**: `invalidate_fonts()` vacía la caché; con
   claves fraccionarias la caché debe seguir siendo correcta (mismo tamaño ⇒ misma
   fuente).
4. **Sentido "up"**: la entrante viene de abajo y la saliente sube; ritmo y curvas iguales.
5. **Ventana estrecha**: `fit_text` recorta el texto; el tamaño fraccionario no debe romper
   el recorte ni el ancho máximo.

---

### Tarea 1: Ritmo de paso fijo (60 fps reales)

**Ficheros:**
- Modificar: `lyrics-carousel/bin/lyrics-carousel` (bucle principal ~línea 2500 y `draw()`
  ~línea 2378)
- Test: `lyrics-carousel/bin/selftest.py`

**Interfaces:**
- Produce: `resto_para_siguiente_frame(inicio: float, ahora: float, intervalo: float) -> float`
  (función de módulo) y `fps_real(frames: int, segundos: float) -> float` (función de módulo).

- [ ] **Paso 1: escribir el test que falla**

En `bin/selftest.py`, una función nueva `check_ritmo_de_frames()` que importa el script con
`script_module()` y comprueba:

```python
mod = script_module()
resto = mod.resto_para_siguiente_frame
intervalo = 1.0 / 60.0
check("el plazo se cuenta desde el inicio del frame",
      abs(resto(0.0, 0.008, intervalo) - (intervalo - 0.008)) < 1e-9,
      repr(resto(0.0, 0.008, intervalo)))
check("un frame a tiempo duerme lo que falta",
      abs(resto(0.0, 0.0, intervalo) - intervalo) < 1e-9)
check("un frame tardío no duerme",
      resto(0.0, 0.05, intervalo) == 0.0)
check("los fps reales se calculan sobre el tiempo entre frames",
      abs(mod.fps_real(180, 3.0) - 60.0) < 1e-9
      and mod.fps_real(0, 1.0) == 0.0)
```

y registrar la llamada en `main()` junto a las demás comprobaciones.

- [ ] **Paso 2: ejecutar el test y ver que falla**

`cd /home/faminec/noctalia-plugins && PYTHONDONTWRITEBYTECODE=1 python3 lyrics-carousel/bin/selftest.py --verbose | grep FALLO`
→ debe fallar con `AttributeError` (las funciones no existen todavía).

- [ ] **Paso 3: implementar las dos funciones puras**

En `bin/lyrics-carousel`, junto a `ease_in_out` (~línea 191):

```python
def resto_para_siguiente_frame(inicio: float, ahora: float, intervalo: float) -> float:
    """Cuánto falta para el siguiente frame con ritmo de paso fijo.

    El plazo se cuenta desde el INICIO del frame: si el frame ha tardado 8 ms
    de un intervalo de 16,7 ms solo se duermen 8,7 ms. Dormir el intervalo
    entero DESPUÉS del trabajo hacía que el ciclo real fuera
    `trabajo + intervalo`: 36 fps en vez de 60.
    """
    return max(0.0, inicio + intervalo - ahora)


def fps_real(frames: int, segundos: float) -> float:
    """Frames por segundo de verdad: frames entre el tiempo que ha pasado."""
    if segundos <= 0:
        return 0.0
    return frames / segundos
```

- [ ] **Paso 4: aplicar el ritmo de paso fijo en el bucle**

En el bucle principal (`bin/lyrics-carousel`, ~línea 2515): guardar `inicio_frame =
time.monotonic()` **antes** de `self.check_manual_resize()` y sustituir el `time.sleep(1.0
/ MOTION_FPS)` final por:

```python
                resto = resto_para_siguiente_frame(
                    inicio_frame, time.monotonic(), 1.0 / MOTION_FPS
                )
                if resto > 0:
                    time.sleep(resto)
```

En `draw()` (~línea 2378): **quitar** el salto por intervalo
(`if not force and now - self.last_draw < interval: return` y el `self.last_draw = now`),
porque ahora el plazo lo gobierna el bucle y ese salto solo servía para descartar frames.

- [ ] **Paso 5: cambiar la métrica del log a fps reales**

En el bloque de estadísticas de `draw()` (~línea 2390): acumular también el instante en el
que se empezó la ventana y logar los fps **reales**:

```python
            if self._draw_frames % 180 == 0:
                avg = self._draw_accum / self._draw_frames
                fps = fps_real(self._draw_frames, ahora - self._draw_desde)
                self.warn(f"draw avg: {avg:.1f}ms | {fps:.0f} fps reales")
                self._draw_accum = 0
                self._draw_frames = 0
                self._draw_desde = ahora
```

`self._draw_desde` se inicializa a `time.monotonic()` al entrar en el bloque por primera
vez (con `getattr`, como ya se hace con `_draw_accum`).

- [ ] **Paso 6: ejecutar el test y la suite**

`PYTHONDONTWRITEBYTECODE=1 python3 lyrics-carousel/bin/selftest.py` → 0 fallos.
`lua5.4 lyrics-carousel/bin/test-panel.lua lyrics-carousel/panel.luau` → 204 correctas.

- [ ] **Paso 7: commit**

```bash
git add lyrics-carousel/bin/lyrics-carousel lyrics-carousel/bin/selftest.py
git commit -m "perf(lyrics-carousel): ritmo de paso fijo a 60 fps reales"
```

---

### Tarea 2: Fuera el resplandor del karaoke

**Ficheros:**
- Modificar: `lyrics-carousel/bin/image_renderer.py` (`_draw_karaoke`, ~líneas 142-301)
- Test: `lyrics-carousel/bin/selftest.py`

**Interfaces:**
- Consume: `_draw_karaoke(self, draw, text, center_y, size, sung, unsung, amount, family)`
  (sin cambios en la firma).
- Produce: la misma firma; el resultado es la **misma letra** pero sin halo difuminado.

- [ ] **Paso 1: escribir el test que falla**

En `bin/selftest.py`, una función nueva `check_karaoke_sin_resplandor()`:

```python
mod = image_module()
if mod.Image is None:
    check("el karaoke sin resplandor se puede medir (Pillow)", False, "sin Pillow")
    return

texto = "cantando"
imagen = mod.Image.new("RGBA", (600, 90), (0, 0, 0, 0))
pincel = mod.ImageDraw.Draw(imagen)
renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
renderer.fonts = {}
renderer.font_files = {"prueba": mod.FALLBACK_FONT}
renderer._draw_karaoke(pincel, texto, 45, 20, (0, 200, 0), (0, 90, 0), len(texto), "prueba")

# La caja del texto: el halo vive fuera de ella.
caja = pincel.textbbox((0, 45), texto, font=renderer.font("prueba", 20), anchor="lm")
margen = 2
izq, arr, der, aba = caja[0] - margen, caja[1] - margen, caja[2] + margen, caja[3] + margen
fuera = 0
for px in pixeles(imagen):
    if px[3] > 0 and (px[0] < caja[0] - 2 or px[0] > caja[2] + 2
                      or px[1] < caja[1] - 2 or px[1] > caja[3] + 2):
        fuera += 1
check("el karaoke no deja halo alrededor de la letra", fuera == 0, "pixeles=%d" % fuera)
check("la letra cantada sigue pintada",
      sum(1 for px in pixeles(imagen) if px[1] == 200 and px[3] == 255) > 0)
```

- [ ] **Paso 2: ejecutar el test y ver que falla**

→ `fuera` sale **mayor que 0** (el halo difuminado se sale de la caja del texto).

- [ ] **Paso 3: quitar la capa difuminada**

En `_draw_karaoke` (`bin/image_renderer.py`):

- borrar el bloque del halo: `forma`, `mascara`, la función `difusa`, `resplandor`,
  `nucleo` y el `base.alpha_composite(Image.alpha_composite(resplandor, nucleo), (box[0], box[1]))`;
- borrar `radio` y `pad` (ya no se usan) y el `box` si queda sin uso;
- **conservar** la capa nítida `nitido`, la `rampa` de alfa del borde del relleno y el
  `base.alpha_composite(nitido, (box[0], box[1]))`;
- quitar `ImageFilter` del `import` de Pillow si deja de usarse en el fichero (comprobar
  con `grep -n ImageFilter image_renderer.py`).

- [ ] **Paso 4: ejecutar el test y la suite**

→ el test nuevo pasa y el total queda en 0 fallos.

- [ ] **Paso 5: commit**

```bash
git add lyrics-carousel/bin/image_renderer.py lyrics-carousel/bin/selftest.py
git commit -m "feat(lyrics-carousel): el karaoke es el brillo de la letra, sin resplandor"
```

---

### Tarea 3: Tamaño de letra continuo

**Ficheros:**
- Modificar: `lyrics-carousel/bin/graphics.py` (`load_font`, ~línea 149)
- Modificar: `lyrics-carousel/bin/image_renderer.py` (`ImageRenderer.font`, ~línea 80)
- Test: `lyrics-carousel/bin/selftest.py`

**Interfaces:**
- Produce: `load_font(path: str, size: float)` acepta tamaño fraccionario (antes `int`).
- Produce: `ImageRenderer.font(family, size)` cachea por `(family, int(round(size * 4)))` y
  devuelve la fuente del tamaño **cuartel de píxel** más cercano.

- [ ] **Paso 1: escribir el test que falla**

En `bin/selftest.py`, `check_tamano_fraccionario()`:

```python
mod = image_module()
renderer = mod.ImageRenderer.__new__(mod.ImageRenderer)
renderer.fonts = {}
renderer.font_files = {"prueba": mod.FALLBACK_FONT}
imagen = mod.Image.new("RGBA", (600, 90), (0, 0, 0, 0))
pincel = mod.ImageDraw.Draw(imagen)
ancho = lambda tam: pincel.textlength("Hola", font=renderer.font("prueba", tam))
a, b = ancho(25.4), ancho(25.6)
check("el tamaño de la letra es continuo, no escalonado",
      abs(a - b) > 0.5, "ancho=%.2f/%.2f" % (a, b))
check("la caché distingue tamaños distintos",
      renderer.font("prueba", 25.4) is not renderer.font("prueba", 25.6))
check("la caché reutiliza el mismo tamaño",
      renderer.font("prueba", 25.4) is renderer.font("prueba", 25.45))
```

- [ ] **Paso 2: ejecutar el test y ver que falla**

→ con la caché por entero, `25.4` y `25.6` dan la misma fuente ⇒ el ancho no cambia ⇒
FALLA.

- [ ] **Paso 3: permitir tamaño fraccionario en `load_font`**

En `bin/graphics.py`:

```python
def load_font(path: str, size: float):
    if Image is None or not path:
        return None
    try:
        return ImageFont.truetype(path, max(1.0, float(size)))
    except OSError:
        return None
```

- [ ] **Paso 4: cachear por cuartos de píxel**

En `bin/image_renderer.py`:

```python
    def font(self, family: str, size: float):
        # El tamaño se guarda en cuartos de píxel: la letra crece de forma
        # continua (sin escalones de 1 px) y la caché no crece sin límite.
        key = (family, int(round(size * 4)))
        font = self.fonts.get(key)
        if font is None:
            font = load_font(self.font_file(family), key[1] / 4.0)
            self.fonts[key] = font
        return font
```

- [ ] **Paso 5: ejecutar el test y la suite**

→ 0 fallos. Comprobar además que `fit_text` sigue recortando bien con tamaño
fraccionario (el autotest de la geometría lo cubre).

- [ ] **Paso 6: commit**

```bash
git add lyrics-carousel/bin/graphics.py lyrics-carousel/bin/image_renderer.py lyrics-carousel/bin/selftest.py
git commit -m "feat(lyrics-carousel): tamaño de letra continuo (cuartos de píxel)"
```

---

### Tarea 4: Curva smootherstep para el scroll

**Ficheros:**
- Modificar: `lyrics-carousel/bin/lyrics-carousel` (`ease_in_out`, ~línea 191)
- Test: `lyrics-carousel/bin/selftest.py`

**Interfaces:**
- Produce: `ease_in_out(progress: float) -> float` con la curva smootherstep
  (6t⁵−15t⁴+10t³). Se usa **solo** en `scroll_state` (verificado: no hay más usos).

- [ ] **Paso 1: escribir el test que falla**

En `bin/selftest.py`, `check_curva_suave()`:

```python
mod = script_module()
curva = mod.ease_in_out
h = 1e-3
segunda = lambda t: (curva(t + h) - 2 * curva(t) + curva(t - h)) / (h * h)
check("la curva va de 0 a 1", curva(0.0) == 0.0 and curva(1.0) == 1.0)
check("la curva no tiene aceleración en los extremos",
      abs(segunda(0.0)) < 0.05 and abs(segunda(1.0)) < 0.05,
      "inicio=%.3f fin=%.3f" % (segunda(0.0), segunda(1.0)))
check("la curva es monótona",
      all(curva(i / 20.0) <= curva((i + 1) / 20.0) for i in range(20)))
```

- [ ] **Paso 2: ejecutar el test y ver que falla**

→ con `smoothstep` la segunda derivada en los extremos vale ~3 ⇒ FALLA.

- [ ] **Paso 3: cambiar la curva**

```python
def ease_in_out(progress: float) -> float:
    """Curva suave: empieza y termina sin velocidad **ni aceleración**.

    Es la smootherstep (6t⁵−15t⁴+10t³). La anterior (smoothstep) frenaba
    bien pero la aceleración saltaba al arrancar y al frenar, y eso se notaba
    como un micro-tirón en el carrusel.
    """
    value = clamp(progress, 0.0, 1.0)
    return value**3 * (value * (value * 6.0 - 15.0) + 10.0)
```

- [ ] **Paso 4: ejecutar el test y la suite**

→ 0 fallos. El test existente `check_transicion_real` (que comprueba
`progress ≈ 0.5` en mitad y la curva arrancando/terminando despacio) debe seguir
en verde: con smootherstep el punto medio sigue siendo 0.5.

- [ ] **Paso 5: commit**

```bash
git add lyrics-carousel/bin/lyrics-carousel lyrics-carousel/bin/selftest.py
git commit -m "feat(lyrics-carousel): curva smootherstep para el relevo"
```

---

### Tarea 5: Verificación final, despliegue y documentación

**Ficheros:**
- Modificar: `lyrics-carousel/README.md` (si describe el resplandor del karaoke)
- Test: `lyrics-carousel/bin/selftest.py` (suite completa)

- [ ] **Paso 1: suite completa**

```bash
cd /home/faminec/noctalia-plugins
PYTHONDONTWRITEBYTECODE=1 python3 lyrics-carousel/bin/selftest.py
lua5.4 lyrics-carousel/bin/test-panel.lua lyrics-carousel/panel.luau
python3 tools/verify-plugins.py --no-ui
bash tools/validate-community.sh lyrics-carousel
```

→ todo en verde, sin errores ni avisos inesperados.

- [ ] **Paso 2: comprobar en vivo el ritmo real**

Lanzar el plugin en modo demo y leer el log:

```bash
cd /home/faminec && nohup kitty --class noctalia-lyrics-carousel --title lyrics \
  -e sh -lc "python3 ~/.local/share/noctalia/plugins/lyrics-carousel/bin/lyrics-carousel --demo" &
sleep 15 && tail -4 ~/.cache/lyrics-carousel/debug.log
```

→ las líneas del log deben decir **~60 fps reales** y salir cada **~3 s** (antes: ~5 s y
36 fps). Después cerrar esa ventana y relanzar el plugin normal.

- [ ] **Paso 3: revisión visual de la transición**

Generar una tira de fotogramas de la transición (como la de
`/tmp/opencode/tira_transicion.py`) y pasársela a un subagente multimodal para que
compruebe: tamaño continuo, color continuo, **sin halo** alrededor de la letra y sin
saltos entre fotogramas.

- [ ] **Paso 4: desplegar**

```bash
cd /home/faminec/noctalia-plugins/lyrics-carousel
rm -rf bin/__pycache__
rsync -a --delete ./ ~/.local/share/noctalia/plugins/lyrics-carousel/
rm -rf ~/.local/share/noctalia/plugins/lyrics-carousel/bin/__pycache__
```

- [ ] **Paso 5: documentar y commitear**

Actualizar el README si menciona el resplandor y commitear el resto.

---

## Self-review

- **Cobertura del spec:** A → Tarea 1 (ritmo) + Tarea 1 (métrica, §3.E); B → Tarea 2;
  C → Tarea 3; D → Tarea 4; verificación → Tarea 5. §4 del spec (cómo se verifica) está
  repartido en los pasos de cada tarea.
- **Coherencia de tipos:** `resto_para_siguiente_frame` y `fps_real` se producen en la
  Tarea 1 y se consumen en ella y en la Tarea 5; `load_font` cambia de `int` a `float` en
  la Tarea 3 y solo lo consume `ImageRenderer.font`.
- **Foco de revisión:** (1) hueco corto → Tarea 4 y el test existente
  `check_transicion_real`; (2) karaoke apagado → la ruta `_draw_centered` no cambia, y el
  test de la Tarea 2 mide `_draw_karaoke` directamente; (3) cambio de tipografía →
  `invalidate_fonts()` sigue vaciando la caché entera, sin cambios; (4) sentido "up" →
  el test `check_transicion_visual_fluida` ya cubre "up"; (5) ventana estrecha →
  `fit_text` no cambia y el test de geometría sigue en verde.
- **Proporción:** 5 tareas, 30 pasos; el plan no transcribe el código de los ficheros
  modificados, solo las funciones y las aserciones nuevas.
