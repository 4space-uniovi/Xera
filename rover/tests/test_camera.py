import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.controllers import camera_controller as cc
from backend.controllers.camera_controller import CameraController, MjpegSplitter, detect_cameras
from backend.main import create_app

CAM = {"device": "/dev/video2", "name": "USB Camera"}


def jpeg(n: int) -> bytes:
    return b"\xff\xd8" + bytes([n]) * 20 + b"\xff\xd9"


# --- detección --------------------------------------------------------------
def make_node(root, name, label, driver, index):
    node = root / name
    (node / "device").mkdir(parents=True)
    (node / "name").write_text(label + "\n")
    (node / "index").write_text(f"{index}\n")
    drv = root.parent / "drivers" / driver
    drv.mkdir(parents=True, exist_ok=True)
    os.symlink(drv, node / "device" / "driver")


def test_detect_only_uvc_capture_nodes(tmp_path):
    root = tmp_path / "video4linux"
    make_node(root, "video0", "qcom-venus-encoder", "qcom-venus", 0)   # códec del chip
    make_node(root, "video2", "USB Camera", "uvcvideo", 0)
    make_node(root, "video3", "USB Camera", "uvcvideo", 1)             # metadatos
    assert detect_cameras(root) == [{"device": "/dev/video2", "name": "USB Camera"}]


def test_detect_without_sysfs(tmp_path):
    assert detect_cameras(tmp_path / "nope") == []


# --- troceado MJPEG ---------------------------------------------------------
def test_splitter_across_chunk_boundaries():
    stream = jpeg(1) + jpeg(2) + jpeg(3)
    sp, out = MjpegSplitter(), []
    for i in range(0, len(stream), 7):          # trozos arbitrarios
        out += sp.feed(stream[i:i + 7])
    assert out == [jpeg(1), jpeg(2)]            # el último se entrega al llegar el siguiente SOI
    assert sp.feed(jpeg(4)) == [jpeg(3)]


def test_splitter_garbage_is_bounded():
    sp = MjpegSplitter(max_buffer=1000)
    sp.feed(b"\x00" * 5000)
    assert len(sp.buf) <= 1000


# --- fakes ------------------------------------------------------------------
class FakeStdout:
    def __init__(self, proc):
        self.p = proc

    async def read(self, n):
        await asyncio.sleep(0.005)
        if self.p.dead:
            return b""
        self.p.i += 1
        return jpeg(self.p.i % 250)


class FakeProc:
    def __init__(self):
        self.i, self.dead, self.terminated = 0, False, False
        self.stdout = FakeStdout(self)

    def terminate(self):
        self.terminated = True
        self.dead = True

    def kill(self):
        self.dead = True

    async def wait(self):
        return 0


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(cc, "RETRY_S", 0.05)


def run(coro):
    return asyncio.run(coro)


# --- sin webcam -------------------------------------------------------------
def test_status_without_camera():
    cam = CameraController(detect=lambda: [])
    st = cam.status()
    assert st["available"] is False and st["state"] == "disconnected"
    assert "desconectada" in st["detail"].lower()
    assert cam.select() is None


def test_stream_endpoint_503_without_camera():
    app = create_app(Settings(demo=True), "/tmp/_unused_rover.yaml")
    app.state.camera = CameraController(detect=lambda: [])
    with TestClient(app) as c:
        assert c.get("/api/camera/stream").status_code == 503
        assert c.get("/api/camera/status").json()["available"] is False
        assert c.get("/api/status").status_code == 200   # el resto funciona sin webcam


# --- captura compartida -----------------------------------------------------
def test_single_capture_for_many_clients_and_stops_after_last():
    spawned = []

    async def spawn(device, w, h, fps):
        p = FakeProc()
        spawned.append((device, w, h, fps, p))
        return p

    async def main():
        cam = CameraController(detect=lambda: [CAM], spawn=spawn)

        async def client(n):
            got = []
            async for f in cam.frames():
                got.append(f)
                if len(got) == n:
                    return got

        results = await asyncio.wait_for(asyncio.gather(client(5), client(5), client(8)), 5)
        await asyncio.sleep(0.1)
        return cam, results

    cam, results = run(main())
    assert len(spawned) == 1                       # una sola captura para 3 clientes
    assert spawned[0][:4] == ("/dev/video2", 640, 480, 15)
    assert all(len(r) in (5, 8) for r in results)
    assert all(f.startswith(b"\xff\xd8") for r in results for f in r)
    assert spawned[0][4].terminated                # al irse el último cliente se apaga
    assert cam.clients == 0 and cam.state == "idle"


def test_camera_unplugged_while_streaming_ends_stream():
    procs, cams = [], [CAM]

    async def spawn(*a):
        p = FakeProc()
        procs.append(p)
        return p

    async def main():
        cam = CameraController(detect=lambda: list(cams), spawn=spawn)
        cam_frames = cam.frames()
        n = 0
        async for _ in cam_frames:
            n += 1
            if n == 3:
                cams.clear()          # se desenchufa
                procs[0].dead = True  # v4l2-ctl muere (EOF)
            if n > 3:
                pytest.fail("no debería seguir emitiendo")
        return cam

    cam = run(asyncio.wait_for(main(), 15))
    assert cam.clients == 0


def test_hotplug_camera_connected_after_client_started():
    cams = []

    async def spawn(*a):
        return FakeProc()

    async def main():
        cam = CameraController(detect=lambda: list(cams), spawn=spawn)

        async def plug():
            await asyncio.sleep(0.3)
            cams.append(CAM)

        asyncio.create_task(plug())
        async for f in cam.frames():
            return f

    assert run(asyncio.wait_for(main(), 5)).startswith(b"\xff\xd8")


def test_explicit_device_must_be_detected():
    from types import SimpleNamespace
    cam = CameraController(detect=lambda: [CAM], get_cfg=lambda: SimpleNamespace(device="/dev/video9", width=1, height=1, fps=1))
    assert cam.select() is None
    cam = CameraController(detect=lambda: [CAM], get_cfg=lambda: SimpleNamespace(device="/dev/video2", width=1, height=1, fps=1))
    assert cam.select() == CAM


def test_missing_v4l2_ctl_reports_error():
    async def spawn(*a):
        raise FileNotFoundError

    async def main():
        cam = CameraController(detect=lambda: [CAM], spawn=spawn)
        cam._add_client()
        await asyncio.sleep(0.2)
        st = cam.status()
        await cam.shutdown()
        return st

    st = run(main())
    assert st["state"] == "error" and "v4l2-ctl" in st["detail"]
