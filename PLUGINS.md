# Plugins de Noctalia · estado y checklist de pruebas

> Documento vivo. Marca las casillas (`[x]`) cuando pruebes que algo funciona **al 100 %**.
> Un plugin con **todas** sus casillas tachadas pasa a la cola de contribución upstream.
>
> Última actualización: **2026-10-21 17:05** (inventario tomado con las otras sesiones
> trabajando en paralelo sobre `floating-term`, `wallpaper-carousel`, `cmf-buds`,
> `lyrics-carousel`, `notes` y la app móvil).

- Repositorio personal: <https://github.com/F4M1N3C/noctalia-plugins>
- Fork de la tienda: <https://github.com/F4M1N3C/community-plugins>
- Tienda oficial (destino): <https://github.com/noctalia-dev/community-plugins>

---

## 0. Resumen · estado y bloqueos

| Plugin | Probado | Versión | Bloqueo exacto |
| --- | --- | --- | --- |
| `faminec/equalizer` | **8/8** ✅ | 1.0.0 | **Ninguno** (retirado del sistema, el código sigue publicado y verificado) |
| `faminec/floating-term` | 0/17 | 2.0.0 "Term Deck" | El tag `terminal` **no está en la lista permitida** por la tienda → el validador oficial falla (1 error). Los 3 bugs de core ya tienen rodeo en el plugin, falta probar |
| `faminec/wallpaper-carousel` | 0/16 | 2.0.0 (v2 inclinada) | La v2 está en el repo pero **sin commitear**; cambia ajustes y miniatura → hay que regenerar el `thumbnail.webp` y el README antes del PR |
| `faminec/notes` | 0/14 | 1.1.0 | El plugin ya está; falta probarlo y probar la app en el móvil. `tailscale funnel` sin activar en la cuenta |
| `faminec/cmf-buds` | 0/20 | 1.0.0 | **La rueda del ratón no llega a los `ui.slider`** (falta `wheelAdjustEnabled` en el reconciliador del core). El parche está preparado pero **no aplicado** |
| `faminec/lyrics-carousel` | 0/18 | 1.0.0 | El fix de los ajustes lostos está **solo en la copia instalada**, no en el repo. El repo tiene la versión antigua con `overrides.json` |
| `ntimer` (utilidad) | 0/9 | — | — |
| `notes-mobile` (utilidad) | 0/8 | — | Sin HTTPS estable (el túnel de Cloudflare cambia de URL) → la PWA no se instala de verdad; probar en el móvil |

**Estado de GitHub (2026-10-21 17:05):**

| Elemento | Estado |
| --- | --- |
| Repo personal `F4M1N3C/noctalia-plugins` | `main` en `7181b02` + 1 commit sin pushear (`feat(notes): add service entry for the IPC bridge`) + trabajo sin commitear de las otras sesiones |
| Fork `F4M1N3C/community-plugins` | Creado y sincronizado con `noctalia-dev/community-plugins` (`main` = `f62bad56`) |
| Ramas en el fork | `feat/cmf-buds`, `feat/equalizer`, `feat/floating-term`, `feat/lyrics-carousel`, `feat/notes`, `feat/wallpaper-carousel` — 1 commit sobre `main` de upstream, un solo directorio cada una |
| PRs abiertos | **Ninguno** |
| Cuerpos de PR | Los 6 generados y validados contra `enforce-pr-template.py` → **0 errores** (listos para abrir) |
| Validador oficial | `Validated 6 plugin manifest(s).` en el estado de las 16:07; **ahora falla 1 error** por el tag `terminal` de `floating-term` v2 |
| Conflictos de nombre con la tienda | Ninguno: `notes`, `equalizer`, `cmf-buds`, `floating-term`, `lyrics-carousel` y `wallpaper-carousel` están libres |

---

## 1. Plugins hechos

