"""Keyboard teleoperation of XERA from Python (teleop_twist_keyboard style).

The firmware expects lines "throttle,steering\\n" with values in -100..100.
The current command is resent continuously (20 Hz) so the rover keeps moving.

Usage:
    pip install pyserial
    python drive.py /dev/ttyACM0      # Linux / Raspberry Pi
    python drive.py COM5              # Windows

Keys:
       u    i    o         i : forward
       j    k    l         , : backward
       m    ,    .         j / l : turn left / right
                           u / o : forward turning left / right
    k : stop               m / . : backward turning left / right

    w / s : increase / decrease linear speed   (throttle)
    e / d : increase / decrease angular speed  (steering)
    q or Ctrl-C : quit (stops the motors)
"""

import argparse
import sys
import time

import serial

SEND_HZ = 20
BAUDRATE = 115200
SPEED_STEP = 10
LIN_START = 40
ANG_START = 40

# key -> (linear direction, turn direction); turn +1 = left
MOVES = {
    "i": (1, 0),
    "u": (1, 1),
    "o": (1, -1),
    "j": (0, 1),
    "l": (0, -1),
    "k": (0, 0),
    ",": (-1, 0),
    "m": (-1, 1),
    ".": (-1, -1),
}


if sys.platform == "win32":
    import msvcrt

    class Keyboard:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def get(self):
            """Return the last key pressed, or None, without blocking."""
            key = None
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # special key: discard the 2nd byte
                    msvcrt.getwch()
                    continue
                key = ch
            return key

else:
    import select
    import termios
    import tty

    class Keyboard:
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            return self

        def __exit__(self, *exc):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

        def get(self):
            key = None
            while select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1)
            return key


def clamp(value: int) -> int:
    return max(-100, min(100, int(value)))


def send(port: serial.Serial, throttle: int, steering: int) -> None:
    port.write(f"{clamp(throttle)},{clamp(steering)}\n".encode())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XERA keyboard teleop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Keys:")[1],
    )
    parser.add_argument("port", help="serial port (COM5, /dev/ttyACM0, ...)")
    parser.add_argument("--baud", type=int, default=BAUDRATE)
    args = parser.parse_args()

    lin, ang = LIN_START, ANG_START
    x, th = 0, 0

    print(__doc__.split("Keys:")[1])
    print(f"linear: {lin}  angular: {ang}")

    with serial.Serial(args.port, args.baud) as port, Keyboard() as kb:
        try:
            while True:
                key = kb.get()
                if key is not None:
                    key = key.lower()
                    if key in MOVES:
                        x, th = MOVES[key]
                    elif key in ("w", "s"):
                        lin = clamp(lin + (SPEED_STEP if key == "w" else -SPEED_STEP))
                        lin = max(0, lin)
                        print(f"linear: {lin}  angular: {ang}")
                    elif key in ("e", "d"):
                        ang = clamp(ang + (SPEED_STEP if key == "e" else -SPEED_STEP))
                        ang = max(0, ang)
                        print(f"linear: {lin}  angular: {ang}")
                    elif key in ("q", "\x03"):
                        break

                # in the firmware steering > 0 turns right; turn +1 is left
                send(port, x * lin, -th * ang)
                time.sleep(1 / SEND_HZ)
        except KeyboardInterrupt:
            pass
        finally:
            send(port, 0, 0)  # always stop on exit


if __name__ == "__main__":
    main()
