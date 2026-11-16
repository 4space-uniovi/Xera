"""Lógica de control de movimiento: dueño único, límite de velocidad y watchdog.

No sabe nada de HTTP ni de WebSockets: recibe identificadores de cliente y
valores (x, y). Así se puede probar con un reloj falso, sin red ni hardware.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Callable

from .controllers.serial_controller import LIMIT, SerialController

log = logging.getLogger(__name__)


def sanitize_xy(x: object, y: object) -> tuple[int, int]:
    """Entrada del joystick -> enteros en [-100, 100].

    Lanza ValueError si no es un número finito. Los valores fuera de rango se
    recortan (clamp): un joystick puede pasarse unas décimas sin ser un error.
    """
    out = []
    for name, v in (("x", x), ("y", y)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name} inválido: {v!r}")
        out.append(max(-LIMIT, min(LIMIT, int(round(v)))))
    return out[0], out[1]


def scale_speed(x: int, y: int, max_speed: int) -> tuple[int, int]:
    """Aplica el límite de velocidad (20-100 %) a ambos ejes."""
    f = max_speed / 100
    return int(round(x * f)), int(round(y * f))


class MotionManager:
    def __init__(
        self,
        serial: SerialController,
        max_speed: int = 60,
        watchdog_s: float = 0.3,
        control_timeout_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.serial = serial
        self.max_speed = max_speed
        self.watchdog_s = watchdog_s
        self.control_timeout_s = control_timeout_s
        self.clock = clock

        self.clients: set[str] = set()
        self.owner: str | None = None
        self.output: tuple[int, int] = (0, 0)   # lo último enviado al ESP32
        self.watchdog_trips = 0
        self._last_cmd = 0.0                     # instante de la última orden válida
        self._owner_seen = 0.0                   # última actividad del dueño
        self.on_change: Callable[[], None] | None = None

    # -- utilidades ---------------------------------------------------------
    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    def _apply(self, x: int, y: int) -> None:
        try:
            self.serial.send(x, y)
        except ValueError:  # no debería ocurrir tras sanitize_xy
            log.exception("orden rechazada por el controlador serie")
            return
        self.output = (x, y)

    def emergency_stop(self) -> None:
        """Envía (0,0) siempre, aunque la salida ya fuera (0,0)."""
        self._apply(0, 0)

    # -- clientes -----------------------------------------------------------
    def connect(self, cid: str) -> None:
        self.clients.add(cid)
        self._changed()

    def disconnect(self, cid: str) -> None:
        self.clients.discard(cid)
        if cid == self.owner:
            self.owner = None
            self.emergency_stop()  # el que conducía se fue: parar
        self._changed()

    # -- control exclusivo --------------------------------------------------
    def request_control(self, cid: str) -> bool:
        if cid not in self.clients:
            return False
        if self.owner not in (None, cid):
            return False
        if self.owner is None:
            self.owner = cid
            self._owner_seen = self._last_cmd = self.clock()
            self._changed()
        return True

    def release_control(self, cid: str) -> bool:
        if cid != self.owner:
            return False
        self.owner = None
        self.emergency_stop()
        self._changed()
        return True

    # -- órdenes ------------------------------------------------------------
    def move(self, cid: str, x: object, y: object) -> bool:
        """Solo el dueño puede mover. Una orden inválida se ignora (y no
        alimenta el watchdog)."""
        if cid != self.owner:
            return False
        try:
            xi, yi = sanitize_xy(x, y)
        except ValueError:
            return False
        now = self.clock()
        self._owner_seen = self._last_cmd = now
        out = scale_speed(xi, yi, self.max_speed)
        changed = out != self.output
        self._apply(*out)
        if changed:
            self._changed()
        return True

    def stop(self, cid: str | None = None) -> None:
        """STOP: lo puede pulsar cualquier cliente (parar nunca es peligroso)."""
        self.emergency_stop()
        self._last_cmd = self.clock()
        self._changed()

    def set_max_speed(self, value: int) -> None:
        self.max_speed = value
        self._changed()

    # -- watchdog -----------------------------------------------------------
    def check(self) -> None:
        """Llamar periódicamente (cada ~50 ms)."""
        now = self.clock()
        if self.owner is None:
            return
        if self.output != (0, 0) and now - self._last_cmd > self.watchdog_s:
            self.watchdog_trips += 1
            log.warning("watchdog: sin órdenes durante %.0f ms -> (0,0)", self.watchdog_s * 1000)
            self.emergency_stop()
            self._changed()
        if now - self._owner_seen > self.control_timeout_s:
            log.info("el cliente %s pierde el control por inactividad", self.owner)
            self.owner = None
            self.emergency_stop()
            self._changed()

    # -- estado -------------------------------------------------------------
    def snapshot(self, cid: str | None = None) -> dict:
        return {
            "clients": len(self.clients),
            "owner_present": self.owner is not None,
            "is_owner": cid is not None and cid == self.owner,
            "max_speed": self.max_speed,
            "output": {"x": self.output[0], "y": self.output[1]},
            "watchdog_trips": self.watchdog_trips,
        }
