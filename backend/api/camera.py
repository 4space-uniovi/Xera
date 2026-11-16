"""Endpoints de cámara. FASE 3 añadirá /api/camera/stream (MJPEG)."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/camera")


@router.get("/status")
def camera_status(request: Request) -> dict:
    return request.app.state.camera.status()