| Plugin | Id | Estado | En GitHub | Rama del fork | Probado 100 % |
| --- | --- | --- | --- | --- | --- |
| Floating Term | `faminec/floating-term` | Listo (v2.0.0 "Term Deck") | Sí | `feat/floating-term` | ☐ 0/17 |
| Wallpaper Carousel | `faminec/wallpaper-carousel` | Listo (v2.0.0, inclinada) | Sí | `feat/wallpaper-carousel` | ☐ 0/16 |
| Notes | `faminec/notes` | Listo | Sí | `feat/notes` | ☐ 0/14 |
| Notes Sync | `faminec/notes-sync` | Listo (nuevo) | No | — | ☐ 0/9 |
| CMF Buds | `faminec/cmf-buds` | Listo | Sí | `feat/cmf-buds` | ☐ 0/20 |
| Lyrics Carousel | `faminec/lyrics-carousel` | Listo | Sí | `feat/lyrics-carousel` | ☐ 0/18 |
| Equalizer | `faminec/equalizer` | Listo pero **retirado** | Sí | `feat/equalizer` | ☑ **8/8** |

### Utilidades (no son plugins)

| Utilidad | Qué es | Dónde | Estado |
| --- | --- | --- | --- |
| `ntimer` | CLI del timer de Noctalia + visor `tty-clock` | `~/.local/bin/ntimer` | Listo |
| `notes-mobile` | App web (PWA + SSE) para editar las notas desde el móvil | `~/notes-mobile` | **Listo** (repo git propio) |
| Tema navegador | Colores de Edge/Monkeytype según el wallpaper | `~/.local/bin/monkeytype-wallpaper-server` | En curso |

---

## 2. Plugins en progreso

| # | Plugin / idea | Qué falta | Prioridad |
| --- | --- | --- | --- |
| 1 | PRs a `noctalia-dev/community-plugins` | Las **6 ramas y los 6 cuerpos de PR ya están preparados**; falta la prueba manual y la aprobación del usuario | Alta |
| 2 | `floating-term` v2 "Term Deck" | Falta commitear, corregir el tag `terminal` y probar | Alta |
| 3 | `wallpaper-carousel` v2 (inclinada) | Falta commitear, regenerar miniatura y README, y probar | Alta |
| 4 | `lyrics-carousel` | Copiar al repo la versión instalada (fix de `overrides.json` + `render_mode="image"`) | Media |
| 5 | App móvil de las notas | **Hecho**: PWA instalada en el celular, sincronización en vivo verificada, push PC→celular, conflictos y respaldos. Falta decidir la URL pública estable (Funnel pide un clic en la consola de Tailscale) | Media |
| 6 | Tema del navegador según el wallpaper | Decidir el enfoque (Edge + Monkeytype) | Media |
| 7 | `pipes.sh` vs `pipies.sh` | Confirmar el nombre real del script | Baja |
| 8 | `faminec/notes-sync` | **Hecho**: plugin nuevo con widget de estado, panel y contrato IPC. Falta probarlo a mano y decidir si se sube a GitHub | Media |

---

## 3. Plugins que faltan

| # | Plugin / idea | Notas | Prioridad |
| --- | --- | --- | --- |
| 1 | Pinterest → fastfetch | Categoría de flores, quitar fondo y convertir a ASCII art | Baja |
| 2 | Barras tipo CachyOS | Todo lo posible con las barras de tareas de CachyOS | Baja |
| 3 | Teléfono como micro/cámara | Ya hay `phone-operate` (comunidad) + `phone-screen`, `phone-remote-up` | Baja |
| 4 | Automatizar Clash of Clans | **Descartado**: contra los ToS, riesgo de ban | — |

---

## 4. Lista de pruebas

Marca `[x]` solo si la función se comporta **exactamente** como esperas, sin fallos ni
pujeones. Si algo falla a medias, déjalo en `[ ]` y anótalo en §5.

### 4.1 Floating Term — `faminec/floating-term` — **0/17**

