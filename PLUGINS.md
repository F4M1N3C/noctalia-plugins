# Plugins de Noctalia · estado y lista de pruebas

> Documento vivo. Marca las casillas (`[x]`) cuando pruebes que algo funciona **al 100 %**.
> Un plugin con todas sus casillas tachadas pasa a la cola de contribución upstream.

- Repositorio personal: <https://github.com/F4M1N3C/noctalia-plugins>
- Tienda oficial (destino): <https://github.com/noctalia-dev/community-plugins>
- Última actualización: **2026-10-21**

---

## 1. Plugins hechos

| Plugin | Id | Estado | En GitHub | PR upstream | Probado 100 % |
| --- | --- | --- | --- | --- | --- |
| Floating Term | `faminec/floating-term` | Listo | Sí | Pendiente | ☐ |
| Wallpaper Carousel | `faminec/wallpaper-carousel` | Listo | Sí | Pendiente | ☐ |
| Notes | `faminec/notes` | Listo | Sí | Pendiente | ☐ |
| CMF Buds | `faminec/cmf-buds` | Listo | Sí | Pendiente | ☐ |
| Lyrics Carousel | `faminec/lyrics-carousel` | Listo | Sí | Pendiente | ☐ |
| Equalizer | `faminec/equalizer` | Listo pero **retirado** | Sí | Pendiente | ☑ (verificado con prueba de audio real) |

### Utilidades (no son plugins)

| Utilidad | Qué es | Dónde | Estado |
| --- | --- | --- | --- |
| `ntimer` | CLI del timer de Noctalia + visor `tty-clock` | `~/.local/bin/ntimer` | Listo |
| `notes-mobile` | App web para editar las notas desde el móvil | `~/notes-mobile` | En curso |
| Tema navegador | Colores de Edge/Monkeytype según el wallpaper | `~/.local/bin/monkeytype-wallpaper-server` | En curso |

---

## 2. Plugins en progreso

| # | Plugin / idea | Qué falta | Prioridad |
| --- | --- | --- | --- |
| 1 | PRs a `noctalia-dev/community-plugins` | Abrir un PR por plugin, con el checklist del repositorio filled | Alta |
| 2 | App móvil de las notas | La parte del teléfono (el plugin ya sincroniza) | Media |
| 3 | Tema del navegador según el wallpaper | Decidir el enfoque (Edge + Monkeytype) | Media |
| 4 | Miniatura / README de la tienda | Hecho el 2026-10-21: ambos plugins nuevos ya los tienen | — |
| 5 | `pipes.sh` vs `pipies.sh` | Confirmar el nombre real del script | Baja |

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

### 4.1 Floating Term — `faminec/floating-term`

```sh
noctalia msg panel-toggle faminec/floating-term:panel
noctalia msg plugin faminec/floating-term:panel all launch cava
noctalia msg plugin faminec/floating-term:panel all refresh
```

- [ ] El widget de la barra abre el panel
- [ ] El panel sale pegado al icono (`attached` + `open_near_click`)
- [ ] Cada comando abre su terminal en una ventana flotante
- [ ] Cada comando respeta su tamaño y su posición (`layouts`)
- [ ] Si el comando ya está abierto, se enfoca y se recoloca en vez de duplicarse
- [ ] El botón de "abrir todo" lanza todos los comandos a la vez
- [ ] **El botón de "abrir todo" con las ventanas ya abiertas las recoloca**
- [ ] El panel no se cierra al usar "abrir todo"
- [ ] La fuente por comando (`fonts`) se aplica en kitty
- [ ] `close_on_launch` cierra el panel al lanzar
- [ ] `margin` y `output` (monitor) se respetan
- [ ] La resolución de colisiones evita que las ventanas se tapen
- [ ] Los atajos del carrusel de letras funcionan (`q`, `espacio`, `d`, `k`, `r`)

### 4.2 Wallpaper Carousel — `faminec/wallpaper-carousel`

```sh
noctalia msg panel-toggle faminec/wallpaper-carousel:panel
noctalia msg plugin faminec/wallpaper-carousel:panel all refresh
```

