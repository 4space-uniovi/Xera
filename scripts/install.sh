#!/usr/bin/env bash
# Instalador de 4SPACE Mini Rover. Idempotente: se puede ejecutar varias veces.
#
#   ./scripts/install.sh                 # pregunta antes de cada cambio del sistema
#   ./scripts/install.sh --yes           # responde "sí" a todo (modo no interactivo)
#   ./scripts/install.sh --rover-id 03   # nombre del rover: 4SPACE-ROVER-03
#
# NO toca la red ni NetworkManager. Instala el servicio systemd del backend.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"
UNIT=4space-rover.service
YES=0; ROVER_ID=""; FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --rover-id) ROVER_ID="${2:?falta el identificador}"; shift ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask()  { # ask "pregunta" -> 0 si sí
  [ "$YES" = 1 ] && { echo "  $1 [s/N] s (--yes)"; return 0; }
  read -r -p "  $1 [s/N] " a; [[ "$a" =~ ^[sSyY]$ ]]
}

if [ "$(id -u)" = 0 ]; then
  echo "No ejecutes este script como root: usa tu usuario (pedirá sudo cuando haga falta)."; exit 1
fi

say "1/6 Arquitectura"
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then ok "ARM64 ($ARCH)"
elif [ "$FORCE" = 1 ]; then warn "Arquitectura $ARCH (continúo por --force)"
else echo "Este instalador es para el UNO Q (ARM64); aquí hay $ARCH. Usa --force para instalar igualmente."; exit 1; fi

say "2/6 Dependencias del sistema"
missing=()
command -v python3 >/dev/null || missing+=(python3)
python3 -c "import ensurepip" 2>/dev/null || missing+=(python3-venv python3-pip)
command -v v4l2-ctl >/dev/null || missing+=(v4l-utils)
if [ ${#missing[@]} -eq 0 ]; then ok "python3, venv y v4l2-ctl presentes"
else
  warn "Faltan paquetes: ${missing[*]}"
  if ask "¿Instalarlos con 'sudo apt-get install'?"; then sudo apt-get install -y "${missing[@]}"
  else echo "Instálalos y vuelve a ejecutar:  sudo apt-get install ${missing[*]}"; exit 1; fi
fi

say "3/6 Entorno virtual Python"
cd "$REPO"
[ -x .venv/bin/python ] || { python3 -m venv .venv; ok "creado .venv"; }
.venv/bin/python -m pip install -q -r requirements.txt && ok "dependencias Python instaladas en .venv"

say "4/6 Permisos de dispositivos"
for g in dialout video gpiod; do
  getent group "$g" >/dev/null || { warn "el grupo $g no existe (se omite)"; continue; }
  if id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx "$g"; then ok "$USER_NAME ya está en el grupo $g"
  elif ask "¿Añadir a $USER_NAME al grupo $g?"; then sudo usermod -aG "$g" "$USER_NAME"; ok "añadido a $g (cierra sesión y vuelve a entrar para notarlo en tu shell)"
  else warn "sin el grupo $g algunas funciones no irán"; fi
done

say "5/6 Identificador del rover"
if [ -z "$ROVER_ID" ] && [ "$YES" = 0 ]; then
  read -r -p "  Número/identificador del rover (Enter = no cambiar): " ROVER_ID || true
fi
if [ -n "$ROVER_ID" ]; then
  NAME="4SPACE-ROVER-${ROVER_ID#4SPACE-ROVER-}"
  .venv/bin/python - "$NAME" <<'PY'
import sys
from backend.config import load_settings, merge_settings, save_settings
name = sys.argv[1]
s = merge_settings(load_settings(), {"rover": {"name": name}, "wifi": {"ap_ssid": name}})
save_settings(s)
print("  ✔ rover.name y wifi.ap_ssid =", name)
PY
else ok "sin cambios"; fi
[ -f config/rover.yaml ] || { cp config/rover.example.yaml config/rover.yaml; ok "creado config/rover.yaml desde el ejemplo"; }

say "6/6 Servicio systemd ($UNIT)"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
sed -e "s|@REPO@|$REPO|g" -e "s|@USER@|$USER_NAME|g" systemd/4space-rover.service.in > "$TMP"
DEST="/etc/systemd/system/$UNIT"
if [ -f "$DEST" ] && cmp -s "$TMP" "$DEST"; then ok "$UNIT ya está instalado y actualizado"
elif ask "¿Instalar $DEST? (se arranca solo al encender)"; then
  sudo install -m 0644 "$TMP" "$DEST"; sudo systemctl daemon-reload; ok "instalado"
else echo "Cancelado: no se instaló el servicio."; exit 0; fi

if ! systemctl is-enabled --quiet "$UNIT" 2>/dev/null; then
  ask "¿Activar el arranque automático (enable)?" && { sudo systemctl enable "$UNIT"; ok "arranque automático activado"; }
else ok "arranque automático ya activo"; fi
if ask "¿Arrancar/reiniciar el servicio ahora?"; then
  sudo systemctl restart "$UNIT"; sleep 2
  systemctl is-active --quiet "$UNIT" && ok "servicio activo" || { warn "no arrancó"; journalctl -u "$UNIT" -n 15 --no-pager; exit 1; }
fi

IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n "s/.* src \([0-9.]*\).*/\1/p" | head -1)"
printf '\nListo. Web: http://%s:8000\nLogs:  journalctl -u %s -f\n' "${IP:-<ip>}" "$UNIT"