> v2.0.0 "Term Deck": tarjetas con vista previa en vivo, editor de widgets, rotación de
> ventanas y botón de abrir/cerrar todo. Los 3 bugs de core ya tienen rodeo (§5).

```sh
noctalia msg panel-toggle faminec/floating-term:panel
noctalia msg plugin faminec/floating-term:panel all launch cava
noctalia msg plugin faminec/floating-term:panel all refresh
```

- [ ] El widget de la barra abre el panel
- [ ] El panel sale pegado al icono (`attached` + `open_near_click`)
- [ ] Cada tarjeta abre su terminal en una ventana flotante
- [ ] Cada tarjeta respeta su tamaño y su posición (`layouts`)
- [ ] Si el comando ya está abierto, se enfoca y se recoloca en vez de duplicarse
- [ ] **Doble clic rápido NO abre dos ventanas** (guarda `launching`)
- [ ] El botón "abrir todo" lanza todos los comandos a la vez
- [ ] **El botón "abrir todo" con las ventanas ya abiertas las recoloca**
- [ ] El panel no se cierra al usar "abrir todo"
- [ ] El botón "cerrar todo" cierra las ventanas del plugin
- [ ] La rotación de ventanas (sentido horario / antihorario / opuesta / por pares / aleatoria) coloca bien las ventanas
- [ ] La rotación con `rotation_sizes` intercambia el ancho y el alto
- [ ] El editor de widgets añade uno **sin que desaparezcan los demás** (fix de los ajustes que se pisan)
- [ ] El botón **X** sí borra un widget que viene **por defecto** (fix de la X que no borraba)
- [ ] La vista previa de cada tarjeta (captura con `grim`) se ve
- [ ] La colisión de ventanas evita que se tapen
- [ ] `close_on_launch` cierra el panel al lanzar

### 4.2 Wallpaper Carousel — `faminec/wallpaper-carousel` — **0/16**

