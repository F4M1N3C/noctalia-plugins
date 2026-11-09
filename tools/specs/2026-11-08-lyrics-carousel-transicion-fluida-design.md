# Diseño: transición del carrusel fluida a 60 fps y relleno sin resplandor

**Fecha:** 2026-11-08
**Alcance:** "lo más fluida que se pueda" (acordado) + "que sea el brillo de cada letra,
sin sombra ni borde" (acordado)
**Plugin:** `lyrics-carousel`

> Este documento vive en `tools/specs/` y no en `docs/superpowers/specs/` a propósito:
> en este repo **cada directorio de primer nivel es un plugin**, así que un `docs/`
> de primer nivel rompería la convención que Noctalia y la community repo esperan.

---

## 1. Por qué este trabajo

El relevo entre renglones ya es **correcto** (tamaño gradual, color que cruza de blanco al
color principal y del color principal al gris de las cantadas, sin parpadeos). Lo que falla
es la **sensación**: el movimiento se ve a tirones.

El motivo está medido, no supuesto:

| Problema | Evidencia |
| --- | --- |
| El bucle duerme `1/60 s` **después** de dibujar, así que el ciclo real es `trabajo + 16,7 ms` | El log del plugin emite una línea cada 180 frames: en modo demo salían **cada ~5 s** ⇒ **36 fps reales**, no 60 |
| El resplandor del karaoke difumina la máscara dos veces por frame (`GaussianBlur`) | `_draw_lyrics` cuesta **5,04 ms** con resplandor y **1,85 ms** sin ⇒ **3,2 ms** solo de difuminado |
| El tamaño de fuente se cachea por `int(round(size))` | El glifo da escalones de 1 px cada ~7 frames durante el crecimiento |
| La curva `smoothstep` (3t²−2t³) | Velocidad 0 en los extremos pero **la aceleración salta** al arrancar y al frenar |

Con el ritmo actual el presupuesto de 60 fps (16,67 ms) se gasta en dormir: el trabajo real
por frame es ~5 ms de dibujo + 1,6 ms de zlib + 0,05 ms de base64 + la escritura al PTY.

## 2. Objetivos y no objetivos

**Objetivos**

1. Que el carrusel se mueva a **60 fps reales**, con ritmo regular (sin frames perdidos).
2. Que la línea cantada se vea como **el brillo de cada letra**: relleno nítido de lo
   cantado, sin halo difuminado y sin borde duro en el límite del relleno.
3. Que el **tamaño** del renglón que crece sea continuo (sin escalones de píxel).
4. Que el **arranque y el frenado** del movimiento no se noten (curva sin aceleración en
   los extremos).

**No objetivos**

- No cambia el aspecto final de la transición más allá de quitar la sombra: mismo
  recorrido, mismos colores, mismos tamaños.
- No se toca la búsqueda de letra en este documento (trabajo aparte, §6).
- No se baja la resolución nativa ni se cuantiza el color.

## 3. Decisiones

### A. Ritmo de paso fijo (`bin/lyrics-carousel`)

El bucle principal pasa de "dibujar y luego dormir 16,7 ms" a un **plazo absoluto**: cada
frame empieza en `inicio + 16,67 ms` y se duerme lo que falte.

```python
plazo = time.monotonic() + 1.0 / MOTION_FPS
... trabajo del frame ...
resto = plazo - time.monotonic()
if resto > 0:
    time.sleep(resto)
```

Además, `draw()` deja de saltarse frames por su propio intervalo: el deadline ya lo
gobierna el bucle, así que la comprobación `now - last_draw < interval` se elimina (dejaba
frames sin dibujar cuando el trabajo sepassed del plazo).

**Alternativas descartadas:** subir `MOTION_FPS` a 120 (el terminal y el ancho de banda no
dan; el coste por frame se duplicaría inútilmente) y bajar la carga bajando la resolución
(el usuario quiere nitidez nativa).

### B. Fuera el resplandor (`bin/image_renderer.py`, `_draw_karaoke`)

Se elimina la capa difuminada completa: `resplandor` (halo) y `nucleo` (brillo pegado a la
letra). Se conservan:

- la capa nítida de lo cantado (`nitido`), que es el "brillo de cada letra";
- la **rampa de alfa** en el límite del relleno: no es un borde, es lo que funde la letra
  cantada con la que falta (sin ella el corte sería en seco).

Se conservan también los colores: lo cantado en `accent`, lo pendiente en el accent
atenuado. Con karaoke apagado el renglón principal se dibuja con `_draw_centered` y su
transición de color, igual que hasta ahora.

**Efectos colaterales aceptados:** el renglón principal pierde el halo (es lo pedido) y el
salto del halo al final de la transición **desaparece solo**, porque el halo ya no existe.

### C. Tamaño de letra continuo

