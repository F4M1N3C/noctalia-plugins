# CMF Buds — plugin de Noctalia

Control nativo de los **Nothing CMF Buds Pro 2** (modelo `B172`) desde la barra de
Noctalia, sin depender de la app Nothing X del móvil.

El plugin habla directamente el protocolo **RFCOMM** del fabricante a través de un
demonio en Python, y expone todo lo que se puede cambiar en los auriculares:
cancelación de ruido, volumen, ecualizador, Ultra Bass, gestos del dial del
estuche, audio espacial, detección in-ear, modo de baja latencia, multipunto,
batería, "ring my buds" y test de ajuste.

## Requisitos

| Dependencia | Para qué |
|---|---|
| `python3` | demonio y cliente |
| `bluetoothctl` | descubrimiento del dispositivo |
| `pactl` (pipewire-pulse) | volumen del sistema |
| BlueZ con el dispositivo ya emparejado | canal RFCOMM |

El plugin se instala en `~/.local/share/noctalia/plugins/cmf-buds` y se activa con:

```bash
noctalia msg plugins enable faminec/cmf-buds
```

## Widget de barra

Se añade como `faminec/cmf-buds:widget` en la lista de widgets de una barra
(por defecto en la barra vertical izquierda, junto al ecualizador y al Bluetooth):

```toml
[bar.Left-utility-bar]
center = [ ..., "cmf_buds", ... ]

[widget.cmf_buds]
type = "faminec/cmf-buds:widget"
color = "on_surface"
```

- **Clic**: abre el panel de control (en la pestaña que se usó la última vez).
- **Rueda**: sube/baja el volumen (5 % por paso, configurable).
- **Clic derecho**: cicla el modo de ANC (apagado → transparencia → cancelación).
- **Tooltip**: conexión, ANC, batería, EQ y volumen.

## Panel

Cuatro pestañas, cada una en su propia entrada `[[panel]]` para que la ventana
se ajuste al tamaño del contenido de la sección (sin barras de desplazamiento):

| Pestaña | Entrada | Tamaño | Contenido |
|---|---|---|---|
| Sonido | `panel-sound` | 600×910 | ANC (apagado / transparencia / cancelación + nivel adaptativo, alto, medio, bajo), volumen del sistema y EQ (Balanced, Rock, Electronic, Pop, Vocals, Classical, Custom con graves/medios/agudos de -6 a +6, Ultra Bass con 5 niveles) |
| Controles | `panel-controls` | 600×560 | Gestos de toque de cada auricular y del estuche (doble, triple, mantener, doble mantener y dial), búsqueda "ring my buds" por auricular |
| Atajos | `panel-actions` | 600×1010 | Atajos locales: qué comando se ejecuta al mover el dial del estuche |
| Sistema | `panel-system` | 600×930 | Audio espacial, detección in-ear, baja latencia, conexión dual, test de ajuste, información del dispositivo y reconexión |

Al cambiar de pestaña, el panel cierra y se abre el de la sección nueva, así que
la ventana cambia de alto.

## Ajustes

En *Ajustes → Plugins → CMF Buds*:

| Ajuste | Por defecto | Descripción |
|---|---|---|
| `device_name` | `CMF Buds Pro 2` | nombre Bluetooth a buscar |
| `device_mac` | *(vacío)* | MAC fija si hay varios auriculares |
| `glyph` | `headphones` | icono del widget |
| `volume_step` | `5` | paso de volumen con la rueda |
| `poll_seconds` | `60` | frecuencia de lectura del estado |
| `wheel_adjust` | `true` | pedir a Noctalia que las barras se ajusten con la rueda (requiere el parche) |

## Atajos locales (comandos en el PC)

Los auriculares no guardan comandos: su firmware solo acepta una lista fija de
acciones (reproducir, siguiente, volumen, ANC...). Lo que llega al PC es la
**acción resultante**, no la pulsación cruda. Por eso las macros se construyen
en el PC:

1. El dial del estuche tiene asignada la acción *Control de volumen*, así que
   al girarlo el PC recibe una tecla de volumen y el volumen del sink de los
   auriculares cambia solo: ese cambio es la señal.
2. El daemon vigila el sink con `pactl subscribe` y detecta la señal.
3. Los modificadores (SUPER, CTRL, ALT, SHIFT) se leen de `/dev/input/event*`,
   así que "SUPER + dial" es distinguible de "dial" a secas.
4. Si una regla encaja, se ejecuta el comando y, si está activated, se restaura
   el volumen (para que el dial no toque el volumen cuando hace de atajo).

La pestaña **Atajos** del panel permite crear reglas:

| Campo | Valores |
|---|---|
| Gesto | Rueda del dial ↑ / ↓ |
| Repeticiones | Cualquiera / 1 – 5 |
| Modificador | Ninguno / SUPER / CTRL / ALT / SHIFT / Sin SUPER |
| Comando | cualquier comando de shell (`hyprctl dispatch 'hl.dsp.focus({ workspace = "m+1" })'`) |
| Notificar | muestra una notificación al ejecutar |
| Restaurar volumen | deshace el cambio de volumen que causó el atajo |

