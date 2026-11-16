#!/usr/bin/env bash
# Diagnóstico de la instalación (solo lectura). Equivale a rover/scripts/doctor.sh
exec "$(cd "$(dirname "$0")" && pwd)/rover/scripts/doctor.sh" "$@"
