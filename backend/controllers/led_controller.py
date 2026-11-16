"""LEDs RGB del Arduino UNO Q (sysfs). Sin sudo: /sys/class/leds es del grupo `gpiod`.

El UNO Q tiene dos LEDs RGB; cada color es un "LED" de Linux distinto:
    LED 3: red:user   green:user  blue:user
    LED 4: red:panic  green:wlan  blue:bt
`green:wlan` y `blue:bt` traen un *trigger* (parpadean con la Wi-Fi / Bluetooth):
se pasa a `none` mientras controlamos el color y se restaura al apagar el servicio.
En un PC (o sin permisos) todo esto es un no-op silencioso.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

SYSFS_LEDS = Path("/sys/class/leds")
RGB_LEDS = [
    ("red:user", "green:user", "blue:user"),
    ("red:panic", "green:wlan", "blue:bt"),
]
COLORS = {
    "off": (0, 0, 0),
    "green": (0, 1, 0),
    "yellow": (1, 1, 0),
    "red": (1, 0, 0),
    "blue": (0, 0, 1),
}


class LedController:
    def __init__(self, root: Path = SYSFS_LEDS, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self.color: str | None = None
        self._saved_triggers: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return self.enabled and any((self.root / n).exists() for rgb in RGB_LEDS for n in rgb)

    @staticmethod
    def _active_trigger(text: str) -> str:
        for word in text.split():
            if word.startswith("[") and word.endswith("]"):
                return word[1:-1]
        return "none"

    def _write(self, path: Path, value: str) -> None:
        path.write_text(value)

    def set_color(self, color: str) -> bool:
        """Pone ambos LEDs RGB de ese color. Devuelve True si cambió algo."""
        if not self.enabled or color == self.color:
            return False
        rgb_values = COLORS[color]
        try:
            for rgb in RGB_LEDS:
                for name, value in zip(rgb, rgb_values):
                    led = self.root / name
                    if not led.exists():
                        continue
                    trig = led / "trigger"
                    if trig.exists():
                        if name not in self._saved_triggers:
                            self._saved_triggers[name] = self._active_trigger(trig.read_text())
                        self._write(trig, "none")
                    self._write(led / "brightness", str(value))
        except OSError as exc:  # sin permisos u otro fallo: no molestar más
            log.warning("LEDs desactivados (%s)", exc)
            self.enabled = False
            return False
        self.color = color
        return True

    def restore(self) -> None:
        """Apaga y devuelve cada LED a su trigger original (Wi-Fi, Bluetooth...)."""
        if not self.enabled or self.color is None:
            return
        try:
            self.set_color("off")
            for name, trigger in self._saved_triggers.items():
                if trigger != "none":
                    self._write(self.root / name / "trigger", trigger)
        except OSError:
            pass
        self.color = None
