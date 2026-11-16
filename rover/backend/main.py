"""Punto de entrada.

  python -m backend.main --demo            # desarrollo en cualquier ordenador
  uvicorn backend.main:create_app --factory --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import camera, control, network
from .config import REPO_ROOT, Settings, load_settings, resolve_config_path
from .controllers.camera_controller import CameraController
from .controllers.led_controller import LedController
from .controllers.serial_controller import PySerialTransport, SerialController, SimulatedTransport, get_protocol
from .controllers.wifi_controller import WifiController
from .motion import MotionManager

log = logging.getLogger("rover")
FRONTEND_DIR = REPO_ROOT / "frontend"
WATCHDOG_PERIOD_S = 0.05


class NoCacheStatic(StaticFiles):
    """Los estudiantes editan HTML/JS/CSS: que el navegador siempre revalide."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app(settings: Settings | None = None, config_path: str | Path | None = None) -> FastAPI:
    path = resolve_config_path(config_path)
    settings = settings or load_settings(path)

    proto = get_protocol(settings.serial.protocol)
    if settings.demo:  # sin hardware: ESP32 simulado en memoria
        serial = SerialController(proto, transport=SimulatedTransport(proto))
    else:
        serial = SerialController(
            proto,
            transport_factory=lambda port, baud: PySerialTransport(port, baud),
            port=settings.serial.port,
            baudrate=settings.serial.baudrate,
        )
    serial.connect()

    motion = MotionManager(
        serial,
        max_speed=settings.motion.max_speed,
        watchdog_s=settings.motion.watchdog_ms / 1000,
        control_timeout_s=settings.motion.control_timeout_s,
    )
    leds = LedController(enabled=settings.leds.enabled and not settings.demo)  # en demo/tests no se tocan los LEDs reales
    hub = control.Hub(motion)
    motion.on_change = hub.schedule_broadcast

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def watchdog_loop():
            while True:
                motion.check()
                await asyncio.sleep(WATCHDOG_PERIOD_S)

        async def serial_supervisor():
            """Reabre el puerto si el USB se desconectó y recoge mensajes del ESP32."""
            while True:
                await asyncio.to_thread(serial.ensure_connected)
                await asyncio.to_thread(serial.poll_rx)
                await asyncio.sleep(1.0)

        async def led_loop():
            """Verde fijo = listo (ESP32 conectado; la webcam es opcional).
            Rojo parpadeando = el ESP32 falla o no está."""
            tick = 0
            while True:
                if serial.connected:
                    leds.set_color("green")
                else:
                    leds.set_color("red" if tick % 2 == 0 else "off")
                tick += 1
                await asyncio.sleep(0.5)

        task = asyncio.create_task(watchdog_loop())
        sup = asyncio.create_task(serial_supervisor())
        led_task = asyncio.create_task(led_loop())
        yield
        task.cancel()
        sup.cancel()
        led_task.cancel()
        await app.state.camera.shutdown()
        leds.restore()
        motion.emergency_stop()
        serial.close()

    app = FastAPI(title="4SPACE Mini Rover", lifespan=lifespan)
    app.state.settings = settings
    app.state.config_path = path
    app.state.serial = serial
    app.state.motion = motion
    app.state.hub = hub
    app.state.leds = leds
    app.state.camera = CameraController(demo=settings.demo, get_cfg=lambda: app.state.settings.camera)
    app.state.wifi = WifiController(demo=settings.demo)
    app.state.started = time.monotonic()

    app.include_router(control.router)
    app.include_router(camera.router)
    app.include_router(network.router)
    app.mount("/", NoCacheStatic(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description="4SPACE Mini Rover")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", help="ruta del YAML (por defecto config/rover.yaml)")
    ap.add_argument("--demo", action="store_true", help="sin ESP32 ni webcam")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings(args.config)
    if args.demo:
        settings.demo = True
    uvicorn.run(create_app(settings, args.config), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
