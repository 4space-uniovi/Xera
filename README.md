# 4SPACE Mini Rover

Control web para los mini rovers de los talleres de robótica de **4Space Uniovi**.
Un **Arduino UNO Q** (Debian ARM64) sirve una web con vídeo en directo y un joystick
virtual, y manda las órdenes por USB a un **ESP32-S3** que mueve los motores.

Sin Docker, sin ROS 2, sin frameworks frontend, sin base de datos:
Python + FastAPI en un `venv`, HTML/CSS/JS planos y servicios `systemd`.

## Estado del proyecto

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Estructura, configuración, backend y frontend con joystick simulado | ✅ hecha |
| 2 | Comunicación serie USB con el ESP32-S3 (autodetección, reconexión) | ✅ hecha (probada con simulador, falta hardware real) |
| 3 | Vídeo USB (MJPEG, una captura compartida) | ✅ hecha (probada con cámara simulada, falta webcam real) |
| 4 | Wi-Fi: hotspot AP ↔ cliente | pendiente |
| 5 | Servicios systemd y arranque automático | pendiente |
| 6 | Documentación de taller y pruebas finales | pendiente |

## Probarlo ya (modo demo, en cualquier ordenador o en el UNO Q)

```bash
git clone <url-del-repo> 4space-mini-rover && cd 4space-mini-rover
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
./scripts/dev.sh            # arranca en http://<ip>:8000 (modo demo)
```

> En Debian puede faltar el paquete del venv: `sudo apt install python3-venv python3-pip`.

Abre `http://localhost:8000` (o la IP del UNO Q) → **Pedir control** → arrastra el joystick.
En la pestaña **Estado** verás las tramas `X,Y` que recibiría el ESP32 (simulado).

Pruebas automáticas (no necesitan hardware):

```bash
.venv/bin/python -m pytest
```

## Probar con el hardware real

Ver [docs/first_hardware_test.md](docs/first_hardware_test.md) (ESP32-S3 + webcam por hub USB).

## Estructura

```
backend/        FastAPI: main.py, config.py, motion.py (control + watchdog)
  controllers/  serial_controller.py, camera_controller.py, wifi_controller.py
  api/          control.py (WebSocket + estado + ajustes), camera.py, network.py
frontend/       index.html, style.css, joystick.js, app.js  (sin compilar)
config/         rover.example.yaml  (copia a rover.yaml, ignorado por git)
scripts/ systemd/ tests/ docs/
```

Más detalle en [docs/architecture.md](docs/architecture.md) y
[docs/uart_protocol.md](docs/uart_protocol.md).

## Seguridad en una frase

Solo un cliente conduce a la vez; si se corta el WebSocket o pasan 300 ms sin órdenes,
el backend envía `0,0`. **El firmware del ESP32-S3 debe tener además su propio watchdog**
(el del backend no protege si se desconecta el USB o muere el proceso Linux).
