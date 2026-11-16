#!/usr/bin/env bash
# Instalador de la app de control XERA / 4SPACE Mini Rover. Idempotente.
#
#   ./install.sh                       # interactivo: pregunta antes de cada cambio del sistema
#   ./install.sh --yes                 # responde "sí" a todo (no interactivo)
#   ./install.sh --dry-run             # solo muestra lo que haría, sin cambiar nada
#   ./install.sh --rover-id 03         # nombre del rover: 4SPACE-ROVER-03
#   ./install.sh --no-service          # no instala el servicio systemd (PC de desarrollo)
#   ./install.sh --force               # permite arquitecturas que no son ARM64
#
# NO toca la red ni NetworkManager.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"          # carpeta rover/
USER_NAME="${SUDO_USER:-$(id -un)}"
UNIT=4space-rover.service
UDEV_RULE=/etc/udev/rules.d/99-4space-xera.rules
YES=0; DRY=0; ROVER_ID=""; FORCE=0; NO_SERVICE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --rover-id) ROVER_ID="${2:?falta el identificador}"; shift ;;
    --no-service) NO_SERVICE=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1 (usa --help)"; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask()  { # ask "pregunta" -> 0 si sí
  if [ "$DRY" = 1 ]; then echo "  $1 [dry-run: se asume que sí]"; return 0; fi
  if [ "$YES" = 1 ]; then echo "  $1 [s/N] s (--yes)"; return 0; fi
  read -r -p "  $1 [s/N] " a; [[ "$a" =~ ^[sSyY]$ ]]
}
# do_cmd <cmd...>: ejecuta, o solo lo muestra en --dry-run
do_cmd() {
  if [ "$DRY" = 1 ]; then printf '  \033[2m[dry-run] %s\033[0m\n' "$*"; else "$@"; fi
}

[ "$DRY" = 1 ] && printf '\033[1;33mMODO SIMULACIÓN (--dry-run): no se cambia nada.\033[0m\n'
if [ "$(id -u)" = 0 ]; then
  echo "No ejecutes este script como root: usa tu usuario (pedirá sudo cuando haga falta)."; exit 1
fi

# ---------------------------------------------------------------------------
say "1/7 Arquitectura"
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then ok "ARM64 ($ARCH)"
elif [ "$FORCE" = 1 ]; then warn "Arquitectura $ARCH (continúo por --force)"
else echo "Este instalador es para ARM64 (UNO Q / Raspberry Pi); aquí hay $ARCH. Usa --force para instalar igualmente."; exit 1; fi

