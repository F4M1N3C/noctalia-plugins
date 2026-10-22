/* Inyector de teclado virtual por uinput, para probar el lector de
 * modificadores del motor de atajos sin usar el teclado de verdad.
 *
 * Uso:  gcc -O2 -o /tmp/key tools/key_injector.c
 *        /tmp/key 125            # pulsa y suelta KEY_LEFTMETA (SUPER)
 *        /tmp/key 125 mantener   # lo deja pulsado (Ctrl-C para soltarlo)
 *
 * El codigo es el de linux/input-event-codes.h (125 = KEY_LEFTMETA,
 * 29 = KEY_LEFTCTRL, 56 = KEY_LEFTALT, 42 = KEY_LEFTSHIFT).
 *
 * ESTADO EN ESTE EQUIPO (kernel 7.2.11): este inyector crea el nodo
 * /dev/input/eventN y el kernel registra el dispositivo con sus
 * capacidades (se ve en /proc/bus/input/devices), pero los eventos NO
 * llegan a los lectores: se lee el nodo y no hay nada. Con ydotool, en
 * cambio, el mismo kernel si los entrega.
 *
 * La receta que parece correcta (y la que usa ydotool) es: declarar las
 * capacidades con los ioctls (UI_SET_EVBIT/UI_SET_KEYBIT), mandar la
 * configuracion con un write() del 'struct uinput_user_dev' DE LA
 * CABECERA DEL SISTEMA (el antiguo, 1120 bytes: si se usa el struct
 * moderno de 1940 bytes, el kernel responde EINVAL) y despues
 * UI_DEV_CREATE.
 *
 * Para probar el lector de modificadores ahora mismo, usa ydotool, que si
 * funciona:  ydotool key 125:1   (125 = KEY_LEFTMETA)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/uinput.h>

static void enviar_tecla(int fd, int code, int value)
{
	struct input_event e;
	memset(&e, 0, sizeof(e));
	e.type = EV_KEY;
	e.code = code;
	e.value = value;
	if (write(fd, &e, sizeof(e)) < 0)
		perror("write");
	memset(&e, 0, sizeof(e));
	e.type = EV_SYN;
	e.code = SYN_REPORT;
	if (write(fd, &e, sizeof(e)) < 0)
		perror("write syn");
}

int main(int argc, char *argv[])
{
	int code = 125;
	int mantener = 0;

	if (argc > 1)
		code = atoi(argv[1]);
	if (argc > 2 && strcmp(argv[2], "mantener") == 0)
		mantener = 1;

	int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (fd < 0) {
		perror("open /dev/uinput");
		return 1;
	}
	/* Capacidades: sin esto el kernel descarta los eventos en silencio. */
	if (ioctl(fd, UI_SET_EVBIT, EV_KEY) < 0)
		perror("UI_SET_EVBIT EV_KEY");
	if (ioctl(fd, UI_SET_EVBIT, EV_SYN) < 0)
		perror("UI_SET_EVBIT EV_SYN");
	if (ioctl(fd, UI_SET_KEYBIT, code) < 0)
		perror("UI_SET_KEYBIT");

	/* El struct tal cual lo define la cabecera del sistema (el antiguo:
	 * name, id, ff_effects_max y los abs). Las capacidades de las teclas
	 * van aparte, con UI_SET_KEYBIT. */
	struct uinput_user_dev ud;
	memset(&ud, 0, sizeof(ud));
	snprintf(ud.name, UINPUT_MAX_NAME_SIZE, "key-injector");
	ud.id.bustype = BUS_USB;
	ud.id.vendor = 0x1234;
	ud.id.product = 0x5679;
	ud.id.version = 1;

	/* Ruta heredada: el kernel recibe la configuracion con un write(). */
	if (write(fd, &ud, sizeof(ud)) < 0) {
		perror("write uinput_user_dev");
		close(fd);
		return 1;
	}
	if (ioctl(fd, UI_DEV_CREATE) < 0) {
		perror("UI_DEV_CREATE");
		close(fd);
		return 1;
	}
	/* Que el lector de /dev/input tenga tiempo de abrir el nodo nuevo. */
	sleep(1);

	enviar_tecla(fd, code, 1);

	if (mantener) {
		/* La pulsacion se repite: un lector puede abrir el nodo del
		 * dispositivo virtual DESPUES de la primera pulsacion (los
		 * eventos no se repiten solos) y se perderia. */
		printf("tecla %d pulsada (Ctrl-C para soltarla)\n", code);
		fflush(stdout);
		while (1) {
			enviar_tecla(fd, code, 1);
			sleep(1);
		}
	}

	usleep(300000);
	enviar_tecla(fd, code, 0);
	usleep(300000);
	ioctl(fd, UI_DEV_DESTROY);
	close(fd);
	printf("tecla %d pulsada y soltada\n", code);
	return 0;
}
