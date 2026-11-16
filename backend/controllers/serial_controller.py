"""Comunicación con el ESP32-S3 por UART/USB.

Este módulo es independiente del resto del backend. Tiene tres piezas:

1. Protocolo (`UartProtocol`): cómo se convierte (x, y) en bytes. Para cambiar
   el formato del mensaje basta con añadir una clase aquí; el resto del backend
   no se entera. Ver docs/uart_protocol.md.
2. Transporte (`Transport`): por dónde salen los bytes: `PySerialTransport`
   (USB real) o `SimulatedTransport` (ESP32 virtual en memoria, modo demo).
3. `SerialController`: valida, codifica, envía y se reconecta solo si el USB
   se desconecta.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
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
    """Protocolo del firmware actual: "X,Y\\n", por ejemplo b"50,-25\\n"."""

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
    baudrate: int = 0

    def read_available(self) -> bytes:
        """Bytes que haya enviado el dispositivo (por defecto, nada)."""
        return b""

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


PORT_RE = re.compile(r"^/dev/(ttyACM\d+|ttyUSB\d+)$")


def list_serial_ports() -> list[dict]:
    """Puertos USB-serie candidatos (ttyACM*/ttyUSB*). Ignora los ttyS* internos."""
    from serial.tools import list_ports

    out = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        if PORT_RE.match(p.device):
            out.append({"device": p.device, "description": p.description or "",
                        "vid": p.vid, "pid": p.pid})
    return out


class PySerialTransport(Transport):
    """Puerto USB-serie real. Las escrituras no bloquean más de 0,2 s."""

    def __init__(self, port: str, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self._ser = None

    def open(self) -> None:
        import serial

        ser = serial.Serial()
        ser.port = self.port
        ser.baudrate = self.baudrate
        ser.timeout = 0
        ser.write_timeout = 0.2
        # DTR/RTS a False ANTES de abrir: en muchas placas ESP32 esas líneas
        # resetean el chip o lo meten en modo bootloader al abrir el puerto.
        ser.dtr = False
        ser.rts = False
        try:
            ser.open()
        except serial.SerialException as exc:
            raise OSError(str(exc)) from exc
        self._ser = ser

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 - ya estaba muerto
                pass

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def write(self, data: bytes) -> None:
        import serial

        if not self.is_open:
            raise OSError("puerto serie cerrado")
        try:
            self._ser.write(data)
        except (serial.SerialException, OSError) as exc:
            self.close()  # USB desconectado: que el supervisor reintente
            raise OSError(str(exc)) from exc

    def read_available(self) -> bytes:
        """Lo que el ESP32 haya enviado (mensajes de depuración). No bloquea."""
        if not self.is_open:
            return b""
        try:
            n = self._ser.in_waiting
            return self._ser.read(n) if n else b""
        except (OSError, Exception):  # noqa: BLE001
            self.close()
            return b""


# --------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------
class SerialController:
    """Valida, codifica y envía órdenes; mantiene la conexión con el ESP32.

    Dos modos:
    - `transport=` dado (tests/demo): se usa ese transporte tal cual.
    - `transport_factory=` dado (real): el puerto se resuelve ("auto" = el
      primer ttyACM/ttyUSB) y `ensure_connected()` reabre tras desconexiones.
    """

    RETRY_INTERVAL_S = 1.0

    def __init__(
        self,
        protocol: UartProtocol | None = None,
        transport: Transport | None = None,
        transport_factory: Callable[[str, int], Transport] | None = None,
        port: str = "auto",
        baudrate: int = 115200,
        ports_provider: Callable[[], list[dict]] = list_serial_ports,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._lock = threading.Lock()
        self.protocol = protocol or CsvProtocol()
        self.transport = transport
        self._factory = transport_factory
        self.port = port
        self.baudrate = baudrate
        self._ports = ports_provider
        self._clock = clock
        self._last_attempt = -1e9
        self.last_sent: tuple[int, int] = (0, 0)
        self.frames_sent = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.last_rx: str = ""  # última línea que mandó el ESP32 (depuración)
        if self.transport is None and self._factory is None:
            self.transport = SimulatedTransport(self.protocol)

    # -- conexión -----------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.transport is not None and self.transport.is_open

    def resolve_port(self) -> str | None:
        """'auto' -> primer puerto USB-serie detectado; si no, el configurado."""
        if self.port != "auto":
            return self.port
        found = self._ports()
        return found[0]["device"] if found else None

    def connect(self) -> bool:
        with self._lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        self._last_attempt = self._clock()
        if self._factory is not None:
            port = self.resolve_port()
            if port is None:
                self.last_error = "no se detecta ningún puerto USB-serie (¿ESP32 conectado?)"
                return False
            if self.transport is None or self.transport.port != port or self.transport.baudrate != self.baudrate:
                if self.transport is not None:
                    self.transport.close()
                self.transport = self._factory(port, self.baudrate)
        try:
            self.transport.open()
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)
            log.warning("no se pudo abrir el puerto: %s", exc)
        return self.transport.is_open

    def ensure_connected(self) -> bool:
        """Llamar periódicamente (~1 s): reabre el puerto si se perdió."""
        with self._lock:
            if self.connected:
                return True
            if self._clock() - self._last_attempt < self.RETRY_INTERVAL_S:
                return False
            ok = self._connect_locked()
            if ok:
                self.reconnects += 1
                log.info("puerto serie conectado: %s", self.transport.port)
            return ok

    def close(self) -> None:
        with self._lock:
            if self.transport is not None:
                self.transport.close()

    def reconfigure(self, port: str, baudrate: int, protocol: str) -> None:
        """Aplica ajustes nuevos: cierra y deja que `ensure_connected` reabra."""
        proto = get_protocol(protocol)
        with self._lock:
            self.protocol = proto
            changed = (port, baudrate) != (self.port, self.baudrate)
            self.port, self.baudrate = port, baudrate
            if isinstance(self.transport, SimulatedTransport):
                self.transport.protocol = proto
            if changed and self.transport is not None:
                self.transport.close()
                self._last_attempt = -1e9  # reintentar ya

    def set_protocol(self, name: str) -> None:
        self.reconfigure(self.port, self.baudrate, name)

    # -- envío --------------------------------------------------------------
    def send(self, x: object, y: object) -> bool:
        """Valida, codifica y escribe. Devuelve True si la trama salió."""
        xi, yi = validate_xy(x, y)  # ValueError si es inválido: se propaga
        frame = self.protocol.encode(xi, yi)
        with self._lock:
            if not self.connected:
                self.last_error = self.last_error or "puerto serie desconectado"
                return False
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

    def poll_rx(self) -> None:
        """Recoge texto que haya enviado el ESP32 (se muestra en Estado)."""
        with self._lock:
            if self.transport is None:
                return
            data = self.transport.read_available()
        lines = data.decode("utf-8", "replace").strip().splitlines()
        if lines:
            self.last_rx = lines[-1][:120]

    # -- estado -------------------------------------------------------------
    def status(self) -> dict:
        t = self.transport
        return {
            "connected": self.connected,
            "simulated": isinstance(t, SimulatedTransport),
            "port": (t.port if t is not None and t.port else self.port),
            "baudrate": self.baudrate,
            "protocol": self.protocol.name,
            "last_sent": {"x": self.last_sent[0], "y": self.last_sent[1]},
            "frames_sent": self.frames_sent,
            "reconnects": self.reconnects,
            "last_rx": self.last_rx,
            "error": self.last_error,
        }