> v2.0.0: tarjetas **inclinadas** (paralelogramo) con miniaturas PNG con alfa.

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
noctalia msg plugin faminec/wallpaper-carousel:panel all refresh
```

- [ ] El botón de la barra abre el panel a pantalla completa
- [ ] Las miniaturas inclinadas se ven (PNG con alfa, no WebP)
- [ ] `←` `→` cambian de fondo
- [ ] La rueda del ratón cambia de fondo
- [ ] `Enter` aplica el fondo seleccionado
- [ ] `Esc` cierra el panel
- [ ] `r` reescanea la carpeta
- [ ] El recorte parallax se nota al desplazarse
- [ ] La animación es suave (no salta de golpe)
- [ ] La tarjeta seleccionada crece (`selected_scale`) y las demás encogen (`base_scale`)
- [ ] El `hover_boost` resalta la tarjeta bajo el cursor
- [ ] El modo `chrome = false` oculta cabecera y pie
- [ ] El fondo del escritorio se ve entre las tarjetas
- [ ] Al abrir no hay tirones (el presupuesto de CPU está bajo control)
- [ ] `card_width`, `card_height` y `skew` se aplican en caliente
- [ ] `scrim` atenúa el fondo de las tarjetas

### 4.3 Notes — `faminec/notes` — **0/14**

```sh
noctalia msg panel-toggle faminec/notes:panel
noctalia msg plugin faminec/notes:service all refresh
noctalia msg plugin faminec/notes:service all open-note "mi nota.md"
```

- [ ] El widget de la barra abre el panel lateral
- [ ] El panel lista las notas de `notes_dir`
- [ ] `+` crea una nota nueva
- [ ] El botón del portapapeles crea una nota con el texto copiado
- [ ] Se puede editar y guardar
- [ ] Se puede renombrar
- [ ] Se puede borrar (con confirmación)
- [ ] Se puede fijar una nota
- [ ] El scratchpad está siempre y no se borra
- [ ] El lanzador `/nt` busca notas
- [ ] El lanzador `/nt <texto>` crea una nota
- [ ] La carpeta vigilada refleja al instante los cambios externos
- [ ] El IPC `refresh` recarga el panel abierto
- [ ] El IPC `open-note` abre la nota indicada

### 4.4 CMF Buds — `faminec/cmf-buds` — **0/20**

> ⚠️ Las casillas de los **sliders de EQ** están bloqueadas por el bug de core C4.

```sh
noctalia msg panel-toggle faminec/cmf-buds:panel-sound
noctalia msg panel-toggle faminec/cmf-buds:panel-controls
noctalia msg panel-toggle faminec/cmf-buds:panel-actions
noctalia msg panel-toggle faminec/cmf-buds:panel-system
```

- [ ] El widget aparece en la barra con el icono correcto
- [ ] El tooltip muestra conexión, ANC, batería, EQ y volumen
- [ ] Clic abre el panel en la última pestaña usada
- [ ] La rueda sube y baja el volumen por `volume_step`
- [ ] El clic derecho cicla el modo de ANC
- [ ] ANC: apagado / transparencia / cancelación
- [ ] Los niveles de ANC (adaptativo, alto, medio, bajo) funcionan
- [ ] El volumen del sistema se controla desde el panel
- [ ] Los presets de EQ (Balanced, Rock, Electronic, Pop, Vocals, Classical) suenan
- [ ] El EQ personalizado (graves/medios/agudos -6..+6) funciona
- [ ] **La rueda del ratón mueve los sliders del EQ** ← bloqueado por C4
- [ ] Ultra Bass con sus 5 niveles funciona
- [ ] Los gestos de toque de cada auricular y del estuche se pueden cambiar
- [ ] "Ring my buds" busca cada auricular por separado
- [ ] Las macros del dial funcionan (SUPER + rueda = workspace)
- [ ] La macro restaura el volumen cuando toca
- [ ] Audio espacial, detección in-ear, baja latencia y conexión dual responden
- [ ] El test de ajuste arranca y muestra el resultado
- [ ] La batería de izquierda, derecha y estuche se lee
- [ ] El panel "Sistema" reconecta el dispositivo

### 4.5 Lyrics Carousel — `faminec/lyrics-carousel` — **0/18**

```sh
noctalia msg panel-toggle faminec/lyrics-carousel:panel
```

- [ ] El widget de música aparece en la barra
- [ ] El panel se abre pegado al icono
- [ ] Se abre la ventana flotante de kitty
- [ ] Lee la pista del reproductor MPRIS (título y artista)
- [ ] Encuentra la letra (LRCLIB / NetEase / SPlayer / QQ / Kugou)
- [ ] La línea activa se resalta
- [ ] El efecto karaoke ilumina carácter a carácter
- [ ] La dirección `down` / `up` se cambia desde el panel
- [ ] El marcador `>` aparece
- [ ] El visualizador de barras se activa
- [ ] El pie con el tiempo y la barra de progreso aparece
- [ ] La cabecera con título y artista aparece
- [ ] Las pistas de teclado aparecen
- [ ] `q` cierra la ventana, `espacio` pausa, `d` invierte, `k` alterna karaoke, `r` reintenta
- [ ] Los interruptores del panel **se aplican en caliente** y **coinciden con la página de Ajustes** (fix de los ajustes lostos)
- [ ] `render_mode = "image"` dibuja la letra como imagen; `render_mode = "text"` como texto
- [ ] El `accent` / `custom_color` se aplica al dibujo
- [ ] `active_scale`, `visible_above` y `visible_below` se aplican

### 4.6 Equalizer — `faminec/equalizer` (retirado del sistema) — **8/8** ✅

```sh
noctalia msg panel-toggle faminec/equalizer:panel
```

- [x] El widget aparece en la barra
- [x] El panel dibuja las 10 bandas (31, 62, 125, 250, 500, 1k, 2k, 4k, 8k, 16k)
- [x] El preamp sube y baja
- [x] El bypass funciona
- [x] Los presets se cargan
- [x] El servicio deja EasyEffects y el preset listos al iniciar la sesión
- [x] `eqctl status` / `set-band` / `set-preamp` / `bypass` / `apply` / `reset` responden
- [x] **Verificación de audio real**: +6,7 dB a 250 Hz y -9,6 dB a 4 kHz medidos con
      un tono a través del sink `easyeffects_sink`

> Retirado del sistema porque `cmf-buds` ya trae su propio ecualizador. El código sigue
> publicado y se puede volver a instalar cuando haga falta.

### 4.7 `ntimer` (utilidad) — **0/9**

```sh
ntimer 25
ntimer 25m
ntimer 90s
ntimer 1h30m
ntimer 1:30
ntimer pause
ntimer cancel
ntimer restart 25m
ntimer status
ntimer display 1h
ntimer 1h --no-display
```

- [ ] `25`, `25m`, `90s`, `1h30m` y `1:30` arrancan el temporizador
- [ ] `pause` pausa y reanuda
- [ ] `cancel` lo cancela
- [ ] `restart` reinicia con otra duración
- [ ] `status` muestra el tiempo y el estado
- [ ] `display 1h` abre el visor `tty-clock` (1200×620, centro)
- [ ] Los últimos 10 segundos se ponen en rojo
- [ ] `q` o `Esc` cierran solo el visor (el temporizador sigue)
- [ ] `--no-display` arranca el widget sin abrir la ventana

### 4.8 App móvil de las notas (`notes-mobile`) — **8/14** ✅

- [x] La PWA se instala de verdad en el Galaxy S22 (icono "Notas" en el launcher, ventana propia)
- [x] La app carga con el token correcto
- [x] Se ven las notas con vista previa
- [x] Se crea una nota desde el móvil
- [x] Se edita una nota desde el móvil
- [x] Se borra o renombra una nota desde el móvil
- [x] El panel del PC refleja los cambios al instante (SSE)
- [x] El móvil refleja al instante los cambios del PC
- [x] Funciona con **datos móviles** (WiFi apagado, red `rmnet_data7`): las 3 rutas responden 200
- [x] Se instala sobre `127.0.0.1` (contexto seguro: `adb reverse`), sin depender de HTTPS
- [x] Conflictos: si el PC cambia la nota mientras se edita, avisa y deja elegir
- [x] Push del PC al celular: el banner sale en el móvil
- [x] Hay respaldos de cada nota antes de sobrescribirla
- [ ] La URL pública con **HTTPS estable** (Tailscale Funnel) → falta tu clic en la consola

### 4.9 Notes Sync (`faminec/notes-sync`) — **6/9**

- [x] El plugin carga sin errores (`noctalia plugins lint` → 0 errores)
- [x] El panel muestra servidor, celular, cola, notas y última conexión
- [x] El widget cambia de color según el estado
- [x] Abre el panel de notas del PC
- [x] Abre una nota concreta en el panel del PC
- [x] Manda al celular la nota que está abierta (push)
- [ ] El botón "enviar" del panel se ve bien con la nota abierta
- [ ] El widget se ve bien en la barra (icono + color)
- [ ] Decidir si se sube a GitHub o se queda local

> **Descubrimiento clave**: `noctalia.state` está **aislado por plugin** (una clave
> publicada por `faminec/notes` no la ve `faminec/notes-sync`). El canal entre
> plugins es un fichero: `~/.local/state/noctalia/plugins/data/faminec/notes/current.json`.

---

## 5. Bugs de core de Noctalia que siguen bloqueando

| # | Bug | Dónde | Efecto | Estado |
| --- | --- | --- | --- | --- |
| **C1** | El ajuste `string_map` **reemplaza** el mapa entero: el override pisa el default | `src/scripting/plugin_manifest.cpp:855` `mergePluginSettings()` → `seeded.emplace(field.key, override ? override : default)` | Al guardar un `string_map` desde Ajustes, **desaparecen los demás valores** | **Rodeado en `floating-term`** (`lib/store.luau`: `defaults ⊕ config ⊕ store − removed`). Es un comportamiento de Noctalia 5.3.0, así que **afecta a cualquier plugin con `string_map`** → hay que mencionarlo en el PR |
| **C2** | El botón **X** de una clave que solo existe en el default no hace nada | `src/shell/settings/settings_control_factory.cpp:1233` `removeAndCommit()` → `clearOverride(entryPath)`: no hay override que borrar | La fila del widget por defecto sigue en la lista | **Rodeado en `floating-term`** (`lib/store.luau` → lista `removed`) |
| **C3** | `findExisting()` es asíncrono: dos clics seguidos lanzan dos ventanas | `panel.luau` (v1) → `hyprctl clients -j` no devuelve aún la ventana | Dos ventanas de kitty con la misma clase | **Rodeado en `floating-term` v2** (guarda `state.launching[class]`, `panel.luau:404`). No es un bug del core, era del plugin |
| **C4** | **`wheelAdjustEnabled` no está en el árbol declarativo**: el reconciliador nunca lo lee | `src/ui/ui_tree_reconciler.cpp:502` (falta en la lista `kSlider`) y `:1661` (falta el `setWheelAdjustEnabled`) | **La rueda del ratón no llega a los `ui.slider` de los plugins** | 🔴 **SIN RODEO**. Parche de 6 líneas preparado en `/tmp/opencode/staging/noctalia-patch/patch.diff`, **no aplicado**. El binario instalado (`noctalia 5.3.0-1.1`) **no lo trae**; el source de `main` **sí** → hay que recompilar o esperar a una release |
| **C5** | El **SSE no llega a través del túnel de Cloudflare** (llegan las cabeceras, el cuerpo nunca) | proxy de Cloudflare | La sincronía "en vivo" por la URL pública no funciona | Workaround: Tailscale Serve (`http://<host>.tailXXXX.ts.net:8787`) o `adb reverse tcp:8787 tcp:8787` |
| **C6** | `tailscale funnel` **no está habilitado** en la tailnet | consola de Tailscale (atributo ACL) | Sin HTTPS estable → la PWA no se instala de verdad (el service worker solo se registra en `https:`) | Requiere **un clic del usuario** en la consola de Tailscale |

