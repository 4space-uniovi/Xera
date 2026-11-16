# AGENTS.md — guía para agentes de código y colaboradores

Proyecto: **4SPACE Mini Rover** (Arduino UNO Q + ESP32-S3). Lee README.md y docs/architecture.md primero.

## Reglas del proyecto
- Python 3 + FastAPI + WebSockets. Frontend en HTML/CSS/JS **sin paso de compilación**.
- NO usar: Docker, ROS 2, React/Vue/etc., bases de datos, C++ (salvo necesidad estricta).
- Dependencias Python solo en `.venv`. Poco consumo de RAM/CPU (placa de 2–4 GB).
- Las pruebas deben pasar **sin hardware** (ESP32 simulado, mocks de NetworkManager, sin webcam).
- Seguridad: el backend no corre como root; el navegador nunca ejecuta comandos arbitrarios;
  solo perfiles Wi-Fi autorizados; **ninguna credencial Wi-Fi en el repo ni en el YAML**.
- No cambiar la red ni NetworkManager del equipo de desarrollo (conexión por SSH) hasta la Fase 4
  y solo con confirmación explícita.

## Comandos
```bash
./scripts/dev.sh                 # servidor en modo demo
.venv/bin/python -m pytest       # pruebas
```

## Dónde tocar qué
- Cambiar el formato UART → `backend/controllers/serial_controller.py` (clase `UartProtocol`).
- Reglas de control/watchdog → `backend/motion.py` (no depende de HTTP; reloj inyectable para tests).
- Mensajes del WebSocket → `backend/api/control.py` (docstring con el protocolo) y `frontend/app.js`.

## Flujo Git
`main` siempre funcional. Trabajo en ramas `feature/<tema>` (joystick, uart, camera, wifi, ui).
Un commit por fase como mínimo; mensajes descriptivos.
