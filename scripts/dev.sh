#!/usr/bin/env bash
# Arranca el rover en modo demo (sin ESP32 ni webcam) para desarrollar.
# No toca la red ni instala servicios.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "No existe .venv. Créalo con:"
  echo "  sudo apt install python3-venv python3-pip   # una sola vez"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
  exit 1
fi
exec .venv/bin/python -m backend.main --demo "$@"
