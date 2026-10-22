/* Inyector de rueda virtual por uinput, para probar los sliders del panel
 * sin tocar el raton de verdad.
 *
 * Uso:  gcc -O2 -o /tmp/wheel tools/wheel_injector.c
 *        /tmp/wheel arriba|abajo [pasos]      (positivo = arriba)
 *
 * LA RECETA QUE FUNCIONA (las otras dos fallan):
 *
 *  1. Las capacidades se declaran con los ioctls: UI_SET_EVBIT (EV_REL,
 *     EV_SYN) y UI_SET_RELBIT (REL_WHEEL, y tambien REL_X/REL_Y: sin ejes
 *     de puntero el compositor puede ignorar el dispositivo).
 *  2. La configuracion se manda con un write() del 'struct uinput_user_dev'
 *     TAL COMO ESTA EN LA CABECERA DEL SISTEMA (el antiguo, 1120 bytes: solo
 *     name, id, ff_effects_max y los absmax/absmin/absfuzz/absflat). Si se
 *     usa el struct moderno (1940 bytes, con los bitmask), el kernel
 *     responde EINVAL y el dispositivo no se crea.
 *  3. Despues, UI_DEV_CREATE.
 *
 *  Con UI_DEV_SETUP (la ruta moderna) el nodo /dev/input/eventN aparece,
 *  pero los eventos NO llegan a los lectores.
 *
 * ESTADO EN ESTE EQUIPO (kernel 7.2.11): con la receta de arriba el
 * dispositivo se registra bien (se ve en /proc/bus/input/devices, con sus
 * capacidades), pero al leer el nodo no llega ningun evento. Con ydotool
 * (que usa otra ruta) el mismo kernel si los entrega, asi que el problema
 * esta en como se arma el dispositivo virtual, no en el plugin.
 * Queda aqui por si en otro equipo/kernel si funciona.
 *
 *  Ademas, el dispositivo tiene que vivir al menos un par de segundos: si
 *  se crea y se destruye enseguida, el compositor no llega a abrirlo y los
 *  eventos se pierden. Por eso los eventos se repiten durante unos
 *  segundos.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/uinput.h>

int main(int argc, char *argv[])
{
	int pasos = 3;
	int amount = -1;

	if (argc > 1) {
		if (strcmp(argv[1], "arriba") == 0 || strcmp(argv[1], "up") == 0)
			amount = 1;
		else if (strcmp(argv[1], "abajo") == 0 || strcmp(argv[1], "down") == 0)
			amount = -1;
		else
			amount = atoi(argv[1]);
	}
	if (argc > 2)
		pasos = atoi(argv[2]);
	if (pasos < 1)
		pasos = 1;

	int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (fd < 0) {
		perror("open /dev/uinput");
		return 1;
	}
	if (ioctl(fd, UI_SET_EVBIT, EV_REL) < 0)
		perror("UI_SET_EVBIT EV_REL");
	if (ioctl(fd, UI_SET_EVBIT, EV_SYN) < 0)
		perror("UI_SET_EVBIT EV_SYN");
	if (ioctl(fd, UI_SET_RELBIT, REL_WHEEL) < 0)
		perror("UI_SET_RELBIT REL_WHEEL");
	if (ioctl(fd, UI_SET_RELBIT, REL_X) < 0)
		perror("UI_SET_RELBIT REL_X");
	if (ioctl(fd, UI_SET_RELBIT, REL_Y) < 0)
		perror("UI_SET_RELBIT REL_Y");

	/* El struct tal cual lo define la cabecera del sistema. */
	struct uinput_user_dev ud;
	memset(&ud, 0, sizeof(ud));
	snprintf(ud.name, UINPUT_MAX_NAME_SIZE, "wheel-injector");
	ud.id.bustype = BUS_USB;
	ud.id.vendor = 0x1234;
	ud.id.product = 0x5678;
	ud.id.version = 1;
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
	/* Que el compositor (y los lectores de /dev/input) tengan tiempo de
	 * abrir el dispositivo nuevo. */
	sleep(1);

	for (int vuelta = 0; vuelta < 3; vuelta++) {
		for (int i = 0; i < pasos; i++) {
			struct input_event e;
			memset(&e, 0, sizeof(e));
			e.type = EV_REL;
			e.code = REL_WHEEL;
			e.value = (amount > 0) ? 1 : -1;
			if (write(fd, &e, sizeof(e)) < 0)
				perror("write");
			memset(&e, 0, sizeof(e));
			e.type = EV_SYN;
			e.code = SYN_REPORT;
			if (write(fd, &e, sizeof(e)) < 0)
				perror("write syn");
			usleep(40000);
		}
		sleep(1);
	}
	sleep(1);
	ioctl(fd, UI_DEV_DESTROY);
	close(fd);
	printf("rueda inyectada: %s x%d\n", amount > 0 ? "arriba" : "abajo", pasos);
	return 0;
}
