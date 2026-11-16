"""Cámara USB (V4L2). FASE 3: todavía no implementado.

En la Fase 1 solo existe el esqueleto para que la API y la interfaz ya
muestren el estado "webcam desconectada".
"""
from __future__ import annotations


class CameraController:
    def __init__(self, demo: bool = False):
        self.demo = demo

    def status(self) -> dict:
        return {
            "available": False,
            "state": "not_implemented",
            "detail": "El vídeo se implementa en la Fase 3.",
            "devices": [],
        }