`ImageFont.truetype` admite tamaño fraccionario (comprobado: 25,4 y 25,5 dan anchos
distintos). La caché de fuentes pasa a indexarse por **cuarto de píxel**:

```python
key = (family, int(round(size * 4)))
```

El tamaño se redondea a 0,25 px antes de dibujar. Con el rango 25→34 px son ~37 entradas
en caché, reutilizadas en cada transición (la caché no crece sin límite).

### D. Curva `smootherstep`

`ease_in_out` pasa a `smootherstep` (6t⁵−15t⁴+10t³): velocidad **y** aceleración 0 en los
extremos. El centro de la transición acelera algo más (1,875× la media frente a 1,5×), que
es el precio de un arranque y un frenado más limpios.

Se usa **solo** para el scroll: el resto de interpolaciones del plugin no cambian. Como el
tamaño y el color del relevo se calculan con el mismo progreso, heredan la curva (el
tamaño y el color pasan a acelerar y frenar con ella).

### E. Métrica honesta

El log pasa de `draw avg: X ms (Y fps theoretical)` a informar de los **fps reales**
(frames entre timestamps) además del tiempo de dibujo, que es lo que de verdad dice si el
carrusel va fluido.

## 4. Cómo se verifica

1. **Autotest** (`bin/selftest.py`): checks nuevos para la ausencia de resplandor (la
   imagen de la línea cantada no tiene halo: los píxeles suaves alrededor del glifo son 0) y
   para el tamaño fraccionario (el ancho del texto crece de forma continua entre dos
   tamaños enteros, no a saltos).
2. **Ritmo real**: en modo demo, el log debe mostrar **~60 fps** y las líneas del log
   (una cada 180 frames) deben salir cada **~3 s**, no cada ~5 s.
3. **Coste por frame**: `_draw_lyrics` sin resplandor debe bajar de 5,04 ms a ~2 ms.
4. **Visual**: tira de fotogramas de la transición revisada con un subagente multimodal
   (continuidad de tamaño, color y ausencia de halo).
5. **Suite completa**: selftest + test-panel + `verify-plugins.py` + validador oficial de
   community-plugins.

## 5. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| 60 fps saturan el PTY (55 KB por frame ⇒ 3,3 MB/s) | Kitty lo aguanta de sobra; si se ve tirón, el log de fps reales lo delata y se baja `MOTION_FPS` |
| La caché de fuentes con claves fraccionarias crece | El rango de tamaños es finito y se reutiliza; se puede purgar si hace falta |
| Quitar el halo resta carácter al renglón principal | Es lo pedido; el relleno nítido mantiene el contraste cantado/pendiente |

## 6. Refinamiento: el relevo no oscurece de golpe (karaoke)

**Aviso del usuario:** "el renglón que está a punto de ser el principal tiene la transición
de tamaño y color, eso está bien, pero cuando llega a ser el principal inmediatamente se
oscurece un poquito; eso solamente pasa cuando está la opción de karaoke glow".

**Causa raíz.** La línea que va a ser principal se dibuja con `_draw_centered`: un solo
color que va de blanco al **acento** (rojo vivo). Al volverse principal, la ruta del
karaoke la dibuja en **dos tonos**: lo cantado en el acento y lo que falta en un rojo
apagado (`mix(acento, fondo, 0.45)`). Como el relleno arranca en 0, toda la línea pasa de
golpe al rojo apagado: ese es el oscurecimiento instantáneo. Solo ocurre con "Karaoke
glow" porque es la única ruta que pinta la línea principal en dos tonos.

**Decisión.** Con el karaoke activo, la entrante hace su transición de color normal
(blanco → acento) **y encima** una transición de oscuridad: del nivel que tienen los
renglones siguientes (sin oscurecer) al tono apagado de lo pendiente del renglón principal.

```python
color = self._lerp(inicio, accent, progress)              # transición de color
color = self._lerp(color, apagado, progress)               # transición de oscuridad
```

El camino resultante es blanco → acento → rojo apagado (monótono en brillo) y la línea
llega al centro ya con el tono que tendrá: el relevo queda continuo. Sin karaoke no
cambia nada. El tono apagado se calcula en un único sitio
(`ImageRenderer._karaoke_pendiente`), que usan tanto la ruta del karaoke como la
entrante, para que no puedan divergir.

**Verificación.** Test nuevo `check_entrada_karaoke_sin_salto` (rojo antes, verde después):
la entrante con karaoke termina en el tono apagado; ese tono es exactamente el del
renglón principal sin cantar; la entrante se oscurece de forma continua; y sin karaoke
sigue terminando en el acento.

## 7. Trabajo siguiente (fuera de este documento)

Mejora permanente de la **búsqueda de letra**: canciones con letra errada o que no se
encuentra cuando la canción sí la tiene. Se hará su propio documento de diseño tras
reconocer el pipeline actual (fuentes, emparejamiento, validación y reintentos).
