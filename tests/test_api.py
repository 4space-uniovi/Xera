import time

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.config import Settings, load_settings
from backend.main import create_app


@pytest.fixture
def cfg_path(tmp_path):
    return tmp_path / "rover.yaml"


@pytest.fixture
def client(cfg_path):
    app = create_app(Settings(demo=True), cfg_path)
    with TestClient(app) as c:
        c.app_state = app.state
        yield c


def recv_until(ws, pred, n=30):
    for _ in range(n):
        m = ws.receive_json()
        if pred(m):
            return m
    raise AssertionError("mensaje esperado no recibido")


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# --- REST -------------------------------------------------------------------
def test_status_works_without_camera_or_esp(client):
    d = client.get("/api/status").json()
    assert d["demo"] is True
    assert d["camera"]["available"] is False
    assert d["serial"]["connected"] is True and d["serial"]["simulated"] is True
    assert "csv" in d["protocols"]


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "4SPACE" in r.text


def test_config_update_persists_and_applies(client, cfg_path):
    r = client.put("/api/config", json={"motion": {"max_speed": 35}, "rover": {"name": "Rover-X"}})
    assert r.status_code == 200
    assert client.app_state.motion.max_speed == 35
    assert load_settings(cfg_path).rover.name == "Rover-X"


@pytest.mark.parametrize("patch", [
    {"motion": {"max_speed": 10}},
    {"motion": {"max_speed": 101}},
    {"serial": {"protocol": "nope"}},
    {"wifi": {"password": "secreto"}},   # nunca se guardan credenciales
    {"rover": {"name": ""}},
])
def test_config_rejects_invalid(client, cfg_path, patch):
    assert client.put("/api/config", json=patch).status_code == 422
    assert not cfg_path.exists()


def test_saved_yaml_has_no_password_field(client, cfg_path):
    client.put("/api/config", json={"rover": {"name": "A"}})
    assert "password" not in yaml.safe_load(cfg_path.read_text()).get("wifi", {})


# --- WebSocket --------------------------------------------------------------
def test_ws_move_reaches_esp32_and_stops_on_disconnect(client):
    esp = client.app_state.serial.transport
    client.put("/api/config", json={"motion": {"max_speed": 100}})
    with client.websocket_connect("/ws/control") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "request_control"})
        recv_until(ws, lambda m: m["type"] == "state" and m["is_owner"])
        ws.send_json({"type": "move", "x": 50, "y": -25})
        assert wait_for(lambda: esp.last == (50, -25))
    # al cerrar el socket el dueño desaparece -> (0,0)
    assert wait_for(lambda: esp.last == (0, 0))
    assert client.app_state.motion.owner is None


def test_ws_exclusive_control(client):
    with client.websocket_connect("/ws/control") as a, client.websocket_connect("/ws/control") as b:
        a.receive_json(); b.receive_json()
        a.send_json({"type": "request_control"})
        recv_until(a, lambda m: m["type"] == "state" and m["is_owner"])
        b.send_json({"type": "request_control"})
        assert recv_until(b, lambda m: m["type"] == "denied")["reason"] == "occupied"
        b.send_json({"type": "stop"})  # fuerza una difusión de estado nueva
        st = recv_until(b, lambda m: m["type"] == "state" and m["owner_present"])
        assert st["is_owner"] is False and st["clients"] == 2


def test_ws_watchdog_stops_rover(client):
    esp = client.app_state.serial.transport
    client.put("/api/config", json={"motion": {"max_speed": 100}})
    with client.websocket_connect("/ws/control") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_control"})
        ws.send_json({"type": "move", "x": 70, "y": 70})
        assert wait_for(lambda: esp.last == (70, 70))
        # dejamos de enviar: el watchdog (300 ms) debe parar el rover
        assert wait_for(lambda: esp.last == (0, 0), timeout=2.0)
        assert client.app_state.motion.watchdog_trips >= 1


def test_ws_bad_messages_do_not_crash(client):
    with client.websocket_connect("/ws/control") as ws:
        ws.receive_json()
        ws.send_text("esto no es json")
        assert recv_until(ws, lambda m: m["type"] == "error")
        ws.send_json({"type": "move", "x": "a", "y": None})  # sin control: se ignora
        ws.send_json({"type": "teleport"})
        assert recv_until(ws, lambda m: m["type"] == "error")
