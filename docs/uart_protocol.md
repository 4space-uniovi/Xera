# Protocolo UART (PROVISIONAL)

> ⚠️ El protocolo definitivo del firmware del ESP32-S3 aún no está fijado.
> El formato de abajo es un **ejemplo** para poder probar el sistema.

## Protocolo `csv` (el actual)

Una línea ASCII por orden, terminada en `\n`:

```
X,Y\n
```

- `X` = steering (giro), entero de -100 (izquierda) a 100 (derecha).
- `Y` = throttle (avance), entero de -100 (marcha atrás) a 100 (adelante).

Ejemplos: `50,-25\n`  ·  `0,0\n` (parar).

Parámetros del puerto: 115200 baudios, 8N1 (configurable en Ajustes / `config/rover.yaml`).

## Cómo cambiar el formato

Todo el formato vive en `backend/controllers/serial_controller.py`. Crea una clase y regístrala;
el resto del backend no cambia:

```python
@register_protocol
class MiProtocolo(UartProtocol):
    name = "mio"

    def encode(self, x: int, y: int) -> bytes:
        return f"M {x} {y}\r\n".encode("ascii")

    def decode(self, frame: bytes) -> tuple[int, int]:   # lo usa el simulador
        _, x, y = frame.decode().split()
        return int(x), int(y)
```

Luego elige `mio` en Ajustes → Protocolo (o `serial.protocol: mio` en el YAML).

## Watchdog del firmware (obligatorio)

El ESP32-S3 debe parar los motores si no recibe ninguna trama válida durante un tiempo corto
(recomendado 300–500 ms). El backend envía tramas a ~20 Hz mientras hay un cliente conduciendo,
y `0,0` al parar. Si se desconecta el USB o el proceso Linux muere, solo el watchdog del firmware
puede detener el rover.
