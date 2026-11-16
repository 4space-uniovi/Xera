"""Endpoints de red. FASE 4 añadirá el cambio AP <-> cliente."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/network")


@router.get("/status")
def network_status(request: Request) -> dict:
    return request.app.state.wifi.status()
