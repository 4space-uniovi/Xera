# Primera prueba con hardware (ESP32-S3 + webcam)

> ⚠️ **Seguridad:** levanta el rover para que las **ruedas no toquen el suelo** y ten a mano
> el interruptor/cable de los motores. El protocolo UART es `X,Y\n` (confirmado con el firmware actual).
> Esta prueba arranca con la velocidad máxima al **20 %** (`config/rover.yaml`).

## 1. Conectar
1. Apaga el UNO Q, conecta el hub USB-C con el ESP32-S3 y la webcam, y enciéndelo.
2. Se conectará a la Wi-Fi de siempre (todavía no hay modo AP: llega en la Fase 4).
   Conéctate por SSH: `ssh arduino@<ip>`.

## 2. Comprobar que Linux ve los dispositivos
```bash
lsusb                              # deben aparecer el ESP32-S3 y la webcam
ls /dev/ttyACM* /dev/ttyUSB*       # el ESP32
./scripts/test_camera.sh           # la webcam (ignora /dev/video0 y 1: son del chip)
```
Si algo falta: `dmesg | tail -30`.

## 3. Probar el ESP32 sin la web
```bash
cd ~/4space-mini-rover
.venv/bin/python scripts/test_serial.py --list
.venv/bin/python scripts/test_serial.py --listen 5        # ¿envía algo el ESP32?
.venv/bin/python scripts/test_serial.py --move --speed 20 # MUEVE LOS MOTORES (suave) y termina en 0,0
```

## 4. Arrancar la web
```bash
nohup ./scripts/run.sh > /tmp/rover.log 2>&1 &
tail -f /tmp/rover.log             # Ctrl-C para salir del log; el servidor sigue
```
Abre `http://<ip-del-uno-q>:8000` → **Pedir control** → mueve el joystick. En **Estado**
verás el puerto serie, las tramas enviadas y la webcam. Para parar el servidor: `pkill -f backend.main`.

## 5. Si algo falla
| Síntoma | Qué mirar |
|---------|-----------|
| ESP32 "Desconectado" | `ls /dev/ttyACM*`; `groups` debe incluir `dialout`; `tail /tmp/rover.log` |
| Se conecta pero no se mueve | Comprueba baudrate (115200 por defecto) y que el firmware tenga su watchdog; ver `docs/uart_protocol.md` |
| El ESP32 se reinicia al abrir el puerto | Ya se abre con DTR/RTS a 0; si persiste, revisa el firmware |
| Webcam "desconectada" | `./scripts/test_camera.sh`; ¿hub con alimentación suficiente? |
| "La cámara no entrega MJPEG" | La cámara solo da YUYV: prueba otra resolución o avísame (hace falta `ffmpeg`) |
| Muchas tramas basura en el ESP32 | `ModemManager` puede sondear los `ttyACM*`: se desactiva para ese USB en la Fase 5 |
