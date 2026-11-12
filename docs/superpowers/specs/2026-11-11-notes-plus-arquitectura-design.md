# Diseño · Notes Plus (Notas del PC ↔ celular)

> Fecha: 2026-11-11. Estado: **propuesto**, pendiente de aprobación.
> Alcance: decidir la arquitectura de `notes-plus` para que **cualquier persona
> con los mismos requisitos** pueda ver sus notas del computador desde el celular.

---

## 1. Intención y por qué

La meta es que cualquier usuario de Noctalia pueda **ver, editar, crear, renombrar,
fijar y borrar** sus notas del computador **desde el celular**, y viceversa, sin
depender de que el plugin "Notes" oficial cambie ni de que el usuario℃
instale un fork a mano.

Esto no es solo "sincronizar archivos". Un `.md` en una carpeta ya se puede
sincronizar con Syncthing. Lo que la gente quiere es **controlar el panel de
notas del escritorio desde el teléfono**: que lo que escribo en el celular
aparezca en el panel, que "abrir esta nota en el PC" funcione, que el panel del
PC se entere de los cambios externos.

## 2. Hechos verificados (no supuestos)

Todo lo de esta sección se comprobó en el código, no de memoria.

### 2.1 El plugin oficial y cómo se modifica

| Hecho | Evidencia |
|---|---|
| `noctalia/notes` vive en `noctalia-dev/official-plugins` | repo clonado, `notes/plugin.toml` con `id = "noctalia/notes"` |
| Ese repo **sí acepta PRs externos sobre plugins oficiales** | 3 PRs de `Yocraft-2000` fusionados en `notes/`: #61 (hover, corner radius), #106 (botón de cerrar), #127 (Documents localizado) |
| Parchear la copia local **no sirve** | `plugin_manager.cpp:materializeGitPlugin` borra y reexporta el árbol en cada actualización → se pierde |
| El oficial **no expone `onIpc`** | `grep -rn onIpc notes/` → 0 resultados; el `plugin_ipc.cpp:166` responde `"matched plugin entry has no onIpc callback"` |
| `noctalia.state` **está aislado por plugin** | `plugin_state_store.cpp` indexa por `pluginId`; `luau_host.cpp:2669` usa `m_pluginId`, derivado del runtime name (`luau_host.cpp:2197`) |
| El oficial **sí** tiene un canal de cambios externos, pero **interno** | `panel.luau:537 onExternalChange()` + `panel.luau:559 noctalia.state.watch("notes_bump", ...)`. La clave `notes_bump` la sube **el launcher del mismo plugin** (`launcher.luau:60-65`). Otro plugin no puede escribir en ese espacio |

**Consecuencia:** un plugin Community **no puede** por sí solo hacer que el panel
oficial refresque en vivo, ni que abra una nota concreta. Necesita un punto de
extensión que el oficial hoy no da.

### 2.2 Estado real de `notes-plus` (lo que ya existe)

- Es un **fork** del oficial: 403 líneas divergentes en `panel.luau`.
- Añade `onIpc` (2 ficheros), `setUpdateInterval` (3 ficheros), watcher de
  directorio, vista de sync y `service.luau` (puente al servidor).