> Nota sobre C4: el control `Slider` **sí** soporta la rueda (`src/ui/controls/slider.cpp:79` y
> `src/ui/builders.cpp:636`), y el centro de control de Noctalia **sí** lo usa
> (`src/shell/control_center/tabs/audio_tab.cpp:1079`). Lo que falta es exponerlo en el
> árbol declarativo que usan los plugins. Es un hueco de una línea en el core.

---

## 6. Lo que se ha arreglado esta noche (2026-10-21, 13:40 → 17:05)

### `floating-term` → v2.0.0 **"Term Deck"** (otra sesión)

- Reestructurado en módulos: `lib/{defaults,layout,preview,store,util,windows}.luau` +
  `bin/snapshot.py`, `panel.luau` de ~1.000 líneas.
- `plugin_api` 26 → 32, `version` 1.2.0 → 2.0.0, nombre → "Term Deck".
- **Rodeo de C1** (ajustes que se pisan): `lib/store.luau` fusiona
  `defaults ⊕ config(Ajustes) ⊕ store(panel) − removed` y lo persiste en
  `~/.local/state/noctalia/plugins/data/faminec/floating-term/store.json`.
- **Rodeo de C2** (la X no borra): `M.remove()` + lista `removed` → ahora sí se pueden
  borrar también los widgets que vienen por defecto.
