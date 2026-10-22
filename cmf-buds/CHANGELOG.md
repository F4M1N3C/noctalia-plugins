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

`bin/test_local_actions.py` (36 comprobaciones) cubre el motor sin necesidad
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
