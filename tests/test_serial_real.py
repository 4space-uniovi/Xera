"""Puerto serie real (pyserial) probado sin hardware: un pseudo-terminal hace de ESP32."""
import os
import pty
import select

import pytest

from backend.controllers.serial_controller import CsvProtocol, PySerialTransport, SerialController, SimulatedTransport


@pytest.fixture
def fake_esp():
    master, slave = pty.openpty()
    yield master, os.ttyname(slave)
    os.close(master)
    os.close(slave)


def read_master(fd, timeout=1.0):
    r, _, _ = select.select([fd], [], [], timeout)
    return os.read(fd, 256) if r else b""


def test_pyserial_transport_writes_frames(fake_esp):
    master, path = fake_esp
    t = PySerialTransport(path, 115200)
    t.open()
    try:
        assert t.is_open
        t.write(b"50,-25\n")
        assert read_master(master) == b"50,-25\n"
    finally:
        t.close()
    assert not t.is_open


def test_pyserial_read_available(fake_esp):
    import time

    master, path = fake_esp
    t = PySerialTransport(path)
    t.open()
    try:
        os.write(master, b"hola esp\n")
        got = b""
        for _ in range(20):
            got += t.read_available()
            if b"hola" in got:
                break
            time.sleep(0.05)
        assert b"hola esp" in got
    finally:
        t.close()


def test_open_missing_port_raises_oserror():
    t = PySerialTransport("/dev/ttyACM99")
    with pytest.raises(OSError):
        t.open()


def test_write_on_closed_transport_raises():
    with pytest.raises(OSError):
        PySerialTransport("/dev/ttyACM99").write(b"0,0\n")


# --- controlador: autodetección y reconexión ------------------------------
class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(ports, clock=None, port="auto"):
    made = []

    def factory(p, baud):
        tr = SimulatedTransport(CsvProtocol(), port=p)
        tr.baudrate = baud
        made.append(tr)
        return tr

    ctrl = SerialController(CsvProtocol(), transport_factory=factory, port=port,
                            ports_provider=lambda: list(ports), clock=clock or Clock())
    return ctrl, made


def test_auto_picks_first_usb_serial():
    ctrl, made = make([{"device": "/dev/ttyACM0"}, {"device": "/dev/ttyUSB0"}])
    assert ctrl.connect() is True
    assert made[0].port == "/dev/ttyACM0"
    assert ctrl.send(10, 20) is True


def test_no_esp32_connected_is_not_a_crash():
    ctrl, _ = make([])
    assert ctrl.connect() is False
    assert ctrl.send(10, 10) is False       # no revienta; se informa
    assert "USB" in ctrl.status()["error"]
    assert ctrl.status()["connected"] is False


def test_hotplug_esp32_connected_later():
    clock, ports = Clock(), []
    ctrl, made = make(ports, clock)
    ctrl.connect()
    assert ctrl.ensure_connected() is False
    ports.append({"device": "/dev/ttyACM0"})
    assert ctrl.ensure_connected() is False   # aún dentro del intervalo de reintento
    clock.t += 1.5
    assert ctrl.ensure_connected() is True
    assert ctrl.send(5, 5) is True


def test_usb_unplug_and_reconnect():
    clock, ports = Clock(), [{"device": "/dev/ttyACM0"}]
    ctrl, made = make(ports, clock)
    ctrl.connect()
    made[0].fail_next_writes = 1              # el cable se desconecta
    assert ctrl.send(30, 30) is False
    assert ctrl.status()["connected"] is False
    ports.clear()                             # el puerto desaparece
    clock.t += 2
    assert ctrl.ensure_connected() is False
    ports.append({"device": "/dev/ttyACM1"})  # vuelve con otro número
    clock.t += 2
    assert ctrl.ensure_connected() is True
    assert ctrl.status()["port"] == "/dev/ttyACM1"
    assert ctrl.status()["reconnects"] == 1
    assert ctrl.send(30, 30) is True


def test_reconfigure_port_reopens():
    clock = Clock()
    ctrl, made = make([{"device": "/dev/ttyACM0"}], clock)
    ctrl.connect()
    ctrl.reconfigure("/dev/ttyACM3", 9600, "csv")
    assert not ctrl.connected
    assert ctrl.ensure_connected() is True
    assert made[-1].port == "/dev/ttyACM3" and made[-1].baudrate == 9600