- **Rodeo de C3** (doble clic duplica): guarda `state.launching[class]`.
- Nuevo: tarjetas con **vista previa en vivo** (capturas con `grim` vía `bin/snapshot.py`),
  editor de widgets (`startEditing` / `saveForm` / `deleteWidget`), botón de **cerrar todo**,
  **rotación** de ventanas (`clockwise`, `counterclockwise`, `opposite`, `pairs`, `shuffle`)
  con `rotation_sizes` para intercambiar ancho y alto.
- Se eliminó el ajuste `fonts` (ya no aplica a la v2).

### `wallpaper-carousel` → v2.0.0 (otra sesión, desde `/tmp/opencode/wc-v2`)

- Tarjetas **inclinadas** (paralelogramo) en vez de verticales.
- Miniaturas en **PNG RGBA** con alfa y recortadas en paralelogramo (`bin/thumbs.py`).
- Ajustes nuevos: `card_width`, `card_height`, `skew`, `selected_scale`, `base_scale`,
  `hover_boost`, `scrim`, `chrome`. Se eliminan `card_scale` y `gap`.

### `lyrics-carousel` (otra sesión)

- **Arreglado el bug de los ajustes lostos**: el panel ya **no** escribe `overrides.json`;
  escribe en `settings.toml` (`plugin_settings."faminec/lyrics-carousel"`) con el helper
  `bin/set-setting.py` y recarga con `noctalia msg config-reload`. Así el panel y la página
  de Ajustes muestran siempre lo mismo.
