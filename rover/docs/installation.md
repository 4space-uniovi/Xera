# Instalación en el Arduino UNO Q

```bash
git clone https://github.com/4space-uniovi/xera.git && cd xera
./install.sh                         # pregunta antes de cada cambio del sistema
./install.sh --dry-run               # solo muestra lo que haría
./install.sh --yes --rover-id 03     # no interactivo; nombre 4SPACE-ROVER-03
./doctor.sh                          # diagnóstico (solo lectura)
./update.sh                          # más adelante: git pull + aplicar cambios
```

El instalador (idempotente: se puede repetir) hace, pidiendo confirmación en cada cambio del sistema:
1. Comprueba ARM64 y las dependencias (`python3-venv`, `v4l-utils`, `git`); ofrece instalarlas con `apt`.
2. Crea `rover/.venv` e instala `requirements.txt`.
3. Comprueba que tu usuario está en los grupos `dialout` (ESP32), `video` (webcam) y `gpiod` (LEDs).
4. Instala la regla udev `/etc/udev/rules.d/99-4space-xera.rules`: crea `/dev/xera-esp32` (enlace estable al
   ESP32) y le dice a ModemManager que no lo sondee.
5. Guarda el identificador del rover en `rover/config/rover.yaml`.
6. Instala y activa `4space-rover.service` (usuario normal, no root; se reinicia solo si falla).

`doctor.sh` comprueba todo lo anterior y dice cómo arreglar lo que falle.
El firmware del ESP32 **no** se carga desde la placa: se hace desde un PC con PlatformIO (ver el README del repo).

## Actualizar (`git pull`)
```bash
cd xera && ./update.sh              # trae los cambios y los aplica
./update.sh --dry-run               # solo muestra qué commits llegarían
./update.sh --reinstall             # vuelve a aplicar la instalación aunque estés al día
```
- Si solo cambió la interfaz web (`frontend/`) o la documentación, basta recargar la página: no reinstala ni reinicia.
- Si cambió Python u otra cosa, ejecuta `install.sh --yes` (idempotente: dependencias, regla udev, servicio) y reinicia el servicio.
- Tu configuración (`rover/config/rover.yaml`) no está en git, así que `git pull` nunca la pisa.
- Si tienes cambios locales sin guardar, el script se detiene y te lo dice (haz commit o `git stash`).

**No toca la red ni NetworkManager.** El modo AP llega en la Fase 4.

## Día a día
```bash
systemctl status 4space-rover        # ¿está vivo?
journalctl -u 4space-rover -f        # logs en directo
sudo systemctl restart 4space-rover  # tras cambiar código Python
```
Los cambios en `frontend/` (HTML/CSS/JS) se ven al recargar la página, sin reiniciar nada.

## LEDs del UNO Q
Verde fijo = ESP32 conectado (la webcam es opcional). Rojo parpadeando = fallo o ESP32 ausente.
Se desactivan con `leds.enabled: false` en `config/rover.yaml`.

## Desinstalar
```bash
./scripts/uninstall.sh            # quita el servicio (conserva código y config)
./scripts/uninstall.sh --purge    # además borra .venv
```