- **Ya está desactualizado respecto al oficial:** el oficial fusionó `dirs.luau` +
  `$XDG_DOCUMENTS_DIR` (PR #127, 2026-10-21) y el fork **no lo tiene**. Aquí no
  se rompe porque `XDG_DOCUMENTS_DIR="$HOME/Documents"`, pero en un sistema en
  español el oficial abriría `~/Documentos/Notes` y el fork `~/Documents/Notes`.
- Instalado en `~/.local/share/noctalia/plugins/notes-plus/` y **idéntico al
  fuente** (`diff -rq` limpio).
- El servidor `~/notes-mobile` está **activo** y responde HTTP 200. PWA con SSE,
  cola offline, resolución de conflictos, token por cookie, 98 pruebas de API.

### 2.3 Lo que ya funciona sin tocar nada

- `noctalia msg panel-open <plugin>:<panel>` funciona contra **cualquier** plugin
  (`panel_manager.cpp:3082-3126`). Abrir el panel oficial desde el celular **ya
  es posible hoy**.
- **`panel-open`/`panel-toggle` aceptan un contexto** y lo pasan a `onOpen(context)`
  del plugin (`panel_manager.cpp:3108-3113` → `plugin_panel.cpp:242`
  `enqueueCallStrings("onOpen", context, ...)`). El oficial **hoy ignora** el
  contexto (`function onOpen(_context)`), pero **el mecanismo ya existe**.
- El servidor de `notes-mobile` **escribe los archivos directamente** y además
  avisa al plugin por `noctalia msg plugin ...`. El teléfono ya crea, edita,
  renombra, fija y borra notas.
- El oficial ya tiene `onExternalChange()` para plegar cambios externos al editor,
  pero solo lo dispara su **propio launcher** vía `notes_bump`.

### 2.4 Hallazgo crítico: PR #149 ya está en marcha

Existe una PR **abierta** en `noctalia-dev/official-plugins`:

> **#149 · `feat(notes): open the panel in a context via panel-open/panel-toggle`**
> — Yocraft-2000, abierto el 2026-11-09. Acepta contextos `scratchpad`, `home`,
> `list`, `note:<nombre>` y `<nombre>`.

El mismo autor ya tiene **3 PRs fusionados** en `notes/` (#61, #106, #127). Es
decir: **la vía "abrir una nota concreta" ya está en marcha upstream y no la
debemos duplicar.** Además resuelve un detalle: `panel-open` sobre un panel
**ya abierto** con contexto distinto **cambia la vista in-place**, sin cerrar.

Consecuencia: nuestro **PR 2 (`onIpc` con `open-note`) sobra**. El contexto de
`panel-open` lo cubre, y mejor.

### 2.5 Hallazgo crítico: existe una pérdida silenciosa de datos

Verificado en `notes/panel.luau` (oficial) y en el fork:

```lua
local function flush()
  if not dirty or current == nil then return end
  local ok, err = noctalia.writeFile(notePath(current), buffer)  -- pisa, sin preguntar
```

`flush()` **escribe siempre**, sin comprobar si el archivo cambió por fuera
entre la carga y el autoguardado. El autoguardado corre a los 2 ticks de
inactividad (`update()` → `flush()`), y el panel ya tiene tick de 1 s
(`panel.setWantsSecondTicks(true)`).

Y `onExternalChange()` **no salva**: cuando el buffer está `dirty` y el
archivo cambió por fuera, solo actualiza `loadedContent` y deja el buffer del
PC. El siguiente `flush()` **pisa lo que escribió el móvil**.

**El servidor no lo detecta**: su control de concurrencia (409 + `rev`) solo
protege las escrituras que pasan por la API (móvil→disco). El autoguardado del
PC va **directo al archivo**, así que el servidor ve un cambio externo normal
y no un conflicto.

Esto no es un detalle de implementación: es **la función central del producto
rota en la mitad PC→móvil**, y hoy existe igual en el oficial y en el fork.

### 2.6 Restricciones que condicionan el diseño

| Restricción | Evidencia |
|---|---|
| **Un solo plugin por id** | `plugin_registry.cpp:96`: "One plugin runs per id — no duplicate providers/services/IPC" |
| **El IPC no devuelve valores** | `plugin_ipc.cpp:167` solo responde `ok: dispatched N` / `error: ...`. No hay vuelta de datos |
| **`noctalia.state` no cruza plugins** | `plugin_state_store.cpp` indexa por `pluginId` |
| **El servidor no resuelve `$XDG_DOCUMENTS_DIR`** | `server.js:63 expandPath` solo expande `~`. El oficial sí lo resuelve (`dirs.luau`) |
| **El widget del oficial ya existe** | `notes/notes.luau` → `[widget.notes] type = "noctalia/notes:notes"` en tu `settings.toml:828`. El fork añade otro → **hoy tienes 2 widgets de notas en la barra** (`settings.toml:828` y `:882`) |
| **Un plugin puede empaquetar un motor externo** | Precedente: `lyrics-carousel` lleva `bin/*.py` y arranca su motor |
| **La rama por defecto del repo oficial es `main`** | `origin/HEAD -> origin/main`. Ojo: el repo de *skills* usa `dev`; el de plugins usa `main` |

---

## 3. Objetivos, no-objetivos y anti-objetivos

### Objetivos
1. Cualquiera con Noctalia + un celular puede tener sus notas del PC a mano.
2. Cero mantenimiento de un fork: los cambios del oficial se heredan solos.
3. Instalación simple: el plugin se instala desde la tienda; el puente se
   configura con un token.
4. Que el plugin oficial mejore para **toda** la comunidad, no solo para nosotros.

### No-objetivos
- No reescribir el panel de notas desde cero (el oficial ya está bien hecho y
 Translate-mantenido).
- No meter configuración personal (token, URL, SSE) dentro del plugin oficial.
- No ser un reemplazo del oficial: el oficial sigue siendo el editor.

### Anti-objetivos (fallarían aunque "funcione")
- **Duplicar la UI de notas** en dos plugins que compiten en la barra. El
  usuario vería dos widgets de notas y no sabría cuál usar.
- **Que la función dependa de que un PR nuestro sea aceptado.** Si el plugin de
  la tienda no funciona sin un PR pendiente upstream, está muerto.
- **Romper a quien usa el oficial tal cual.** Quien no quiere sincronización no
  debe notar nada.

---

## 4. Enfoques considerados

### A. Seguir con el fork (`notes-plus` completo, ya existente)

- **Qué es:** publicar el fork actual en la tienda Community como plugin
  independiente.
- **A favor:** ya funciona, control total, no depende de nadie.
- **En contra:** (1) el fork ya se atrasó una vez y volverá a atrasarse;
  (2) duplica la UI → dos widgets de notas en la barra; (3) como propuesta de
  tienda es débil: "¿por qué no uso el oficial?"; (4) exige un servidor externo
  al que el usuario promedio no llega solo.

### B. Arriba lo genérico + abajo el puente como plugin aparte — **ELEGIDO**

- **Qué es:** tres piezas con responsabilidades separadas.
  1. **PR a `noctalia-dev/official-plugins`** con lo **genérico** que el oficial
     necesita de todos modos:
     - **PR 1 · `watch_external_changes`** (ajuste `bool`, default `false`): el
       panel sondea la firma de la carpeta (nombres + tamaño + mtime) y llama a
       `onExternalChange()` cuando cambia. El tick de 1 s **ya existe**
       (`panel.setWantsSecondTicks(true)`), así que el diff es pequeño.
     - **PR 2 · guardado que no pisa cambios externos**: `flush()` compara la
       revisión del archivo con la que se cargó y, si divergió, **no escribe**:
       avisa y deja que el usuario decida. Sin este PR, el producto pierde datos
       (§2.5) y no es publicable.
     - **NO ~~PR con `onIpc`/`open-note`~~**: PR #149 ya lo cubre (§2.4).
       Duplicarlo sería tonto y sonaría a robo de trabajo.
  2. **Plugin Community `notes-sync`** = **solo puente**, sin panel propio:
     un `service.luau` que habla con el servidor y un widget de estado. **No
     duplica la UI.** Se apoya en el oficial para la edición.
  3. **`notes-mobile` (servidor Node)** sigue siendo repo aparte, pero ahora
     habla con **`noctalia/notes`** (el oficial), no con nuestro plugin.
- **A favor:** cero UI duplicada, cero deriva, el refresco en vivo y el guardado
  seguro benefician a **toda** la comunidad (Syncthing, editores, git), y
  nuestro plugin se queda pequeño y mantenible.
- **En contra:** dependemos de la latencia de upstream; hay que mantener el fork
  como puente provisional hasta que entren los PRs.
- **Por qué se elige:** cumple los 4 objetivos, evita los 4 anti-objetivos, y
  **arregla un bug real de pérdida de datos** que hoy afecta a todos los que
  usan Notes con Syncthing.

### C. No tocar el oficial; solo el servidor

- **Qué es:** el servidor escribe los archivos; el panel oficial se entera al
  reabrirlo.
- **A favor:** cero mantenimiento, cero PRs, cero riesgo upstream.
- **En contra:** sin refresco en vivo; **y el bug de §2.5 sigue ahí**, así que
  el móvil puede perder cambios. Un plugin puente no puede ni hablar con el
  oficial: `noctalia.state` está aislado y no hay `onIpc`.
- **Cuándo sería la correcta:** si upstream rechaza los PRs. Es el plan B.

### D. Todo en el plugin oficial (incluido el puente con token y SSE)

- **Qué es:** meter la configuración personal (URL del servidor, token, push)
  dentro del oficial.
- **A favor:** un solo plugin.
- **En contra:** **rechazable de entrada.** El repo oficial es para plugins
  mantenidos por el equipo core, sin configuración personal de terceros. Además
  ata a todos los usuarios a una infraestructura que solo tiene sentido para
  quien sincroniza con un celular.
- **Descartado.**

---

## 5. Arquitectura elegida

```
┌─────────────────────────── PC ───────────────────────────┐
│                                                            │
│  noctalia/notes  (OFICIAL, con 2 PRs nuestros)            │
│    · watch_external_changes → refresca lista/editor         │
│    · onIpc: refresh | open-note                            │
│              ▲                                             │
│              │ IPC (noctalia msg plugin ...)               │
│              │                                             │
│  faminec/notes-plus  (PLUGIN COMMUNITY — solo puente)     │
│    · service.luau: habla con el servidor, expone estado    │
│    · widget: estado de sync (icono en la barra)             │
│    · SIN panel propio, SIN copia de la UI                   │
│              ▲                                             │
│              │ HTTP + SSE (localhost:8787)                 │
│              │                                             │
│  notes-mobile (servidor Node, repo aparte)                 │
│    · API REST + SSE + PWA                                  │
│    · escribe los .md directamente                           │
│    · cola offline, conflictos, token por cookie            │
└────────────────────────────┼───────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Celular (PWA)  │
                    │  ver/editar/    │
                    │  crear/renombrar│
                    └─────────────────┘
```

### Pieza 1 — PRs al plugin oficial (`noctalia-dev/official-plugins`)

Dos PRs pequeños e independientes, ambos en el estilo de los ya aceptados. Se
apuntan a **`main`** (la rama por defecto de ese repo).

**PR 1 · `watch_external_changes`** (ajuste `bool`, default `false`)
- Cuando está activo, el panel sondea la firma de la carpeta (nombres + tamaño +
  mtime) en el tick de 1 s que **ya tiene** y llama a `onExternalChange()` cuando
  cambia.
- **Genérico**: sirve para Syncthing, editores externos, git, y este caso.
- Riesgo: bajo. No cambia el comportamiento por defecto.

**PR 2 · guardado que no pisa cambios externos** (corrección de bug)
- `flush()` compara la revisión del archivo con la que se cargó (`loadedContent`).
  Si divergió y el buffer local tiene cambios sin guardar, **no escribe**:
  avisa y deja que el usuario elija.
- **Genérico**: hoy cualquiera que edite una nota en dos sitios pierde una
  versión. Es un bug, no una feature.
- Es el PR **más importante** de los dos: sin él, el producto pierde datos.

> **No se propone un PR con `onIpc`/`open-note`.** PR #149 (abierta, del autor de
> los 3 PRs ya fusionados en `notes/`) ya resuelve "abrir una nota concreta" vía
> el contexto de `panel-open`/`panel-toggle`. Cuando entre, el puente usará
> `noctalia msg panel-open noctalia/notes:panel "note:<nombre>"`.

### Pieza 2 — `notes-sync` como plugin puente

- `service.luau`: mantiene la conexión con el servidor, expone el estado y
  acepta comandos IPC. **No tiene panel de edición.**
- `widget.luau`: un icono en la barra con el estado de la sync. Glifo de nube,
  inequívoco frente al de notas.
- El servidor `notes-mobile` apunta a **`noctalia/notes`** (el oficial), no a
  nuestro plugin, para todo lo que sea abrir/refrescar una nota.
- Id nuevo: `faminec/notes-sync`. El id `faminec/notes-plus` queda retirado
  (solo un plugin corre por id → `plugin_registry.cpp:96`).

### Pieza 3 — El fork actual, reencogido y luego retirado

`notes-plus` (el fork) deja de ser un fork en cuanto PR 1 y PR 2 entren. El
panel del fork se borra y solo queda el puente. Mientras tanto, el fork sigue
siendo el puente provisional (con su propio panel), y se reduce en dos pasos
explícitos, no de golpe.

### Pieza 4 — `notes-mobile` pasa a hablar con el oficial

El servidor hoy avisa a `faminec/notes-plus:service`. Al migrar:

- **`plugin_id`** → `noctalia/notes` (para `refresh` y `open-note`).
- **`notes_dir` / `extension`** → se leen de `[plugin_settings."noctalia/notes"]`.
- **El servidor debe resolver `$XDG_DOCUMENTS_DIR`** como hace `dirs.luau`: hoy
  su `expandPath` solo expande `~`, y con el oficial el default es
  `$XDG_DOCUMENTS_DIR/Notes`. Sin esto, en un sistema en español el móvil
  escribiría en `~/Documents/Notes` y el panel leería `~/Documentos/Notes`:
  **desincronización silenciosa**.
- **El `current.json`** (canal entre el panel y el service del fork) se
  **elimina**: al encoger el plugin, el service queda en otro `pluginId` y no ve
  el `pluginDataDir` del panel. Las funciones que dependían de él
  (`send-current`, el push de la nota abierta) **se recortan** o se resuelven
  con un canal nuevo.

---

## 6. Migración de los datos

- Las notas son `.md` planos en `~/Documents/Notes` (o `$XDG_DOCUMENTS_DIR/Notes`).
  **No hay migración de datos**: es el mismo formato que el oficial.
- Los pines viven en `.pinned.json` dentro de la carpeta. El fork lo usa igual
  que el oficial → **los pines sobreviven al cambio de plugin**.
- El `notes_dir` por defecto del fork (`~/Documents/Notes`) **no** coincide con
  el del oficial (`$XDG_DOCUMENTS_DIR/Notes`). Al encoger el plugin hay que
  **portar `dirs.luau` del oficial**, o la carpeta cambia bajo los pies del
  usuario en sistemas localizados.
- El `settings.toml` tiene dos widgets de notas hoy (`noctalia/notes:notes` y
  `faminec/notes-plus:widget`). Al migrar hay que **quitar el widget del fork**
  y dejar el del oficial, más el de estado del puente (glifo de nube).

## 7. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Pérdida silenciosa de datos** (§2.5) | **Crítico**: es la función central | PR 2 al oficial (no pisar cambios externos). Es un bug real que ya afecta a todos, no solo a nosotros |
| Upstream rechaza los PRs | Alto | Plan C: el puente habla con el **fork** desplegado; se documenta la configuración de 2 plugins |
| PR #149 se cae o se retrasa | Medio | "Abrir nota concreta" queda para después; el resto (refresco, sync) no depende de él |
| El usuario tiene un Noctalia viejo | Medio: no hay `watch_external_changes` | El puente detecta que el ajuste no existe y avisa en el widget con un mensaje claro |
| Dos widgets de notas en la barra | Medio | El widget del puente es un icono de **nube/sync**, no un editor. Se documenta que se quite el del fork |
| Desincronización por `$XDG_DOCUMENTS_DIR` | Alto: móvil y PC en carpetas distintas | El servidor resuelve la variable igual que `dirs.luau` (Pieza 4) |
| Conflicto de edición simultánea | Parcialmente resuelto | El servidor resuelve móvil→API con 409 + `rev`. PC→directo al archivo lo arregla PR 2 |

## 8. Fuera de alcance (fase siguiente)

- Publicar el plugin en la tienda Community (PR con el cuerpo y las etiquetas
  que exige el validador).
- Activar Tailscale Funnel para una URL HTTPS estable (requiere una acción
  manual del usuario).
- El `server_url`/`token` como configuración por instalador (hoy en
  `settings.toml` y `config.json`).

## 9. Decisiones tomadas (ya resueltas)

### 9.1 `send-current` y push de la nota abierta: **SE MANTIENEN**

Decisión: **no se recortan**, y no hace falta un tercer PR upstream.

El `current.json` actual vive en el `pluginDataDir()` del plugin, y por eso
muere cuando el panel y el servicio son plugins distintos. La solución **no es
un PR upstream**: es **cambiar el canal**.

- **Nuevo canal: un fichero dentro de la carpeta de notas.** El oficial ya
  guarda ahí `.pinned.json` (el sidecar de los fijados), así que hay
  precedente: **`.current.json`**, escrito de forma atómica (temporal + rename),
  con `{name, content, open}`.
- **Ventaja**: la carpeta de notas ya es el punto de encuentro entre el
  computador y el celular. El servidor `notes-mobile` la lee y escribe; el
  plugin la lee. **Funciona entre plugins distintos y entre repos distintos.**
- **El servicio** (que vivirá en `faminec/notes-sync`) lee `.current.json` de la
  carpeta de notas → `send-current` y `push` siguen funcionando aunque el
  editor sea el oficial.
- **El oficial no necesita saber nada**: quien publica `.current.json` es el
  panel. Mientras el editor sea el fork, lo publica el fork. Si más adelante
  el oficial lo publica, mejor — pero **no es un requisito**.

### 9.2 Dónde se publica: **repo personal primero, tienda Community después**

Decisión: **nada sale a GitHub todavía.**

- Todo vive en el monorepo local `~/noctalia-plugins` y en `~/notes-mobile`
  (repo git propio).
- **El usuario prueba y avisa.** Cuando confirme que está al 100 %, se decide
  el destino final:
  - **Preferida:** `faminec/notes-sync` en la **tienda Community** (alcancio
    máximo, pero exige el validador y el cuerpo de PR de la guía).
  - **Alternativa:** repo personal `F4M1N3C/noctalia-plugins` sin PR a la
    tienda (control total, cero revisión pública).
- Los **PRs al oficial** (`noctalia-dev/official-plugins`) también se preparan
  **en local** y solo se abren cuando el usuario lo ordene. Nota: el repo
  oficial usa `main` como rama por defecto (a diferencia del repo de skills,
  que usa `dev`).

### 9.3 Otras decisiones tomadas por mí (para que puedas corregir)

1. **El PR va primero, el plugin después.** Se prepara el PR 1
   (`watch_external_changes`, el de menos riesgo y el que más gente agradece) y
   se mide la reacción antes de invertir en el PR 2 (el del bug de datos).
2. **No se propone `onIpc`/`open-note`.** PR #149 ya lo cubre; duplicarlo sería
   tonto. Cuando #149 entre, el puente usará
   `noctalia msg panel-open noctalia/notes:panel "note:<nombre>"`.
3. **El widget del puente cambia de glifo.** Hoy usa `"notes"` por defecto, que
   es **exactamente el mismo glifo que el widget del oficial** → en tu barra hay
   dos iconos de notas idénticos (`settings.toml:828` y `:882`). El glifo por
   defecto pasa a ser de nube/sync, y el icono del oficial queda como el único
   que abre las notas.
4. **El fork no se borra hasta que los PRs entren.** Es la red de seguridad.
5. **`notes-mobile` sigue siendo repo aparte.** No es un plugin: es un proceso
   Node que necesita socket, token y SSE.
6. **El id nuevo del puente es `faminec/notes-sync`.** `faminec/notes-plus`
   queda para el fork y se retira al final (un solo plugin por id).
7. **El canal pasa a `.current.json` en la carpeta de notas** (§9.1), no a un
   `pluginDataDir()`.

## 10. Alcance de esta fase (todo local)

Mientras no se publique nada, el trabajo es **dejar el sistema local al 100 %**:

| # | Tarea | Dónde |
|---|---|---|
| 1 | Corregir la pérdida silenciosa de datos: `flush()` no pisa cambios externos | `notes-plus/panel.luau` |
| 2 | Portar `dirs.luau` y `$XDG_DOCUMENTS_DIR` del oficial al fork | `notes-plus/` |
| 3 | Resolver `$XDG_DOCUMENTS_DIR` en el servidor | `notes-mobile/server.js` |
| 4 | Mover el canal de la nota abierta a `.current.json` | `notes-plus/` + `notes-mobile/` |
| 5 | Cambiar el glifo del widget a nube/sync | `notes-plus/` |
| 6 | Apuntar el servidor al plugin correcto y a la carpeta correcta | `notes-mobile/` |
| 7 | Pruebas: API, panel, y el recorrido completo celular→PC→celular | ambos |
| 8 | Preparar los 2 PRs al oficial **en local**, sin abrirlos | repo oficial clonado |

La publicación (tienda, repo personal, PRs upstream) es una fase posterior que
solo arranca cuando el usuario confirme que esto está al 100 %.