- Nuevo modo de render **`render_mode = "image"`** con `bin/image_renderer.py` y
  `bin/graphics.py`.
- Ajustes nuevos: `render_mode`, `accent`, `custom_color`, `active_scale`,
  `visible_above`, `visible_below`.

### `cmf-buds` (otra sesión)

- Paneles recolocados de `center_right` a `top_center` y alturas ajustadas
  (960 / 610 / 1040 / 950).
- `lib/panel_ui.luau` y `lib/common.luau` reescritos, `bin/budsctl.py` y
  `bin/local_actions.py` actualizados.
- Staging con `apply.sh` + copia de seguridad en `/tmp/opencode/staging`.

### `notes` (otra sesión)

- El panel solo mira **las notas y `.pinned.json`** al calcular la firma de la carpeta
  (antes cualquier archivo del directorio hacía cambiar la firma).
- `service.luau` con el puente IPC (`refresh`, `open-note`, `open-home`).

### App móvil de las notas (otra sesión)

- PWA completa: `manifest.webmanifest`, `sw.js`, iconos 192/512/maskable.
- API REST + SSE, servicio **systemd de usuario activo**.
- `adb reverse tcp:8787 tcp:8787` → el celular llega al PC **sin depender de la red**.
- Tailscale Serve → `:8787`; script `notes-mobile-url` con las dos direcciones.
- `test-api.sh` para probar la API a mano.

### Repo y tienda (esta sesión)

- `cmf-buds`, `lyrics-carousel` y `notes` publicados en `F4M1N3C/noctalia-plugins`
  (commit `72d5c20`): README con la plantilla de la tienda, miniatura 960×540, claves de
  traducción anidadas y `tags` ajustados a la lista permitida.
- Fork `F4M1N3C/community-plugins` creado y sincronizado; **6 ramas `feat/*`**, cada una
  con un solo directorio de plugin sobre `main` de upstream.
- Los **6 cuerpos de PR** generados y validados contra `enforce-pr-template.py`
  (marcador, 7 secciones obligatorias, campos, tipo de plugin, compositor y las 12
  casillas de atestación) → **0 errores**.

---

## 7. Pendiente de prueba manual por el usuario

Nada de esto se puede automatizar: necesita tus ojos y tus manos.

