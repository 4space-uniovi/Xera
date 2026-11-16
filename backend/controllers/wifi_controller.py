"""Gestión Wi-Fi (NetworkManager). FASE 4: todavía no implementado.

En la Fase 1 NO se toca NetworkManager: solo se informa de la IP local.
"""
from __future__ import annotations

import socket


def get_ip_address() -> str:
    """IP local usada para salir de la máquina.

    `connect` sobre un socket UDP no envía ningún paquete: solo consulta la
    tabla de rutas. Funciona sin Internet; si no hay ruta, devuelve 127.0.0.1.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class WifiController:
    def __init__(self, demo: bool = False):
        self.demo = demo

    def status(self) -> dict:
        return {
            "mode": "unknown",
            "state": "not_implemented",
            "ssid": None,
            "ip": get_ip_address(),
            "detail": "La gestión AP/cliente se implementa en la Fase 4.",
        }
