#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

// ======================================================
// USB SERIAL
// ======================================================

#define BAUDRATE 115200

// Format:
// throttle,steering\n
//
// Range:
// throttle: -100 ... +100
// steering: -100 ... +100
//
// Examples:
//
//  100,0     -> forward
// -100,0     -> backward
//   50,30    -> forward while turning
//   50,-30   -> forward while turning to the other side
//    0,100   -> rotate in place
//    0,-100  -> rotate in place to the other side
//    0,0     -> stop


// ======================================================
// LED
// ======================================================

// Onboard RGB LED of the ESP32-S3-DevKitC-1 v1.1 (GPIO 38).
// On v1.0 boards it is GPIO 48.
#define LED_PIN 38
#define NUM_LEDS 1

Adafruit_NeoPixel leds(
  NUM_LEDS,
  LED_PIN,
  NEO_GRB + NEO_KHZ800
);


// ======================================================
// MOTOR PINS
// ======================================================

// M1 = rear left
#define M1_HA 17
#define M1_HB 18
#define M1_LA 15
#define M1_LB 16

// M2 = rear right
#define M2_HA 40
#define M2_HB 37
#define M2_LA 36
#define M2_LB 35

// M3 = front left
#define M3_HA 7
#define M3_HB 6
#define M3_LA 5
#define M3_LB 4

// M4 = front right
#define M4_HA 1
#define M4_HB 2
#define M4_LA 42
#define M4_LB 41


// ======================================================
// MOTOR DIRECTION
// ======================================================
//
//  1 = normal direction
// -1 = reversed direction
//
// If a motor spins the wrong way,
// just change 1 to -1.
//

#define M1_DIR  1
#define M2_DIR -1
#define M3_DIR  1
#define M4_DIR  1


// ======================================================
// SPEED SETTINGS
// ======================================================

// Maximum PWM for forward / backward
int velocidadLinealMax = 50;

// Maximum PWM used for turning / rotation
int velocidadGiroMax = 120;


// ======================================================
// CONTROL
// ======================================================

int throttle = 0;
int steering = 0;

String mensaje = "";


// ======================================================
// DEBUG
// ======================================================

unsigned long lastPrint = 0;


// ======================================================
// BREATHING LED
// ======================================================

float brillo = 0;
float velocidadResp = 0.03;
bool subiendo = true;


// ======================================================
// TURNING LED (blinking)
// ======================================================

unsigned long lastLedMove = 0;
bool ledEncendido = false;
int ledInterval = 150;


// ======================================================
// PWM (LEDC)
// ======================================================
//
// The PlatformIO Arduino core (espressif32 v6) does not include
// analogWrite() for the ESP32-S3, so LEDC is used directly.
// One channel per PWM pin (the ESP32-S3 has 8).

const int PWM_PINS[] = {
  M1_HA, M1_HB, M2_HA, M2_HB,
  M3_HA, M3_HB, M4_HA, M4_HB
};
const int NUM_PWM = sizeof(PWM_PINS) / sizeof(PWM_PINS[0]);
const int PWM_FREQ = 1000;
const int PWM_BITS = 8;

void pwmInit() {

  for (int ch = 0; ch < NUM_PWM; ch++) {
    ledcSetup(ch, PWM_FREQ, PWM_BITS);
    ledcAttachPin(PWM_PINS[ch], ch);
  }
}

void pwmWrite(int pin, int duty) {

  for (int ch = 0; ch < NUM_PWM; ch++) {
    if (PWM_PINS[ch] == pin) {
      ledcWrite(ch, duty);
      return;
    }
  }
}


// ======================================================
// TURN ALL MOTORS OFF
// ======================================================

void apagarTodo() {

  pwmWrite(M1_HA, 0);
  pwmWrite(M1_HB, 0);
  digitalWrite(M1_LA, LOW);
  digitalWrite(M1_LB, LOW);

  pwmWrite(M2_HA, 0);
  pwmWrite(M2_HB, 0);
  digitalWrite(M2_LA, LOW);
  digitalWrite(M2_LB, LOW);

  pwmWrite(M3_HA, 0);
  pwmWrite(M3_HB, 0);
  digitalWrite(M3_LA, LOW);
  digitalWrite(M3_LB, LOW);

  pwmWrite(M4_HA, 0);
  pwmWrite(M4_HB, 0);
  digitalWrite(M4_LA, LOW);
  digitalWrite(M4_LB, LOW);
}


