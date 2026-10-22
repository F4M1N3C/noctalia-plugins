# Changelog de cmf-buds

Registro **verificado** de los cambios del plugin. Existe porque el análisis de
los fallos vivía solo en los mensajes de commit, y algunos de esos mensajes
describían el fallo de forma inexacta (ver "Correcciones" al final). Aquí se
describe lo que el código hace de verdad, contrastado con las pruebas.

## 2026-10-21 — Atajos locales con el dial del estuche

### `6065a82` — Atajos locales con el dial del estuche

Motor de atajos: el dial del estuche se detecta como un cambio de volumen del
sink de los auriculares; con un modificador pulsado se ejecuta un comando. Las
reglas viven en `local_actions.json` y se editan desde el panel de Atajos.

### `f508b99` — Las reglas de N pulsaciones mandan sobre "cualquiera"

Una regla con N pulsaciones (2, 3...) tiene prioridad sobre la de
"cualquiera" (N = 0), que queda de respaldo y se dispara al final del gesto si
las pulsaciones no llegan al número.

### `1ec1257` — El lector de modificadores reescanea /dev/input

Los dispositivos de entrada se abren en modo no bloqueante y se releen cada
2 s, para que un teclado que se conecte después siga sirviendo.

### `e5fe6ff` — El motor decide con el estado completo

La lista de reglas aplicables se recalcula **en cada evento** contra el juego
de reglas vigente, en vez de guardar una vista parcial.

### `3e56ac6` — La identidad de un evento la da el valor, no el reloj

Un evento es "el mismo" que otro si el volumen no ha cambiado; el motor ya no
usa marcas de tiempo para decidir si un cambio es propio (el restore del
volumen) o un gesto del usuario.

### `fb5e5fc` — Fuera los últimos proxies de identidad por reloj

Se eliminan los restos de la lógica por reloj, dejando solo el valor.

### `5dd46c3` — Limpia constantes muertas del motor

### `42d9fbf` — Reglas malformadas

Lectura tolerante de `presses`, `require` y `forbid`; una regla inválida se
ignora entera, con aviso, y **no** aborta la evaluación de las demás.

### `9ba4bad` — El watcher no puede morir en silencio

El watcher registraba los errores y reintentaba; además se añadió
`_handle_line()` para poder probar el camino de error de verdad.

### Este cambio — Espera creciente real, registro verificable y pruebas que discriminan

- **Las pruebas esperan a la condición, no a un tiempo.** Antes los tests del
  watcher dormían 0,6-0,8 s y luego miraban: si la máquina iba cargada y el
  bucle no había terminado sus iteraciones, la prueba fallaba por el motivo
  equivocado. Ahora hay un helper `esperar(cond)` que espera a que se cumpla
  lo que se quiere comprobar, con un tope de tiempo como red de seguridad.
- **Numeración en orden.** El test de recarga de reglas estaba numerado como
  7 pero se ejecutaba el último; ahora los tests se numeran y se ejecutan en
  el mismo orden.
- **Aserciones más fuertes:** el log de fallos se comprueba **en orden y en
  bloque** (no solo "aparece uno"), y se comprueba que la suscripción sana
  está **entre** los dos fallos, no solo que aparece.

- **Espera creciente real.** Antes el contador de fallos se reiniciaba al
  empezar cada intento, así que la espera **nunca crecía**: con un fallo
  persistente se quedaba siempre en 2 s. Ahora el contador solo se reinicia
  cuando la suscripción aguanta `HEALTHY_SECONDS` (5 s) sin errores, y las
  esperas son 1 s, 2 s, 3 s… hasta 10 s.
- **Una suscripción que se cierra antes de tiempo también es un fallo**
  (antes reiniciaba el bucle cada segundo, sin log).
- **Registro:** este `CHANGELOG.md`, con la descripción verificada de cada
  cambio y las correcciones de los mensajes de commit imprecisos.
