# Arquitectura

```
Navegador (móvil/tablet)
   │  HTTP  /            → frontend estático (index.html, app.js, joystick.js)
   │  HTTP  /api/*       → estado y ajustes (JSON)
   │  WS    /ws/control  → joystick (20 Hz) y estado en vivo
   ▼
FastAPI (backend/main.py)  ── un solo proceso, usuario sin privilegios
   ├─ api/control.py ──► MotionManager (backend/motion.py)
   │                        · un único dueño del control
   │                        · límite de velocidad 20–100 %
   │                        · watchdog 300 ms → (0,0)
   │                        ▼
   ├─ controllers/serial_controller.py ──► UART/USB ──► ESP32-S3 ──► motores
   ├─ controllers/camera_controller.py  (Fase 3) ──► /dev/video*
   └─ controllers/wifi_controller.py    (Fase 4) ──► servicio auxiliar ──► NetworkManager
```

## Flujo de una orden
1. El joystick (`joystick.js`) calcula X,Y ∈ [-100,100] (círculo, diagonales permitidas).
2. `app.js` envía `{"type":"move","x":..,"y":..}` cada 1/20 s **mientras tiene el control**
   (también (0,0): es el latido que alimenta el watchdog).
3. `MotionManager.move` comprueba que el cliente es el dueño, recorta a ±100, aplica la
   velocidad máxima y llama a `SerialController.send`.
4. `SerialController` valida de nuevo (estricto), codifica con el protocolo UART activo y escribe.

## Garantías de seguridad (Fase 1)
| Situación | Resultado |
|-----------|-----------|
| El dueño suelta el joystick | el cliente envía (0,0) al instante |
| Botón STOP (cualquier cliente) | (0,0) inmediato |
| Se cierra el WebSocket del dueño | el backend envía (0,0) y libera el control |
| 300 ms sin órdenes válidas | watchdog: (0,0) |
| El dueño no da señales 5 s | pierde el control |
| Orden inválida (NaN, texto…) | se ignora y **no** alimenta el watchdog |

> **Importante:** el watchdog del backend no protege frente a un USB desconectado o un
> fallo del proceso Linux. El firmware del ESP32-S3 **debe** implementar su propio watchdog
> (p. ej. parar motores si no llega ninguna trama en 300–500 ms).

## Decisiones
- Sin base de datos: ajustes en `config/rover.yaml` (escritura atómica, sin credenciales).
- `MotionManager` no conoce HTTP ni WebSockets y recibe el reloj por parámetro → pruebas rápidas y deterministas.
- Un único proceso y un solo hilo de eventos: poca RAM en el UNO Q.
