import pytest

from backend.controllers.serial_controller import (
    CsvProtocol,
    SerialController,
    SimulatedTransport,
    get_protocol,
    validate_xy,
)


@pytest.mark.parametrize("x,y,expected", [(0, 0, (0, 0)), (100, -100, (100, -100)), (49.6, -25.2, (50, -25))])
def test_validate_ok(x, y, expected):
    assert validate_xy(x, y) == expected


@pytest.mark.parametrize("bad", [101, -101, float("nan"), float("inf"), "50", None, True])
def test_validate_rejects(bad):
    with pytest.raises(ValueError):
        validate_xy(bad, 0)
    with pytest.raises(ValueError):
        validate_xy(0, bad)


def test_csv_protocol_format():
    p = CsvProtocol()
    assert p.encode(50, -25) == b"50,-25\n"
    assert p.decode(b"50,-25\n") == (50, -25)


@pytest.mark.parametrize("frame", [b"", b"1\n", b"a,b\n", b"1,2,3\n", b"500,0\n", b"\xff\n"])
def test_csv_decode_invalid(frame):
    with pytest.raises(ValueError):
        CsvProtocol().decode(frame)


def test_unknown_protocol():
    with pytest.raises(ValueError):
        get_protocol("nope")


def test_send_reaches_simulated_esp32(esp):
    assert esp.send(50, -25) is True
    assert esp.transport.frames[-1] == b"50,-25\n"
    assert esp.transport.last == (50, -25)
    assert esp.status()["last_sent"] == {"x": 50, "y": -25}


def test_invalid_command_never_hits_the_wire(esp):
    with pytest.raises(ValueError):
        esp.send(500, 0)
    assert len(esp.transport.frames) == 0


def test_write_failure_is_reported_not_raised(esp):
    esp.transport.fail_next_writes = 1
    assert esp.send(10, 10) is False
    assert esp.status()["connected"] is False
    assert esp.status()["error"]


def test_reconnect_after_failure(esp):
    esp.transport.fail_next_writes = 1
    esp.send(10, 10)
    assert esp.send(10, 10) is False   # sigue cerrado
    assert esp.connect() is True       # reabrir
    assert esp.send(10, 10) is True


def test_switch_protocol_without_touching_callers(esp):
    from backend.controllers import serial_controller as sc

    @sc.register_protocol
    class Semicolon(sc.UartProtocol):
        name = "semicolon"

        def encode(self, x, y):
            return f"{x};{y}\n".encode()

        def decode(self, frame):
            a, b = frame.decode().strip().split(";")
            return int(a), int(b)

    try:
        esp.set_protocol("semicolon")
        esp.send(1, 2)
        assert esp.transport.frames[-1] == b"1;2\n"
    finally:
        sc.PROTOCOLS.pop("semicolon")
