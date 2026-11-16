#!/usr/bin/env bash
# Instala y configura todo lo necesario en el ordenador de a bordo (Arduino UNO Q / Raspberry Pi).
# Equivale a rover/scripts/install.sh — mira sus opciones con:  ./install.sh --help
exec "$(cd "$(dirname "$0")" && pwd)/rover/scripts/install.sh" "$@"
