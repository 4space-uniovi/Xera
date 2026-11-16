"""Comunicación con el ESP32-S3 por UART/USB.

Este módulo es independiente del resto del backend. Tiene tres piezas:

1. Protocolo (`UartProtocol`): cómo se convierte (x, y) en bytes. Para cambiar
   el formato del mensaje basta con añadir una clase aquí; el resto del backend
   no se entera. Ver docs/uart_protocol.md.
2. Transporte (`Transport`): por dónde salen los bytes. Fase 1: solo el
   `SimulatedTransport` (ESP32 virtual en memoria). La Fase 2 añadirá el
   transporte real con pyserial.
3. `SerialController`: valida, codifica y envía.
"""
from __future__ import annotations

import logging
import math
import threading
from abc import ABC, abstractmethod
from collections import deque
from typing import Callable

log = logging.getLogger(__name__)

LIMIT = 100  # X e Y van de -100 a 100


# --------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------
def validate_xy(x: object, y: object) -> tuple[int, int]:
    """Devuelve (x, y) como enteros o lanza ValueError.

    Estricto: un valor fuera de [-100, 100], NaN, infinito, bool o no numérico
    es un error (nunca se envía nada "adivinado" al ESP32).
    """
    out = []
    for name, v in (("x", x), ("y", y)):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name} debe ser numérico, recibido {v!r}")
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"{name} no es un número finito: {v!r}")
        iv = int(round(v))
        if not -LIMIT <= iv <= LIMIT:
            raise ValueError(f"{name}={iv} fuera de rango [-{LIMIT}, {LIMIT}]")
        out.append(iv)
    return out[0], out[1]


# --------------------------------------------------------------------------
# Protocolos
# --------------------------------------------------------------------------
class UartProtocol(ABC):
    """Convierte (x, y) <-> bytes. x = steering, y = throttle."""

    name: str = "base"

    @abstractmethod
    def encode(self, x: int, y: int) -> bytes: ...

    @abstractmethod
    def decode(self, frame: bytes) -> tuple[int, int]:
        """Inverso de encode (lo usa el simulador del ESP32)."""


class CsvProtocol(UartProtocol):
    """PROVISIONAL: "X,Y\\n", por ejemplo b"50,-25\\n"."""

    name = "csv"

    def encode(self, x: int, y: int) -> bytes:
        return f"{x},{y}\n".encode("ascii")

    def decode(self, frame: bytes) -> tuple[int, int]:
        try:
            xs, ys = frame.decode("ascii").strip().split(",")
            return validate_xy(int(xs), int(ys))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"trama inválida {frame!r}: {exc}") from exc


PROTOCOLS: dict[str, type[UartProtocol]] = {CsvProtocol.name: CsvProtocol}


def register_protocol(cls: type[UartProtocol]) -> type[UartProtocol]:
    """Decorador para añadir un protocolo nuevo."""
    PROTOCOLS[cls.name] = cls
    return cls


def get_protocol(name: str) -> UartProtocol:
    try:
        return PROTOCOLS[name]()
    except KeyError:
        raise ValueError(f"protocolo desconocido {name!r}; disponibles: {sorted(PROTOCOLS)}") from None


# --------------------------------------------------------------------------
# Transportes
# --------------------------------------------------------------------------
class Transport(ABC):
    port: str = ""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Escribe bytes; lanza OSError si el puerto no está disponible."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SimulatedTransport(Transport):
    """ESP32-S3 virtual: guarda las tramas recibidas y la última orden decodificada."""

    def __init__(self, protocol: UartProtocol, port: str = "simulator", history: int = 200):
        self.protocol = protocol
        self.port = port
        self._open = False
        self.frames: deque[bytes] = deque(maxlen=history)
        self.last: tuple[int, int] = (0, 0)
        self.fail_next_writes = 0  # para tests: simula un USB desconectado

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> None:
        if not self._open:
            raise OSError("puerto simulado cerrado")
        if self.fail_next_writes > 0:
            self.fail_next_writes -= 1
            self._open = False
            raise OSError("fallo de escritura simulado")
        self.frames.append(data)
        self.last = self.protocol.decode(data)


# --------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------
class SerialController:
    def __init__(
        self,
        protocol: UartProtocol | None = None,
        transport: Transport | None = None,
        transport_factory: Callable[[UartProtocol], Transport] | None = None,
    ):
        self._lock = threading.Lock()
        self.protocol = protocol or CsvProtocol()
        self._factory = transport_factory or (lambda p: SimulatedTransport(p))
        self.transport = transport or self._factory(self.protocol)
        self.last_sent: tuple[int, int] = (0, 0)
        self.frames_sent = 0
        self.last_error: str | None = None

    # -- ciclo de vida ------------------------------------------------------
    def connect(self) -> bool:
        with self._lock:
            try:
                self.transport.open()
                self.last_error = None
            except OSError as exc:
                self.last_error = str(exc)
                log.warning("no se pudo abrir el puerto: %s", exc)
            return self.transport.is_open

    def close(self) -> None:
        with self._lock:
            self.transport.close()

    def set_protocol(self, name: str) -> None:
        proto = get_protocol(name)
        with self._lock:
            self.protocol = proto
            if isinstance(self.transport, SimulatedTransport):
                self.transport.protocol = proto

    # -- envío --------------------------------------------------------------
    def send(self, x: object, y: object) -> bool:
        """Valida, codifica y escribe. Devuelve True si la trama salió."""
        xi, yi = validate_xy(x, y)  # ValueError si es inválido: se propaga
        frame = self.protocol.encode(xi, yi)
        with self._lock:
            try:
                self.transport.write(frame)
            except OSError as exc:
                self.last_error = str(exc)
                log.error("error de escritura serie: %s", exc)
                return False
            self.last_sent = (xi, yi)
            self.frames_sent += 1
            return True

    def stop(self) -> bool:
        return self.send(0, 0)

    # -- estado -------------------------------------------------------------
    def status(self) -> dict:
        return {
            "connected": self.transport.is_open,
            "simulated": isinstance(self.transport, SimulatedTransport),
            "port": self.transport.port,
            "protocol": self.protocol.name,
            "last_sent": {"x": self.last_sent[0], "y": self.last_sent[1]},
            "frames_sent": self.frames_sent,
            "error": self.last_error,
        }
