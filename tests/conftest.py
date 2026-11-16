import pytest

from backend.controllers.serial_controller import CsvProtocol, SerialController, SimulatedTransport
from backend.motion import MotionManager


class FakeClock:
    """Reloj manual: los tests avanzan el tiempo sin dormir."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def esp():
    """Un ESP32 simulado ya conectado."""
    proto = CsvProtocol()
    ctrl = SerialController(proto, transport=SimulatedTransport(proto))
    ctrl.connect()
    return ctrl


@pytest.fixture
def motion(esp, clock):
    return MotionManager(esp, max_speed=100, watchdog_s=0.3, control_timeout_s=5.0, clock=clock)