# ---------------------------------------------------------------------------
say "2/7 Dependencias del sistema"
missing=()
command -v python3 >/dev/null || missing+=(python3)
python3 -c "import ensurepip" 2>/dev/null || missing+=(python3-venv python3-pip)
command -v v4l2-ctl >/dev/null || missing+=(v4l-utils)
command -v git >/dev/null || missing+=(git)
if [ ${#missing[@]} -eq 0 ]; then ok "python3, venv, v4l2-ctl y git presentes"
elif ! command -v apt-get >/dev/null; then
  warn "Faltan: ${missing[*]} (no es Debian/apt: instálalos a mano)"
else
  warn "Faltan paquetes: ${missing[*]}"
  if ask "¿Instalarlos con 'sudo apt-get install'?"; then do_cmd sudo apt-get install -y "${missing[@]}"
  else echo "Instálalos y vuelve a ejecutar:  sudo apt-get install ${missing[*]}"; exit 1; fi
fi

# ---------------------------------------------------------------------------
say "3/7 Entorno virtual Python (.venv)"
cd "$REPO"
if [ -x .venv/bin/python ]; then ok ".venv ya existe"
else do_cmd python3 -m venv .venv && ok "creado .venv"; fi
if [ "$DRY" = 1 ]; then echo "  [dry-run] .venv/bin/python -m pip install -r requirements.txt"
else .venv/bin/python -m pip install -q -r requirements.txt && ok "dependencias Python instaladas en .venv"; fi

# ---------------------------------------------------------------------------
say "4/7 Permisos de dispositivos (grupos)"
for g in dialout video gpiod; do
  getent group "$g" >/dev/null || { warn "el grupo $g no existe (se omite)"; continue; }
  if id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx "$g"; then ok "$USER_NAME ya está en el grupo $g"
  elif ask "¿Añadir a $USER_NAME al grupo $g?"; then do_cmd sudo usermod -aG "$g" "$USER_NAME"; ok "añadido a $g (cierra sesión y vuelve a entrar para notarlo en tu shell)"
  else warn "sin el grupo $g algunas funciones no irán"; fi
done

# ---------------------------------------------------------------------------
say "5/7 Regla udev del ESP32 (/dev/xera-esp32 y sin ModemManager)"
if ! command -v udevadm >/dev/null; then warn "sin udev: se omite"
else
  RULE_TMP="$(mktemp)"; trap 'rm -f "$RULE_TMP"' EXIT
  cat > "$RULE_TMP" <<'RULE'
# 4SPACE XERA: ESP32-S3 por USB nativo (303a:*) o por puente CH343 (1a86:55d3).
#  - ModemManager no debe sondearlo (le mandaría comandos AT).
#  - Enlace estable /dev/xera-esp32, independiente de si es ttyACM0, ttyACM1...
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="303a", ENV{ID_MM_DEVICE_IGNORE}="1", SYMLINK+="xera-esp32"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="55d3", ENV{ID_MM_DEVICE_IGNORE}="1", SYMLINK+="xera-esp32"
RULE
  if [ -f "$UDEV_RULE" ] && cmp -s "$RULE_TMP" "$UDEV_RULE"; then ok "regla udev ya instalada"
  elif ask "¿Instalar $UDEV_RULE?"; then
    do_cmd sudo install -m 0644 "$RULE_TMP" "$UDEV_RULE"
    do_cmd sudo udevadm control --reload-rules
    do_cmd sudo udevadm trigger --subsystem-match=tty --action=add
    ok "regla instalada (si el ESP32 está conectado, aparecerá /dev/xera-esp32)"
  else warn "sin la regla, ModemManager puede interferir con el ESP32"; fi
fi

# ---------------------------------------------------------------------------
say "6/7 Identificador y configuración del rover"
if [ -z "$ROVER_ID" ] && [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then
  read -r -p "  Número/identificador del rover (Enter = no cambiar): " ROVER_ID || true
fi
[ -f config/rover.yaml ] || { do_cmd cp config/rover.example.yaml config/rover.yaml; ok "config/rover.yaml creado desde el ejemplo"; }
if [ -n "$ROVER_ID" ]; then
  NAME="4SPACE-ROVER-${ROVER_ID#4SPACE-ROVER-}"
  if [ "$DRY" = 1 ]; then echo "  [dry-run] rover.name y wifi.ap_ssid = $NAME"
  else
    .venv/bin/python - "$NAME" <<'PY'
import sys
from backend.config import load_settings, merge_settings, save_settings
name = sys.argv[1]
s = merge_settings(load_settings(), {"rover": {"name": name}, "wifi": {"ap_ssid": name}})
save_settings(s)
print("  ✔ rover.name y wifi.ap_ssid =", name)
PY
  fi
else ok "sin cambios de nombre"; fi

# ---------------------------------------------------------------------------
say "7/7 Servicio systemd ($UNIT)"
if [ "$NO_SERVICE" = 1 ]; then warn "omitido (--no-service)"
elif ! command -v systemctl >/dev/null; then warn "sin systemd: se omite"
else
  TMP="$(mktemp)"
  sed -e "s|@REPO@|$REPO|g" -e "s|@USER@|$USER_NAME|g" systemd/4space-rover.service.in > "$TMP"
  DEST="/etc/systemd/system/$UNIT"
  if [ -f "$DEST" ] && cmp -s "$TMP" "$DEST"; then ok "$UNIT ya está instalado y actualizado"
  elif ask "¿Instalar $DEST? (se arranca solo al encender)"; then
    do_cmd sudo install -m 0644 "$TMP" "$DEST"; do_cmd sudo systemctl daemon-reload; ok "instalado"
  else warn "servicio NO instalado"; fi
  rm -f "$TMP"

  if [ "$DRY" = 1 ] || [ -f "$DEST" ]; then
    if [ "$DRY" = 0 ] && systemctl is-enabled --quiet "$UNIT" 2>/dev/null; then ok "arranque automático ya activo"
    elif ask "¿Activar el arranque automático (enable)?"; then do_cmd sudo systemctl enable "$UNIT"; ok "arranque automático activado"; fi
    if ask "¿Arrancar/reiniciar el servicio ahora?"; then
      do_cmd sudo systemctl restart "$UNIT"
      if [ "$DRY" = 0 ]; then
        sleep 2
        systemctl is-active --quiet "$UNIT" && ok "servicio activo" || { warn "no arrancó"; journalctl -u "$UNIT" -n 15 --no-pager; exit 1; }
      fi
    fi
  fi
fi

IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)"
printf '\nListo%s.\n  Web:    http://%s:8000\n  Logs:   journalctl -u %s -f\n  Estado: %s/scripts/doctor.sh\n  Actualizar más adelante: git pull && ./install.sh --yes   (o ./update.sh)\n' \
  "$([ "$DRY" = 1 ] && echo ' (simulación)')" "${IP:-<ip-del-rover>}" "$UNIT" "$REPO"