// ======================================================
// MOTOR FORWARD
// ======================================================

void motorAdelante(
  int HA,
  int HB,
  int LA,
  int LB,
  int velocidad
) {

  pwmWrite(HA, velocidad);
  pwmWrite(HB, 0);

  digitalWrite(LA, LOW);
  digitalWrite(LB, HIGH);
}


// ======================================================
// MOTOR BACKWARD
// ======================================================

void motorAtras(
  int HA,
  int HB,
  int LA,
  int LB,
  int velocidad
) {

  pwmWrite(HA, 0);
  pwmWrite(HB, velocidad);

  digitalWrite(LA, HIGH);
  digitalWrite(LB, LOW);
}


// ======================================================
// STOP MOTOR
// ======================================================

void motorStop(
  int HA,
  int HB,
  int LA,
  int LB
) {

  pwmWrite(HA, 0);
  pwmWrite(HB, 0);

  digitalWrite(LA, LOW);
  digitalWrite(LB, LOW);
}


// ======================================================
// MOTOR CONTROL
// ======================================================

void moverMotor(
  int HA,
  int HB,
  int LA,
  int LB,
  int velocidad
) {

  velocidad = constrain(
    velocidad,
    -255,
    255
  );

  if (velocidad > 0) {

    motorAdelante(
      HA,
      HB,
      LA,
      LB,
      velocidad
    );

  }
  else if (velocidad < 0) {

    motorAtras(
      HA,
      HB,
      LA,
      LB,
      -velocidad
    );

  }
  else {

    motorStop(
      HA,
      HB,
      LA,
      LB
    );
  }
}


// ======================================================
// ORANGE LED
// ======================================================

void ledsNaranja() {

  for (int i = 0; i < NUM_LEDS; i++) {

    leds.setPixelColor(
      i,
      leds.Color(255, 80, 0)
    );
  }

  leds.show();
}


// ======================================================
// BREATHING BLUE LED
// ======================================================

void ledsAzulRespirando() {

  if (subiendo) {

    brillo += velocidadResp;

    if (brillo >= 1.0) {

      brillo = 1.0;
      subiendo = false;
    }

  }
  else {

    brillo -= velocidadResp;

    if (brillo <= 0.05) {

      brillo = 0.05;
      subiendo = true;
    }
  }

  int b = brillo * 255;

  for (int i = 0; i < NUM_LEDS; i++) {

    leds.setPixelColor(
      i,
      leds.Color(0, 0, b)
    );
  }

  leds.show();
}


// ======================================================
// TURNING LED (blinking orange)
// ======================================================

void ledsGiro() {

  if (millis() - lastLedMove < ledInterval) {
    return;
  }

  lastLedMove = millis();

  ledEncendido = !ledEncendido;

  if (ledEncendido) {

    leds.setPixelColor(
      0,
      leds.Color(255, 80, 0)
    );

  }
  else {

    leds.clear();
  }

  leds.show();
}


// ======================================================
// READ USB SERIAL
// ======================================================

void leerSerial() {

  while (Serial.available()) {

    char c = Serial.read();

    // End of message
    if (c == '\n') {

      int coma = mensaje.indexOf(',');

      if (coma > 0) {

        int nuevoThrottle =
          mensaje.substring(0, coma).toInt();

        int nuevoSteering =
          mensaje.substring(coma + 1).toInt();

        // Check that the values are within range
        if (
          nuevoThrottle >= -100 &&
          nuevoThrottle <= 100 &&
          nuevoSteering >= -100 &&
          nuevoSteering <= 100
        ) {

          throttle = nuevoThrottle;
          steering = nuevoSteering;

          Serial.print("RECEIVED -> Throttle: ");
          Serial.print(throttle);

          Serial.print(" Steering: ");
          Serial.println(steering);
        }
      }

      mensaje = "";
    }

    // Ignore carriage return
    else if (c != '\r') {

      if (mensaje.length() < 30) {

        mensaje += c;

      }
      else {

        mensaje = "";
      }
    }
  }
}