- **Pruebas que discriminan.** La prueba que supuestamente cubría el reinicio del
  contador era **vacua**: la suscripción sana era el primer intento (contador
  ya a 0), así que la aserción se cumplía igual sin el reinicio. Se
  demuestra desactivando el reinicio a propósito: la prueba antigua pasa
  igual, la nueva falla. Ahora la secuencia es fallo → suscripción sana →
  fallo, y el segundo fallo **tiene** que volver a ser el nº1. Además se
  añadió la prueba de la suscripción que se cierra antes de tiempo, que solo
  estaba verificada a mano. Las tres pruebas se comprobaron rompiendo el
  código a propósito (espera fija, sin reinicio, sin detección de cierre
  temprano): las tres fallan.

### Este cambio — Ningún hilo puede morir en silencio; el fichero manda

Cuatro hilos podían morir en silencio (una excepción sin capturar los
mataba y la tarea se perdía sin rastro):

- el **watcher**: el resolutor del sink estaba fuera de cualquier `try`
- el **temporizador del gesto**: si fallaba al cerrarlo, se perdía el gesto
- el **temporizador del restore**: si fallaba, el volumen se quedaba donde
  no toca y el usuario no sabía por qué
- el **lector RFCOMM** del demonio: una excepción inesperada lo mataba

Además, el panel operaba sobre la lista **en memoria** del motor, que solo se
recargaba con un evento de volumen: si las reglas se editaban a mano, el
siguiente "Añadir regla" **sobrescribía el fichero y las perdía**. Ahora el
fichero es la fuente de verdad: se relee antes de guardar y antes de
mostrar las reglas.

También se recoge `tools/wheel_injector.c` (inyector de rueda por `uinput`)
dentro del plugin, con los dos detalles que costaron tiempo: `UI_DEV_CREATE`
no recibe el `struct uinput_user_dev` en los kernels modernos (hay que usar
`UI_DEV_SETUP` primero) y el dispositivo tiene que vivir lo suficiente para
que el compositor lo abra.

Suite: 37 → 44 comprobaciones.

## Correcciones de descripciones anteriores

Las dos descripciones siguientes eran **inexactas**; se corrigen aquí porque no
se puede reescribir la historia del repositorio:

- **`42d9fbf`**: decía que el hilo del watcher "se moría en silencio" y que una
  regla con `presses` ilegible "se convertía en 1 pulsación y se comía los
  gestos de la buena". **Realidad verificada**: el hilo del watcher **no
  moría** (el bucle `while` seguía vivo); lo que se abortaba era la
  *suscripción* a `pactl subscribe`, que se relanzaba cada segundo en bucle, y
  la excepción (que salía de `int("abc")` o de iterar un `require` numérico)
  abortaba **la evaluación de todas las reglas**, no solo de la mala: el gesto
  entero se perdía. El síntoma real era "los atajos no funcionan nunca y no
  hay ni una línea en el log".
- **`9ba4bad`**: su nota decía que el fallo "tumbaba el watcher". Con más
  precisión: **tumbaba la suscripción**, que se reiniciaba en bucle; el hilo
  seguía vivo. Además, la espera creciente que ese commit anunciaba no
  llegaba a crecer por el reinicio prematuro del contador (corregido en este
  cambio).

## Pruebas

`bin/test_local_actions.py` (37 comprobaciones) cubre el motor sin necesidad
de auriculares: la precedencia de las reglas de N pulsaciones y su respaldo, el
aislamiento de una regla malformada, que el watcher registre los errores sin
morir, que avise si no puede suscribirse, **que la espera entre reintentos
crezca (1, 2, 3, 4 s)**, **que el contador se reinicie cuando la suscripción
vuelve a funcionar** (un fallo, una suscripción sana y otro fallo: el segundo
vuelve a ser el nº1) y **que una suscripción que se cierra antes de tiempo
cuente como fallo**.

Las comprobaciones del watcher se validaron **rompiendo el código a
propósito** (espera fija de 1 s, sin reinicio del contador, sin detección del
cierre temprano): las tres fallan, así que no son vacuas. La de la regla
malformada cubre la propiedad en su conjunto —que una regla inválida no
impida ejecutar las demás—, y se comprobó rompiendo a la vez las dos capas
que la sostienen (la lectura tolerante y el aislamiento por regla): la suite
falla.
