#!/usr/bin/env bash
# Arranca el rover con hardware REAL (ESP32 por USB + webcam). Sin --demo.
# Para que siga vivo al cerrar SSH:   nohup ./scripts/run.sh > /tmp/rover.log 2>&1 &   (o instala tmux)
# (el arranque automático con systemd llega en la Fase 5)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Falta .venv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
exec .venv/bin/python -m backend.main "$@"