| # | Qué | Cómo |
| --- | --- | --- |
| 1 | Las 17 casillas de `floating-term` (§4.1) | `noctalia msg panel-toggle faminec/floating-term:panel` |
| 2 | Las 16 casillas de `wallpaper-carousel` (§4.2) | `noctalia msg panel-toggle faminec/wallpaper-carousel:panel` |
| 3 | Las 14 casillas de `notes` (§4.3) | `noctalia msg panel-toggle faminec/notes:panel` |
| 4 | Las 20 casillas de `cmf-buds` (§4.4) | `noctalia msg panel-toggle faminec/cmf-buds:panel-sound` |
| 5 | Las 18 casillas de `lyrics-carousel` (§4.5) | `noctalia msg panel-toggle faminec/lyrics-carousel:panel` |
| 6 | Las 9 casillas de `ntimer` (§4.7) | `ntimer 25m` |
| 7 | Las 8 casillas de la app móvil (§4.8) | Con el móvil conectado por `adb reverse` |
| 8 | **Activar Tailscale Funnel** en la consola | Un clic tuyo: es lo que da HTTPS estable para la PWA |
| 9 | Decidir si la v2 del carrusel entra antes del PR | Cambia miniatura y README |

---

## 8. PLUGINS PARA REVISAR

### 8.1 Al 100 % · solo falta que lo confirmes

| # | Plugin | Por qué está aquí |
| --- | --- | --- |
| 1 | `faminec/equalizer` | **8/8** probadas, con verificación de audio real (+6,7 dB / -9,6 dB). Pasa el validador y la rama `feat/equalizer` está lista. Solo se desinstaló del sistema porque `cmf-buds` trae su propio EQ. **Único bloqueo: la confirmación de que lo quieres ofrecer a la tienda.** |

### 8.2 Con pendientes · motivo exacto del bloqueo

| # | Plugin | Probado | Motivo exacto del bloqueo |
| --- | --- | --- | --- |
| 2 | `faminec/floating-term` | 0/17 | **Bloqueo duro**: el tag `terminal` de la v2 no está en la lista permitida por la tienda → el validador oficial falla con 1 error. Los 3 bugs de core (C1, C2, C3) **ya están rodeados** en el plugin, así que solo falta probarlos |
| 3 | `faminec/wallpaper-carousel` | 0/16 | La **v2 inclinada está sin commitear** en el repo y cambia los ajustes (`card_scale`/`gap` → `card_width`/`card_height`/`skew`/…), así que la **miniatura de la tienda y el README están desfasados**. Además la rama `feat/wallpaper-carousel` del fork apunta a la v1 |
| 4 | `faminec/lyrics-carousel` | 0/18 | El **fix de los ajustes lostos y el `render_mode="image"` están solo en la copia instalada**; el repo (y por tanto la rama del fork) tiene la versión antigua con `overrides.json`. Hay que copiar y revalidar |
| 5 | `faminec/cmf-buds` | 0/20 | **C4 sin rodeo**: la rueda del ratón no llega a los `ui.slider` porque el core no expone `wheelAdjustEnabled`. El parche de 6 líneas está en `/tmp/opencode/staging/noctalia-patch/patch.diff` pero **no está aplicado** y el binario instalado no lo trae. Afecta a las casillas de los sliders de EQ |
| 6 | `faminec/notes` | 0/14 | El plugin está listo y el IPC responde, pero falta **probarlo** y probar la **app en el móvil**, que necesita **Tailscale Funnel activado en tu cuenta** para tener HTTPS estable |
| 7 | `ntimer` (utilidad) | 0/9 | Sin bloqueo técnico: falta probarlo a mano |
| 8 | `notes-mobile` (utilidad) | 0/8 | Sin HTTPS estable: el túnel de Cloudflare cambia de URL en cada reinicio y el SSE no pasa por él. Workaround ya listo (`adb reverse` / Tailscale Serve) |

---

## 9. Fallos encontrados

| Plugin | Qué falla | Notas |
| --- | --- | --- |
| | | |