// ======================================================
// SETUP
// ======================================================

void setup() {

  Serial.begin(BAUDRATE);

  // -------------------------
  // Motor pins
  // -------------------------

  pinMode(M1_HA, OUTPUT);
  pinMode(M1_HB, OUTPUT);
  pinMode(M1_LA, OUTPUT);
  pinMode(M1_LB, OUTPUT);

  pinMode(M2_HA, OUTPUT);
  pinMode(M2_HB, OUTPUT);
  pinMode(M2_LA, OUTPUT);
  pinMode(M2_LB, OUTPUT);

  pinMode(M3_HA, OUTPUT);
  pinMode(M3_HB, OUTPUT);
  pinMode(M3_LA, OUTPUT);
  pinMode(M3_LB, OUTPUT);

  pinMode(M4_HA, OUTPUT);
  pinMode(M4_HB, OUTPUT);
  pinMode(M4_LA, OUTPUT);
  pinMode(M4_LB, OUTPUT);

  // -------------------------
  // PWM and initial safety
  // -------------------------

  pwmInit();
  apagarTodo();

  // -------------------------
  // LED
  // -------------------------

  leds.begin();
  leds.clear();
  leds.show();

  // -------------------------
  // Startup message
  // -------------------------

  Serial.println();
  Serial.println("Rover ready");
  Serial.println("Format: throttle,steering");
  Serial.println("Range: -100 to 100");
}


// ======================================================
// LOOP
// ======================================================

void loop() {

  // ====================================================
  // READ COMMANDS
  // ====================================================

  leerSerial();


  // ====================================================
  // THROTTLE
  // ====================================================

  int velocidad = map(
    throttle,
    -100,
    100,
    -velocidadLinealMax,
    velocidadLinealMax
  );


  // ====================================================
  // STEERING / ROTATION
  // ====================================================

  int giro = map(
    steering,
    -100,
    100,
    -velocidadGiroMax,
    velocidadGiroMax
  );


  // ====================================================
  // DIFFERENTIAL MIX
  // ====================================================
  //
  // throttle != 0 + steering = turn while moving
  //
  // throttle = 0 + steering != 0
  // = rotate in place
  //

  int izquierda =
    velocidad + giro;

  int derecha =
    velocidad - giro;


  // ====================================================
  // LIMIT PWM
  // ====================================================

  izquierda = constrain(
    izquierda,
    -255,
    255
  );

  derecha = constrain(
    derecha,
    -255,
    255
  );


  // ====================================================
  // MOTORS
  // ====================================================

  // M1 - rear left
  moverMotor(
    M1_HA,
    M1_HB,
    M1_LA,
    M1_LB,
    izquierda * M1_DIR
  );


  // M2 - rear right
  moverMotor(
    M2_HA,
    M2_HB,
    M2_LA,
    M2_LB,
    derecha * M2_DIR
  );


  // M3 - front left
  moverMotor(
    M3_HA,
    M3_HB,
    M3_LA,
    M3_LB,
    izquierda * M3_DIR
  );


  // M4 - front right
  moverMotor(
    M4_HA,
    M4_HB,
    M4_LA,
    M4_LB,
    derecha * M4_DIR
  );


  // ====================================================
  // LED
  // ====================================================

  bool moviendo =
    abs(izquierda) > 5 ||
    abs(derecha) > 5;

  bool girando =
    abs(steering) > 5;


  if (girando) {

    ledsGiro();

  }
  else if (moviendo) {

    ledsNaranja();

  }
  else {

    ledsAzulRespirando();
  }


  // ====================================================
  // DEBUG
  // ====================================================

  if (millis() - lastPrint > 200) {

    lastPrint = millis();

    Serial.print("Throttle: ");
    Serial.print(throttle);

    Serial.print(" Steering: ");
    Serial.print(steering);

    Serial.print(" | L: ");
    Serial.print(izquierda);

    Serial.print(" R: ");
    Serial.println(derecha);
  }
}
