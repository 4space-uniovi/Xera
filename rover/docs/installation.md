# Instalación en el Arduino UNO Q

```bash
git clone <url-del-repo> ~/4space-mini-rover && cd ~/4space-mini-rover
./scripts/install.sh                 # pregunta antes de cada cambio del sistema
./scripts/install.sh --yes --rover-id 03   # no interactivo; nombre 4SPACE-ROVER-03
```

El instalador (idempotente: se puede repetir):
1. Comprueba ARM64 y las dependencias (`python3-venv`, `v4l-utils`); ofrece instalarlas con `apt`.
2. Crea `.venv` e instala `requirements.txt`.
3. Comprueba que tu usuario está en los grupos `dialout` (ESP32), `video` (webcam) y `gpiod` (LEDs).
4. Guarda el identificador del rover en `config/rover.yaml`.
5. Instala y activa `4space-rover.service` (usuario normal, no root; se reinicia solo si falla).

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
