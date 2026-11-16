#!/usr/bin/env bash
# Desinstala el servicio de 4SPACE Mini Rover. No borra el código ni la configuración.
#   ./scripts/uninstall.sh            # quita el servicio
#   ./scripts/uninstall.sh --purge    # además borra .venv
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=4space-rover.service
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1

if systemctl list-unit-files "$UNIT" 2>/dev/null | grep -q "$UNIT"; then
  sudo systemctl disable --now "$UNIT" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$UNIT"
  sudo systemctl daemon-reload
  echo "Servicio $UNIT eliminado."
else
  echo "El servicio $UNIT no estaba instalado."
fi
[ "$PURGE" = 1 ] && { rm -rf "$REPO/.venv"; echo ".venv borrado."; }
echo "El código y config/rover.yaml se conservan."
