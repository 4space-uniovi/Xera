#!/usr/bin/env bash
# Compila y carga el firmware XERA en el ESP32-S3 desde el propio UNO Q.
#   ./scripts/flash_firmware.sh            # pregunta antes de cargar
#   ./scripts/flash_firmware.sh --yes
# Requiere PlatformIO: ./scripts/install.sh --with-firmware-tools
# Para el servicio mientras carga (el puerto serie no se puede compartir) y lo reanuda al terminar.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FW="$(cd "$REPO/.." && pwd)/firmware"
UNIT=4space-rover.service
YES=0; [ "${1:-}" = "--yes" ] && YES=1

[ -f "$FW/platformio.ini" ] || { echo "No encuentro firmware/ (esto solo funciona dentro del repo xera)."; exit 1; }
PIO="$(command -v pio || true)"; [ -z "$PIO" ] && [ -x "$HOME/.platformio-venv/bin/pio" ] && PIO="$HOME/.platformio-venv/bin/pio"
[ -n "$PIO" ] || { echo "Falta PlatformIO. Instálalo con: ./scripts/install.sh --with-firmware-tools"; exit 1; }

PORT=/dev/xera-esp32
[ -e "$PORT" ] || PORT="$( (compgen -G '/dev/ttyACM*'; compgen -G '/dev/ttyUSB*') | head -1 )"
[ -n "$PORT" ] || { echo "No se detecta el ESP32. Revisa el cable/hub (lsusb, dmesg | tail)."; exit 1; }

echo "Firmware: $FW"
echo "Puerto:   $PORT"
echo "⚠  Los motores quedarán sin control durante la carga. Levanta las ruedas del suelo."
if [ "$YES" = 0 ]; then read -r -p "¿Cargar el firmware? [s/N] " a; [[ "$a" =~ ^[sSyY]$ ]] || { echo "Cancelado."; exit 0; }; fi

RESTART=0
if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
  echo "Parando $UNIT..."; sudo systemctl stop "$UNIT"; RESTART=1
fi
trap '[ "$RESTART" = 1 ] && { echo "Reanudando $UNIT..."; sudo systemctl start "$UNIT"; }' EXIT

cd "$FW"
"$PIO" run -t upload --upload-port "$PORT"
echo "✔ Firmware cargado."
echo "Si falla al conectar: mantén pulsado BOOT, pulsa y suelta RESET, suelta BOOT y repite."