- [ ] El botón de la barra abre el panel a pantalla completa
- [ ] Las miniaturas se ven (son JPEG, no WebP)
- [ ] `←` `→` cambian de fondo
- [ ] La rueda del ratón cambia de fondo
- [ ] `Enter` aplica el fondo seleccionado
- [ ] `Esc` cierra el panel
- [ ] `r` reescanea la carpeta
- [ ] El recorte parallax se nota al desplazarse
- [ ] La animación es suave (no salta de golpe)
- [ ] `visible = 0` reparte las tarjetas por todo el ancho
- [ ] El modo minimalista oculta cabecera y pie
- [ ] El fondo del escritorio se ve entre las tarjetas
- [ ] Al abrir no hay tirones (el presupuesto de CPU está bajo control)
- [ ] Las miniaturas del entorno ya están en caché al desplazarse
- [ ] `card_scale`, `gap` y `parallax` se aplican en caliente

### 4.3 Notes — `faminec/notes`

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
- [ ] El scratchpad está siempre y no se borra
- [ ] El lanzador `/nt` busca notas
- [ ] El lanzador `/nt <texto>` crea una nota
- [ ] La carpeta vigilada refleja al instante los cambios externos
- [ ] El IPC `refresh` recarga el panel abierto
- [ ] El IPC `open-note` abre la nota indicada
- [ ] El IPC `open-home` vuelve a la lista

### 4.4 CMF Buds — `faminec/cmf-buds`

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
- [ ] Ultra Bass con sus 5 niveles funciona
- [ ] Los gestos de toque de cada auricular y del estuche se pueden cambiar
- [ ] "Ring my buds" busca cada auricular por separado
- [ ] Las macros del dial funcionan (SUPER + rueda = workspace)
- [ ] La macro restaura el volumen cuando toca
- [ ] Audio espacial, detección in-ear, baja latencia y conexión dual responden
- [ ] El test de ajuste arranca y muestra el resultado
- [ ] La batería de izquierda, derecha y estuche se lee
- [ ] El panel "Sistema" reconecta el dispositivo

### 4.5 Lyrics Carousel — `faminec/lyrics-carousel`

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
- [ ] Los interruptores del panel se aplican en caliente
- [ ] Cambiar la tipografía reinicia la ventana con la nueva fuente
- [ ] `offset_ms` afina la sincronía
- [ ] `anchor`, `width` y `height` colocan la ventana

### 4.6 Equalizer — `faminec/equalizer` (retirado del sistema)

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

### 4.7 `ntimer` (utilidad)

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

### 4.8 App móvil de las notas (`notes-mobile`)

- [ ] El túnel de Cloudflare aguanta la sesión
- [ ] La app web carga en el móvil
- [ ] Se ven las notas
- [ ] Se crea una nota desde el móvil
- [ ] Se edita una nota desde el móvil
- [ ] Se borra o renombra una nota desde el móvil
- [ ] El panel del PC refleja los cambios al instante
- [ ] La app cambia de tema con el wallpaper

---

## 5. Fallos encontrados

Anota aquí lo que falle al probar, para no perderlo:

| Plugin | Qué falla | Notas |
| --- | --- | --- |
| | | |

---

## 6. Cola de contribución upstream

Cuando un plugin tenga **todas** sus casillas tachadas, se abre un PR contra
`noctalia-dev/community-plugins` (un plugin por PR, como exige la tienda):

- [ ] `faminec/floating-term`
- [ ] `faminec/wallpaper-carousel`
- [ ] `faminec/notes`
- [ ] `faminec/cmf-buds`
- [ ] `faminec/lyrics-carousel`
- [ ] `faminec/equalizer`

Cada PR necesita:

- [ ] El directorio contiene `plugin.toml`, `README.md`, `thumbnail.webp` y `translations/en.json`
- [ ] El `README.md` sigue la plantilla de la tienda y documenta todas las entradas
- [ ] `thumbnail.webp` es WebP de 960×540
- [ ] `version` con semver y subida, `plugin_api` es el nivel más bajo que hace falta
- [ ] `catalog.toml` **no** se toca (lo genera la CI)
- [ ] El PR toca **un solo** directorio de plugin
