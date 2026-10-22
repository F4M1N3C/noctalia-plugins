/* Inyector de rueda virtual por uinput, para probar el panel sin tocar el
 * raton de verdad.
 *
 * Uso:  gcc -O2 -o wheel tools/wheel_injector.c
 *        ./wheel arriba|abajo [pasos]      (positivo = arriba)
 *
 * Notas (importantes, para no perder tiempo la proxima vez):
 *
 *  - En los kernels modernos (>= 4.5) UI_DEV_CREATE ya NO recibe el
 *    'struct uinput_user_dev': el dispositivo se configura antes con
 *    UI_DEV_SETUP. Si se llama a UI_DEV_CREATE sin configurar, el kernel
 *    responde EINVAL ("write device info first") y no se crea nada.
 *  - Los ejes del puntero (REL_X/REL_Y) tambien hacen falta: con un
 *    dispositivo que solo tiene la rueda, el compositor puede ignorarlo y
 *    los eventos no llegan a ninguna superficie.
 *  - El dispositivo tiene que vivir al menos un par de segundos: si se crea
 *    y se destruye enseguida, el compositor no llega a abrirlo y los eventos
 *    se pierden.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
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

	struct uinput_setup setup;
	memset(&setup, 0, sizeof(setup));
	snprintf(setup.name, UINPUT_MAX_NAME_SIZE, "wheel-injector");
	setup.id.bustype = BUS_USB;
	setup.id.vendor = 0x1234;
	setup.id.product = 0x5678;
	setup.id.version = 1;
	setup.ff_effects_max = 0;
	if (ioctl(fd, UI_DEV_SETUP, &setup) < 0) {
		perror("UI_DEV_SETUP");
		close(fd);
		return 1;
	}
	if (ioctl(fd, UI_DEV_CREATE) < 0) {
		perror("UI_DEV_CREATE");
		close(fd);
		return 1;
	}
	/* El compositor necesita tiempo para abrir el dispositivo nuevo: los
	 * eventos que se mandan antes de que lo abra se pierden. Por eso se
	 * repiten durante unos segundos: aunque el primero se pierda, los
	 * siguientes llegan. */
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
	ioctl(fd, UI_DEV_DESTROY);
	close(fd);
	printf("rueda inyectada: %s x%d\n", amount > 0 ? "arriba" : "abajo", pasos);
	return 0;
}
