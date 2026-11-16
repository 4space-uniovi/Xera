#!/usr/bin/env bash
# Actualiza la app del rover desde GitHub (git pull + aplicar cambios). Equivale a rover/scripts/update.sh
exec "$(cd "$(dirname "$0")" && pwd)/rover/scripts/update.sh" "$@"
