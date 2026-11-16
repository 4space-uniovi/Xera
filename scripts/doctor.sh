#!/usr/bin/env bash
# Diagnóstico de la instalación: comprueba todo y te dice qué falta y cómo arreglarlo.
# Solo LEE, no cambia nada.   ./scripts/doctor.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$REPO/.." && pwd)"
UNIT=4space-rover.service
FAIL=0; WARN=0

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '      → %s\n' "$2"; FAIL=$((FAIL+1)); }
meh()  { printf '  \033[33m!\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '      → %s\n' "$2"; WARN=$((WARN+1)); }
head() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }

head "Sistema"
case "$(uname -m)" in aarch64|arm64) ok "ARM64";; *) meh "arquitectura $(uname -m) (la placa debería ser ARM64)";; esac
command -v python3 >/dev/null && ok "python3 $(python3 -V 2>&1 | cut -d' ' -f2)" || bad "falta python3" "sudo apt install python3"
command -v v4l2-ctl >/dev/null && ok "v4l2-ctl" || bad "falta v4l2-ctl" "sudo apt install v4l-utils"
for g in dialout video gpiod; do
  getent group "$g" >/dev/null || continue
  id -nG | tr ' ' '\n' | grep -qx "$g" && ok "usuario en grupo $g" || bad "tu usuario no está en el grupo $g" "sudo usermod -aG $g $USER  (y vuelve a iniciar sesión)"
done

head "Aplicación"
if [ -x "$REPO/.venv/bin/python" ]; then
  "$REPO/.venv/bin/python" -c "import fastapi, uvicorn, serial, yaml" 2>/dev/null && ok ".venv con las dependencias" \
    || bad ".venv sin dependencias" "$REPO/.venv/bin/pip install -r $REPO/requirements.txt"
else bad "no existe .venv" "./scripts/install.sh"; fi
[ -f "$REPO/config/rover.yaml" ] && ok "config/rover.yaml" || meh "sin config/rover.yaml (se usan valores por defecto)" "cp config/rover.example.yaml config/rover.yaml"

head "Servicio"
if systemctl list-unit-files "$UNIT" 2>/dev/null | grep -q "$UNIT"; then
  systemctl is-enabled --quiet "$UNIT" && ok "arranque automático activo" || meh "servicio no habilitado" "sudo systemctl enable $UNIT"
  systemctl is-active --quiet "$UNIT" && ok "servicio en marcha" || bad "servicio parado" "journalctl -u $UNIT -n 30 --no-pager"
else meh "servicio no instalado" "./scripts/install.sh"; fi

STATUS="$(curl -sf -m 3 http://localhost:8000/api/status || true)"
if [ -z "$STATUS" ]; then bad "la web no responde en :8000" "systemctl status $UNIT ; ./scripts/dev.sh para probar a mano"
else
  ok "la web responde"
  "$REPO/.venv/bin/python" - "$STATUS" <<'PY'
import json, sys
d = json.loads(sys.argv[1]); s, c = d["serial"], d["camera"]
G, R, Y, N = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m", ""
print(f"  {G if s['connected'] else R} ESP32: {'conectado en ' + s['port'] if s['connected'] else 'DESCONECTADO (' + str(s['error']) + ')'}")
print(f"  {G if c['available'] else Y} Webcam: {c['name'] if c['available'] else c['detail']}")
print(f"  · Rover «{d['rover']}»{' [DEMO]' if d['demo'] else ''}, velocidad máx. {d['motion']['max_speed']} %, IP {d['wifi']['ip']}")
PY
fi

head "ESP32 y dispositivos USB"
if [ -e /dev/xera-esp32 ]; then ok "/dev/xera-esp32 → $(readlink -f /dev/xera-esp32)"
elif PORTS="$( (compgen -G '/dev/ttyACM*'; compgen -G '/dev/ttyUSB*') || true)"; [ -n "$PORTS" ]; then meh "hay puertos ($(echo $PORTS)) pero no /dev/xera-esp32" "instala la regla udev: ./scripts/install.sh"
else bad "no hay ningún /dev/ttyACM* ni ttyUSB*" "revisa cable y hub USB: lsusb ; dmesg | tail"; fi
[ -f /etc/udev/rules.d/99-4space-xera.rules ] && ok "regla udev instalada" || meh "regla udev no instalada" "./scripts/install.sh"
systemctl is-active --quiet ModemManager 2>/dev/null && [ ! -f /etc/udev/rules.d/99-4space-xera.rules ] \
  && meh "ModemManager activo sin la regla de exclusión: puede enviar comandos AT al ESP32" "./scripts/install.sh"
found=0
for n in /sys/class/video4linux/video*; do
  [ -e "$n" ] || continue
  [ "$(basename "$(readlink -f "$n/device/driver" 2>/dev/null)")" = uvcvideo ] && [ "$(cat "$n/index" 2>/dev/null)" = 0 ] \
    && { ok "webcam UVC: /dev/$(basename "$n") ($(cat "$n/name"))"; found=1; }
done
[ "$found" = 1 ] || meh "no se ve ninguna webcam USB (es opcional)" "./scripts/test_camera.sh"

head "LEDs del UNO Q"
if [ -e /sys/class/leds/green:user/brightness ]; then
  [ -w /sys/class/leds/green:user/brightness ] && ok "LEDs escribibles" || bad "sin permiso para los LEDs" "usuario en el grupo gpiod"
else meh "esta máquina no tiene los LEDs del UNO Q (normal en un PC)"; fi

head "Red (solo lectura)"
if command -v nmcli >/dev/null; then
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null | awk -F: '$2=="wifi"{printf "  · %s: %s (%s)\n",$1,$3,$4}'
else meh "sin nmcli"; fi

head "Firmware"
if [ -d "$ROOT/firmware" ]; then
  ok "carpeta firmware/ presente"
  command -v pio >/dev/null || [ -x "$HOME/.platformio-venv/bin/pio" ] && ok "PlatformIO instalado" \
    || meh "PlatformIO no instalado (solo hace falta para cargar firmware)" "./scripts/install.sh --with-firmware-tools"
  grep -qiE "watchdog|timeout" "$ROOT/firmware/src/main.cpp" 2>/dev/null && ok "el firmware parece tener un temporizador de seguridad" \
    || meh "el firmware NO tiene watchdog: si se corta el USB, conserva la última orden" "ver docs/uart_protocol.md"
else meh "no hay carpeta firmware/ junto a rover/ (instalación suelta)"; fi

printf '\n'
if [ "$FAIL" -gt 0 ]; then printf '\033[31m%d problema(s)\033[0m y %d aviso(s).\n' "$FAIL" "$WARN"; exit 1
else printf '\033[32mTodo en orden\033[0m (%d aviso(s)).\n' "$WARN"; fi
