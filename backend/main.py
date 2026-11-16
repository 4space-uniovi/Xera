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
from .controllers.serial_controller import SerialController, get_protocol, SimulatedTransport
from .controllers.wifi_controller import WifiController
from .motion import MotionManager

log = logging.getLogger("rover")
FRONTEND_DIR = REPO_ROOT / "frontend"
WATCHDOG_PERIOD_S = 0.05


def create_app(settings: Settings | None = None, config_path: str | Path | None = None) -> FastAPI:
    path = resolve_config_path(config_path)
    settings = settings or load_settings(path)

    # FASE 1: el ESP32 es siempre el simulador. La Fase 2 elegirá el puerto real aquí.
    proto = get_protocol(settings.serial.protocol)
    serial = SerialController(proto, transport=SimulatedTransport(proto))
    serial.connect()

    motion = MotionManager(
        serial,
        max_speed=settings.motion.max_speed,
        watchdog_s=settings.motion.watchdog_ms / 1000,
        control_timeout_s=settings.motion.control_timeout_s,
    )
    hub = control.Hub(motion)
    motion.on_change = hub.schedule_broadcast

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def watchdog_loop():
            while True:
                motion.check()
                await asyncio.sleep(WATCHDOG_PERIOD_S)

        task = asyncio.create_task(watchdog_loop())
        yield
        task.cancel()
        motion.emergency_stop()
        serial.close()

    app = FastAPI(title="4SPACE Mini Rover", lifespan=lifespan)
    app.state.settings = settings
    app.state.config_path = path
    app.state.serial = serial
    app.state.motion = motion
    app.state.hub = hub
    app.state.camera = CameraController(demo=settings.demo)
    app.state.wifi = WifiController(demo=settings.demo)
    app.state.started = time.monotonic()

    app.include_router(control.router)
    app.include_router(camera.router)
    app.include_router(network.router)
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
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