El motor agrupa los eventos: un giro del dial es **una** acción (no una por
muesca) y, tras disparar, ignora el eco que devuelve el auricular al restaurar
el volumen (si no, el workspace iba +1 y -1 y no se movía nada).

En los comandos se puede usar el marcador `{output}`, que se sustituye por el
nombre del monitor enfocado (por ejemplo `DP-1`).

De serie hay dos reglas (con la sintaxis de dispatch de Hyprland 0.56):

| Gesto | Modificador | Comando |
|---|---|---|
| Rueda del dial ↑ | SUPER | `hyprctl dispatch 'hl.dsp.focus({ workspace = "m+1" })'` |
| Rueda del dial ↓ | SUPER | `hyprctl dispatch 'hl.dsp.focus({ workspace = "m-1" })'` |

Sin SUPER el dial se comporta como siempre (sube/baja el volumen); con SUPER
cambia de workspace y el volumen se restaura solo.

La puerta queda abierta para más atajos: basta con añadir reglas con otro
comando, otro modificador o más repeticiones.

Requisitos: el usuario debe estar en el grupo `input` (para leer
`/dev/input`) y los auriculares deben estar conectados al PC por Bluetooth de
audio.

## Pruebas

`bin/test_local_actions.py` comprueba el motor de atajos sin necesitar
auriculares (simula la señal del dial):

```bash
python3 bin/test_local_actions.py
```

Cubre (37 comprobaciones): la regla "cualquiera" sola, la precedencia de la de N
pulsaciones y su respaldo, reglas con modificadores distintos, la
especificidad, el comando vacío, que una ráfaga sea un solo gesto, que gestos
separados disparen acciones distintas, que un gesto tras restaurar el volumen
no se pierda, que los pinchazos muy juntos (50 ms) se cuenten como varios,
que nuestro propio cambio se reconozca por el valor, que una regla malformada
se ignore sin tapar a las demás, que el watcher registre un error puntual sin
morir, que avise cuando no puede suscribirse a los cambios de volumen, **que
la espera entre reintentos crezca (1, 2, 3, 4 s)**, **que el contador de
fallos se reinicie cuando la suscripción vuelve a funcionar** (un fallo, una
suscripción sana y otro fallo: el segundo vuelve a ser el nº1), **que una
suscripción que se cierra antes de tiempo cuente como fallo** y que las reglas
editadas fuera del panel se recargan.

Las pruebas **esperan a la condición que comprueban**, no a un tiempo fijo: si
la máquina va cargada, no falla "por el motivo equivocado", y una comprobación
no puede cumplirse antes de que se haya dado el caso que dice comprobar.

## Cómo funciona

- `service.luau` arranca `bin/budsctl.py daemon` (demonio persistente con
  `flock`, socket Unix y `state.json`) y lo mantiene vivo con un ping cada 20 s.
- El demonio habla RFCOMM por el canal 15 del SDP del dispositivo, envía los
  comandos con cabecera `[0x55, 0x60, 0x01, cmd, len, fsn]` y CRC16-ARC, y
  publica el estado en `state.json`.
- `widget.luau` y `panel.luau` leen ese estado y mandan comandos vía el socket
  (`rpc`), sin bloquear la interfaz.
- El volumen se controla sobre el sink de PipeWire del dispositivo
  (`bluez_output.<MAC>.1`).

Datos persistentes:

```
~/.local/state/noctalia/plugins/data/faminec/cmf-buds/
├── state.json         # estado actual del dispositivo
├── local_actions.json # reglas de atajos locales
├── daemon.sock        # socket del demonio
├── daemon.sock.lock
└── daemon.log         # log del demonio
```

## Tipografía

- **Doto** (dot matrix) para títulos, cifras grandes y etiquetas.
- **Space Grotesk** para el resto del texto.
- Ambas fuentes están empaquetadas en `fonts/` con su licencia OFL.

## Créditos del protocolo

