"""WebSocket de control + estado + configuración.

Protocolo del WebSocket (JSON, un objeto por mensaje):

  cliente -> servidor
    {"type": "request_control"}          pedir el control de movimiento
    {"type": "release_control"}          liberarlo (envía 0,0)
    {"type": "move", "x": -100..100, "y": -100..100}   solo si eres el dueño
    {"type": "stop"}                     (0,0) inmediato; lo puede enviar cualquiera

  servidor -> cliente
    {"type": "hello", "id": "...", "send_rate_hz": 20}
    {"type": "state", "clients": n, "is_owner": bool, "owner_present": bool,
     "max_speed": 60, "output": {"x": 0, "y": 0}, "watchdog_trips": 0}
    {"type": "denied", "reason": "occupied"}
    {"type": "error", "detail": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Body, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..config import merge_settings, save_settings
from ..controllers.serial_controller import PROTOCOLS

log = logging.getLogger(__name__)
router = APIRouter()


class Hub:
    """Conexiones WebSocket abiertas y difusión del estado."""

    def __init__(self, motion):
        self.motion = motion
        self.conns: dict[str, WebSocket] = {}
        self._tasks: set[asyncio.Task] = set()

    async def broadcast(self) -> None:
        for cid, ws in list(self.conns.items()):
            try:
                await ws.send_json({"type": "state", **self.motion.snapshot(cid)})
            except Exception:  # cliente caído: su handler limpiará
                pass

    def schedule_broadcast(self) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self.broadcast())
        except RuntimeError:  # sin bucle (tests síncronos)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


@router.websocket("/ws/control")
async def ws_control(ws: WebSocket) -> None:
    await ws.accept()
    st = ws.app.state
    motion, hub = st.motion, st.hub
    cid = uuid.uuid4().hex[:8]
    hub.conns[cid] = ws
    await ws.send_json({"type": "hello", "id": cid, "send_rate_hz": st.settings.motion.send_rate_hz})
    motion.connect(cid)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                kind = msg["type"]
            except (ValueError, KeyError, TypeError):
                await ws.send_json({"type": "error", "detail": "mensaje JSON inválido"})
                continue

            if kind == "move":
                motion.move(cid, msg.get("x"), msg.get("y"))
            elif kind == "stop":
                motion.stop(cid)
            elif kind == "request_control":
                if not motion.request_control(cid):
                    await ws.send_json({"type": "denied", "reason": "occupied"})
            elif kind == "release_control":
                motion.release_control(cid)
            else:
                await ws.send_json({"type": "error", "detail": f"tipo desconocido: {kind!r}"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.conns.pop(cid, None)
        motion.disconnect(cid)  # si era el dueño: (0,0)


@router.get("/api/status")
def status(request: Request) -> dict:
    st = request.app.state
    return {
        "rover": st.settings.rover.name,
        "demo": st.settings.demo,
        "uptime_s": round(time.monotonic() - st.started, 1),
        "serial": st.serial.status(),
        "camera": st.camera.status(),
        "wifi": st.wifi.status(),
        "motion": st.motion.snapshot(),
        "protocols": sorted(PROTOCOLS),
    }


@router.get("/api/config")
def get_config(request: Request) -> dict:
    return request.app.state.settings.model_dump()


@router.put("/api/config")
def put_config(request: Request, patch: dict = Body(...)) -> dict:
    """Cambio parcial, p. ej. {"motion": {"max_speed": 40}}. Valida todo antes de aplicar."""
    st = request.app.state
    try:
        new = merge_settings(st.settings, patch)
    except ValidationError as exc:
        detail = [{"field": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]
        raise HTTPException(status_code=422, detail=detail) from None
    if new.serial.protocol not in PROTOCOLS:
        raise HTTPException(422, detail=[{"field": "serial.protocol", "msg": "protocolo desconocido"}])

    st.settings = new
    st.motion.set_max_speed(new.motion.max_speed)
    st.motion.watchdog_s = new.motion.watchdog_ms / 1000
    st.motion.control_timeout_s = new.motion.control_timeout_s
    st.serial.set_protocol(new.serial.protocol)
    save_settings(new, st.config_path)
    return new.model_dump()
