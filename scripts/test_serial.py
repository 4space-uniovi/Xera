#!/usr/bin/env python3
"""Prueba del puerto serie del ESP32-S3 SIN arrancar el servidor web.

  python scripts/test_serial.py --list              # lista puertos USB-serie
  python scripts/test_serial.py --port /dev/ttyACM0 --listen 5   # solo escucha 5 s
  python scripts/test_serial.py --port auto --move --speed 20    # ¡mueve los motores!

--move envía una secuencia suave (adelante, parada, atrás, parada, giros) y SIEMPRE
termina con 0,0, incluso con Ctrl-C. Levanta las ruedas del suelo antes de usarlo.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.controllers.serial_controller import (  # noqa: E402
    PROTOCOLS, PySerialTransport, SerialController, get_protocol, list_serial_ports)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="listar puertos y salir")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--protocol", default="csv", choices=sorted(PROTOCOLS))
    ap.add_argument("--listen", type=float, default=0, help="escuchar N segundos lo que envíe el ESP32")
    ap.add_argument("--move", action="store_true", help="enviar una secuencia de movimiento (MUEVE LOS MOTORES)")
    ap.add_argument("--speed", type=int, default=20, help="%% máximo de la secuencia (por defecto 20)")
    args = ap.parse_args()

    ports = list_serial_ports()
    if args.list or not ports:
        print("Puertos USB-serie:" if ports else "No se detecta ningún /dev/ttyACM* ni /dev/ttyUSB*.")
        for p in ports:
            print(f"  {p['device']}  {p['description']}  (VID:PID {p['vid']}:{p['pid']})")
        if not ports:
            print("Comprueba el cable/hub USB y mira `dmesg | tail`.")
        return 0 if args.list else 1

    ctrl = SerialController(get_protocol(args.protocol), port=args.port, baudrate=args.baud,
                            transport_factory=lambda p, b: PySerialTransport(p, b))
    if not ctrl.connect():
        print("No se pudo abrir el puerto:", ctrl.status()["error"])
        return 1
    print(f"Conectado a {ctrl.status()['port']} @ {args.baud}")

    try:
        if args.listen:
            end = time.time() + args.listen
            print(f"Escuchando {args.listen:.0f} s...")
            while time.time() < end:
                ctrl.poll_rx()
                if ctrl.last_rx:
                    print("  ESP32 >", ctrl.last_rx)
                    ctrl.last_rx = ""
                time.sleep(0.1)
        if args.move:
            v = max(0, min(100, args.speed))
            seq = [("adelante", 0, v), ("parar", 0, 0), ("atrás", 0, -v), ("parar", 0, 0),
                   ("giro derecha", v, 0), ("parar", 0, 0), ("giro izquierda", -v, 0), ("parar", 0, 0)]
            print(f"Secuencia al {v} %. Ctrl-C para parar.")
            for name, x, y in seq:
                print(f"  {name:15s} -> {x},{y}")
                end = time.time() + 1.0
                while time.time() < end:          # reenviar a 20 Hz, como hace la web
                    ctrl.send(x, y)
                    time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nInterrumpido.")
    finally:
        for _ in range(3):
            ctrl.send(0, 0)
            time.sleep(0.02)
        ctrl.close()
        print("Parado (0,0) y puerto cerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
