#!/usr/bin/env bash
# Comprueba la webcam USB sin arrancar el servidor web.
#   ./scripts/test_camera.sh            # detecta cámaras y captura un fotograma
#   ./scripts/test_camera.sh /dev/video2
set -uo pipefail

if ! command -v v4l2-ctl >/dev/null; then
  echo "Falta v4l2-ctl:  sudo apt install v4l-utils"; exit 1
fi

echo "== Cámaras USB (UVC) detectadas =="
found=()
for n in /sys/class/video4linux/video*; do
  [ -e "$n" ] || continue
  drv=$(basename "$(readlink -f "$n/device/driver" 2>/dev/null)")
  idx=$(cat "$n/index" 2>/dev/null)
  if [ "$drv" = "uvcvideo" ] && [ "$idx" = "0" ]; then
    dev="/dev/$(basename "$n")"; found+=("$dev"); echo "  $dev  $(cat "$n/name")"
  fi
done
if [ ${#found[@]} -eq 0 ]; then
  echo "  (ninguna). Conecta la webcam al hub y mira:  dmesg | tail -20 ;  lsusb"
  echo "  Nota: /dev/video0 y /dev/video1 del UNO Q son códecs del chip, no webcams."
  exit 1
fi

dev="${1:-${found[0]}}"
echo; echo "== Formatos de $dev =="
v4l2-ctl -d "$dev" --list-formats-ext | grep -E "\[[0-9]\]|Size:" | head -20
echo; echo "== Capturando 1 fotograma MJPEG 640x480 =="
out=/tmp/rover_test_frame.jpg
if v4l2-ctl -d "$dev" --set-fmt-video=width=640,height=480,pixelformat=MJPG \
     --stream-mmap=3 --stream-count=1 --stream-to="$out" 2>/dev/null && [ -s "$out" ]; then
  echo "OK: $out ($(stat -c %s "$out") bytes). Ábrelo o descárgalo con scp para verlo."
else
  echo "FALLO: la cámara no entrega MJPG a 640x480 (¿ocupada por otro proceso? ¿solo YUYV?)."
  exit 1
fi