- [SoaOaoS/something-x](https://github.com/SoaOaoS/something-x) — app Nothing X
  de escritorio, base del trabajo inverso del protocolo.
- [maniacx/BudsLink](https://github.com/maniacx/BudsLink) — implementación de
  referencia de los comandos RFCOMM de los Nothing Ear/CMF.

El registro verificado de los cambios (con las correcciones de descripciones
anteriores que resultaron inexactas) está en [`CHANGELOG.md`](CHANGELOG.md).

## Detalles de comportamiento

- **Un giro = una acción.** Varias muescas seguidas se agrupan en un solo
  gesto (ventana de 0,7 s) y solo se dispara una vez: lo decide el estado
  del gesto, no un antirrebote por reloj.
- **Precedencia:** si un gesto tiene una regla con N pulsaciones (2, 3...), esa
  manda y la de "Cualquiera" queda de respaldo: se ejecuta al final del gesto
  si las pulsaciones no llegan al número. Las reglas se evalúan en cada evento
  contra el juego vigente, y las más específicas (SUPER antes que ninguna)
  ganan.
- **Nuestro propio cambio de volumen no se confunde con un gesto:** se
  reconoce por el **valor** que ponemos, no por una ventana de tiempo. La
  identidad de un evento la da **siempre el valor** (el volumen), nunca el
  reloj: un evento es "el mismo" que otro si el volumen no ha cambiado, y es
  nuestro si su valor es el que pusimos. Las únicas ventanas de tiempo que
  quedan son la definición de gesto (GROUP_WINDOW, 0,7 s) y una red
  anti-duplicados de 30 ms, que no puede tragarse un pinchazo real (el dial
  separa las muescas más de 30 ms).
- **Nada se descarta en silencio:** si un gesto no encaja con ninguna regla, si
  una regla de N pulsaciones hace esperar a la de "cualquiera", si un gesto se
  omite por venir demasiado cerca del anterior o si se pierde la referencia
  del volumen, queda anotado en el log del demonio.
- Los gestos que no encajan con ninguna regla se avisan en el log, para que
  no parezca que los atajos están rotos.
- **Una regla malformada no puede romper el motor.** Los campos de cada regla
  (`presses`, `require`, `forbid`) se leen de forma tolerante y una regla
  inválida —editada a mano— se **ignora entera**, con aviso en el log, de modo
  que ni tapa a las reglas bien escritas ni aborta la evaluación de las demás.
- **El watcher no puede morir en silencio.** Un error al procesar un cambio se
  registra y el hilo sigue; un error en la suscripción, o una suscripción que
  se cierra antes de tiempo, se registran y se reintentan con una **espera
  creciente de 1 s, 2 s, 3 s… hasta 10 s**; y si no se puede abrir la
  suscripción también se avisa. El contador de fallos solo se reinicia cuando
  la suscripción aguanta 5 s sin errores, y al reiniciarse el siguiente
  reintento vuelve a ser de 1 s. Antes de esto, un fallo repetido reiniciaba
  la suscripción cada segundo y los atajos no funcionaban nunca, sin una sola
  línea en el log.
- **El eco del auricular se ignora.** Al restaurar el volumen, los auriculares
  devuelven el suyo y generan otro evento; el motor ignora los eventos hasta
  que el volumen se estabiliza (1,2 s) y luego vuelve a armarse solo.
- **El restore espera 0,8 s** y comprueba el resultado: PipeWire aplica el
  volumen con una rampa de ~0,5 s y descarta un cambio emitido durante la
  rampa.
- **Si no hay ninguna ventana enfocada**, Hyprland ignora el cambio de
  workspace (afecta igual a sus propios atajos de teclado). Con una ventana
  activa funciona siempre.
- **La rueda del ratón en las barras del panel** (volumen y EQ) necesita un
  parche en Noctalia: el control `Slider` ya soporta la rueda, pero el árbol
  declarativo `ui.*` no expone la propiedad. El plugin la pide siempre
  (`wheelAdjustEnabled`); hasta que el shell tenga el parche aparece un aviso
  en el log y la rueda no hace nada. Se puede desactivar con el ajuste
  `wheel_adjust` para no ensuciar el log.

  **Noctalia parcheado: ya instalado y funcionando.** El parche (6 líneas sobre
  `src/ui/ui_tree_reconciler.cpp`, aplica limpio sobre v5.3.0) expone la
  propiedad `wheelAdjustEnabled` en los sliders declarativos, igual que hace el
  centro de control. Está en `patch.diff` (este mismo directorio) y el binario
  compilado quedó en `/opt/noctalia-patched/`:
  - `sudo /opt/noctalia-patched/instalar.sh` → reinstala el binario parcheado
    (hace copia de seguridad del original).
  - `sudo /opt/noctalia-patched/revertir.sh` → vuelve al binario del paquete.
  - Con el shell parcheado, la rueda ajusta el volumen y las barras de EQ
    directamente sobre el panel; el ajuste `wheel_adjust` del plugin permite
    dejar de pedirlo.
- Si el usuario cambia el volumen a mano justo después de un atajo, ese cambio
  se respeta (no se restaura).

## Limitaciones

- El canal RFCOMM está ocupado si la app Nothing X del móvil está conectada al
  mismo dispositivo: cierra la app en el móvil antes de usar el panel.
- No hay actualización de firmware.
- Algunos auriculares solo informan de la batería de un lado o de ninguno; la
  interfaz muestra `—` cuando el valor no existe.
- El dial del estuche no expone la acción de doble pulsación mantenida.
- `Nothing X` en el móvil sigue mandando sobre los ajustes si está conectado.
