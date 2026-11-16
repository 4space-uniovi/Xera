"""Webcam USB (V4L2/UVC) -> MJPEG para el navegador.

Diseño (poca CPU y RAM):
- La cámara se detecta leyendo /sys/class/video4linux (sin abrirla). Solo cuentan
  las UVC (driver `uvcvideo`): /dev/video0 y /dev/video1 del UNO Q son los
  códecs del chip y se ignoran.
- UNA sola captura compartida: `v4l2-ctl` pide MJPG a la cámara y vuelca los JPEG
  tal cual por su salida estándar (sin recodificar). Se enciende con el primer
  espectador y se apaga con el último.
- Cada cliente recibe siempre el fotograma más reciente (un cliente lento se
  salta fotogramas, nunca acumula memoria).
- Conectar/desconectar la cámara en caliente: se reintenta cada segundo mientras
  haya espectadores.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

log = logging.getLogger(__name__)

SYSFS_V4L = Path("/sys/class/video4linux")
SOI = b"\xff\xd8"  # inicio de JPEG
NO_FRAMES_TIMEOUT_S = 5.0
RETRY_S = 1.0


def detect_cameras(sysfs: Path = SYSFS_V4L) -> list[dict]:
    """Webcams UVC presentes: [{"device": "/dev/video2", "name": "..."}]."""
    cams = []
    if not sysfs.exists():
        return cams

    def num(p: Path) -> int:
        m = re.search(r"(\d+)$", p.name)
        return int(m.group(1)) if m else 0

    for node in sorted(sysfs.glob("video*"), key=num):
        try:
            name = (node / "name").read_text().strip()
            index = int((node / "index").read_text().strip())
            driver = os.path.basename(os.path.realpath(node / "device" / "driver"))
        except (OSError, ValueError):
            continue
        # index 0 = nodo de captura; los siguientes suelen ser metadatos
        if driver == "uvcvideo" and index == 0:
            cams.append({"device": f"/dev/{node.name}", "name": name})
    return cams


class MjpegSplitter:
    """Trocea un flujo continuo de JPEG concatenados en fotogramas sueltos."""

    def __init__(self, max_buffer: int = 4_000_000):
        self.buf = bytearray()
        self.max_buffer = max_buffer

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        frames = []
        while True:
            start = self.buf.find(SOI)
            if start < 0:
                del self.buf[:-1]  # conserva un posible 0xFF final
                break
            nxt = self.buf.find(SOI, start + 2)
            if nxt < 0:
                del self.buf[:start]
                break
            frames.append(bytes(self.buf[start:nxt]))
            del self.buf[:nxt]
        if len(self.buf) > self.max_buffer:  # basura sin fin: no crecer sin límite
            self.buf.clear()
        return frames


async def spawn_v4l2(device: str, width: int, height: int, fps: int):
    """Lanza `v4l2-ctl` volcando MJPEG a stdout (sin recodificar)."""
    return await asyncio.create_subprocess_exec(
        "v4l2-ctl", "-d", device,
        f"--set-fmt-video=width={width},height={height},pixelformat=MJPG",
        f"--set-parm={fps}",
        "--stream-mmap=4", "--stream-to=-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )


class CameraController:
    def __init__(
        self,
        demo: bool = False,
        get_cfg: Callable[[], object] | None = None,
        detect: Callable[[], list[dict]] = detect_cameras,
        spawn: Callable[..., Awaitable] = spawn_v4l2,
    ):
        self.demo = demo
        self._get_cfg = get_cfg
        self._detect = detect
        self._spawn = spawn

        self.latest: bytes | None = None
        self.seq = 0
        self.clients = 0
        self.state = "idle"       # idle | starting | streaming | disconnected | error
        self.error: str | None = None
        self.fps_measured = 0.0
        self._task: asyncio.Task | None = None
        self._cond: asyncio.Condition | None = None
        self._stamps: list[float] = []

    # -- selección de cámara ------------------------------------------------
    def _cfg(self):
        if self._get_cfg:
            return self._get_cfg()
        from types import SimpleNamespace
        return SimpleNamespace(device="auto", width=640, height=480, fps=15)

    def select(self) -> dict | None:
        """La cámara configurada, solo si está realmente detectada."""
        cams = self._detect()
        want = self._cfg().device
        if want == "auto":
            return cams[0] if cams else None
        return next((c for c in cams if c["device"] == want), None)

    # -- estado -------------------------------------------------------------
    def status(self) -> dict:
        cams = self._detect()
        sel = self.select()
        if self.state == "streaming":
            state = "streaming"
        elif not cams:
            state = "disconnected"
        elif sel is None:
            state = "error"
        else:
            state = self.state if self.state in ("starting", "error") else "idle"
        return {
            "available": sel is not None,
            "state": state,
            "devices": cams,
            "selected": sel["device"] if sel else None,
            "name": sel["name"] if sel else None,
            "clients": self.clients,
            "fps_measured": round(self.fps_measured, 1),
            "detail": self._detail(state, cams, sel),
        }

    def _detail(self, state, cams, sel) -> str:
        if self.error and state in ("error", "starting"):
            return self.error
        if not cams:
            return "Webcam desconectada. Conéctala al hub USB."
        if sel is None:
            return f"La cámara configurada ({self._cfg().device}) no está conectada."
        return {"streaming": "Emitiendo", "idle": "Lista"}.get(state, state)

    # -- captura compartida -------------------------------------------------
    def _condition(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    async def _publish(self, frame: bytes) -> None:
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t < 2.0] + [now]
        self.fps_measured = len(self._stamps) / 2.0 if len(self._stamps) > 1 else 0.0
        async with self._condition():
            self.latest = frame
            self.seq += 1
            self._condition().notify_all()

    async def _capture_loop(self) -> None:
        """Mientras haya espectadores: detecta, captura y reintenta."""
        while self.clients > 0:
            sel = self.select()
            if sel is None:
                self.state, self.error = "disconnected", None
                await asyncio.sleep(RETRY_S)
                continue
            cfg = self._cfg()
            self.state, self.error = "starting", None
            proc = None
            drain = None
            try:
                proc = await self._spawn(sel["device"], cfg.width, cfg.height, cfg.fps)
                # v4l2-ctl escribe un "<" por fotograma en stderr: si nadie lo lee, se llena el
                # pipe y la captura se congela. Lo vaciamos y guardamos el último texto útil.
                drain = asyncio.create_task(self._drain_stderr(proc))
                splitter = MjpegSplitter()
                got_frame = False
                while True:
                    timeout = NO_FRAMES_TIMEOUT_S
                    try:
                        chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout)
                    except asyncio.TimeoutError:
                        self.error = ("La cámara no entrega fotogramas MJPEG. "
                                      "Prueba otra resolución o comprueba que soporta MJPG.")
                        break
                    if not chunk:
                        if not got_frame:
                            self.error = ("v4l2-ctl terminó sin imagen: " + self._stderr_tail
                                          if self._stderr_tail else
                                          "v4l2-ctl terminó sin imagen (¿cámara ocupada o sin MJPG?).")
                        break
                    for frame in splitter.feed(chunk):
                        got_frame = True
                        self.state, self.error = "streaming", None
                        await self._publish(frame)
            except FileNotFoundError:
                self.state, self.error = "error", "Falta v4l2-ctl: sudo apt install v4l-utils"
                await asyncio.sleep(RETRY_S * 5)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.error = f"error de captura: {exc}"
                log.exception("captura de cámara")
            finally:
                if drain is not None:
                    drain.cancel()
                if proc is not None:
                    await self._kill(proc)
            if self.clients > 0:
                self.state = "disconnected" if not self._detect() else "error"
                await self._wake()
                await asyncio.sleep(RETRY_S)
        self.state = "idle"

    _stderr_tail = ""

    async def _drain_stderr(self, proc) -> None:
        self._stderr_tail = ""
        stream = getattr(proc, "stderr", None)
        if stream is None:
            return
        try:
            while True:
                data = await stream.read(4096)
                if not data:
                    return
                text = data.decode("utf-8", "replace").replace("<", "").strip()
                if text:
                    self._stderr_tail = text.splitlines()[-1][:160]
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    async def _kill(proc) -> None:
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            proc.kill()

    async def _wake(self) -> None:
        async with self._condition():
            self._condition().notify_all()

    # -- clientes -----------------------------------------------------------
    def _add_client(self) -> None:
        self.clients += 1
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._capture_loop())

    async def _remove_client(self) -> None:
        self.clients -= 1
        if self.clients <= 0:
            self.clients = 0
            task, self._task = self._task, None
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self.state, self.latest, self.fps_measured = "idle", None, 0.0

    async def frames(self) -> AsyncIterator[bytes]:
        """Fotogramas JPEG para UN cliente. Termina si la cámara se pierde."""
        self._add_client()
        last = self.seq
        try:
            idle_since = time.monotonic()
            while True:
                async with self._condition():
                    try:
                        await asyncio.wait_for(self._condition().wait_for(lambda: self.seq != last), 1.0)
                    except asyncio.TimeoutError:
                        pass
                if self.seq != last and self.latest is not None:
                    last = self.seq
                    idle_since = time.monotonic()
                    yield self.latest
                elif self.state in ("disconnected", "error") and time.monotonic() - idle_since > 3.0:
                    return  # el navegador reintentará al ver la cámara de nuevo
        finally:
            await self._remove_client()

    async def restart(self) -> None:
        """Aplica nuevos ajustes de resolución/FPS/dispositivo al vuelo."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            if self.clients > 0:
                self._task = asyncio.create_task(self._capture_loop())

    async def shutdown(self) -> None:
        self.clients = 0
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
