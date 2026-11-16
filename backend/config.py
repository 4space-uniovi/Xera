"""Configuración del rover (fichero YAML).

Los ajustes se validan con pydantic. NO existe ningún campo para la contraseña
Wi-Fi: las credenciales las guarda NetworkManager (/etc/NetworkManager/...),
nunca este fichero ni el repositorio.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "rover.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "rover.example.yaml"


class _Section(BaseModel):
    # extra="forbid": un campo desconocido (p. ej. "password") es un error.
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RoverSection(_Section):
    name: str = Field("4SPACE-ROVER-01", min_length=1, max_length=32)


class SerialSection(_Section):
    # Solo "auto" o un dispositivo USB-serie: el navegador no puede elegir rutas arbitrarias.
    port: str = Field("auto", pattern=r"^(auto|/dev/(ttyACM\d+|ttyUSB\d+|serial/by-(id|path)/[A-Za-z0-9_.:\-]+))$")
    baudrate: int = Field(115200, ge=1200, le=2_000_000)
    protocol: str = "csv"


class MotionSection(_Section):
    max_speed: int = Field(60, ge=20, le=100)       # % de velocidad máxima
    send_rate_hz: int = Field(20, ge=5, le=50)      # frecuencia del joystick
    watchdog_ms: int = Field(300, ge=100, le=2000)  # sin órdenes -> (0,0)
    control_timeout_s: float = Field(5.0, ge=1, le=60)  # el dueño inactivo pierde el control


class CameraSection(_Section):
    device: str = Field("auto", pattern=r"^(auto|/dev/video\d+)$")
    width: int = Field(640, ge=160, le=1920)
    height: int = Field(480, ge=120, le=1080)
    fps: int = Field(15, ge=1, le=60)


class WifiSection(_Section):
    ap_ssid: str = Field("4SPACE-ROVER-01", min_length=1, max_length=32)
    ap_ip: str = "192.168.4.1"
    client_profile: str = "4space-client"  # perfil NM autorizado (sin contraseña aquí)
    switch_timeout_s: int = Field(30, ge=5, le=300)


class Settings(_Section):
    demo: bool = False
    rover: RoverSection = RoverSection()
    serial: SerialSection = SerialSection()
    motion: MotionSection = MotionSection()
    camera: CameraSection = CameraSection()
    wifi: WifiSection = WifiSection()


def resolve_config_path(path: str | os.PathLike | None = None) -> Path:
    """Orden: argumento > $ROVER_CONFIG > config/rover.yaml."""
    if path:
        return Path(path)
    env = os.environ.get("ROVER_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_PATH


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    """Carga el YAML. Si no existe, devuelve los valores por defecto."""
    p = resolve_config_path(path)
    if not p.exists():
        return Settings()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)


def save_settings(settings: Settings, path: str | os.PathLike | None = None) -> Path:
    """Guarda el YAML de forma atómica (escribe a un temporal y renombra)."""
    p = resolve_config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(settings.model_dump(), sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".rover-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def merge_settings(current: Settings, patch: dict[str, Any]) -> Settings:
    """Aplica un cambio parcial (dict anidado) y devuelve unos Settings nuevos y validados."""
    data = current.model_dump()
    for section, values in patch.items():
        if isinstance(values, dict) and isinstance(data.get(section), dict):
            data[section].update(values)
        else:
            data[section] = values
    return Settings.model_validate(data)
