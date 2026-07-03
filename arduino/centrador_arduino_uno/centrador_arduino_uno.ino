/*
  Centrador Corrugadora - Arduino UNO

  Protocolo serie 115200:
    PING                 -> PONG
    ENABLE 1             -> habilita pulsos
    ENABLE 0             -> deshabilita y apaga salidas
    HB                   -> heartbeat desde la PC
    STOP                 -> apaga salidas
    PULSE L 100          -> activa salida izquierda 100 ms
    PULSE R 250          -> activa salida derecha 250 ms

  IMPORTANTE:
  - Arduino NO debe conectarse directo a entradas de maquina sin interfaz adecuada.
  - Usar modulo de reles u optoacopladores.
  - Para simular botones existentes, usar contactos secos NA en paralelo a cada pulsador.
  - Nunca alimentar la botonera desde el Arduino.
*/

const uint8_t PIN_RELAY_LEFT = 7;
const uint8_t PIN_RELAY_RIGHT = 8;
const bool RELAY_ACTIVE_LOW = false;   // Cambiar a true si tu modulo de reles activa con LOW.

const unsigned long WATCHDOG_MS = 3000;
const unsigned int MAX_PULSE_MS = 1000;

bool enabled = false;
unsigned long lastHeartbeatMs = 0;
unsigned long pulseEndMs = 0;
char activeDirection = '-';

String inputLine = "";

void relayWrite(uint8_t pin, bool on) {
  if (RELAY_ACTIVE_LOW) {
    digitalWrite(pin, on ? LOW : HIGH);
  } else {
    digitalWrite(pin, on ? HIGH : LOW);
  }
}

void allOff() {
  relayWrite(PIN_RELAY_LEFT, false);
  relayWrite(PIN_RELAY_RIGHT, false);
  activeDirection = '-';
  pulseEndMs = 0;
}

void setup() {
  pinMode(PIN_RELAY_LEFT, OUTPUT);
  pinMode(PIN_RELAY_RIGHT, OUTPUT);
  allOff();
  Serial.begin(115200);
  inputLine.reserve(80);
  lastHeartbeatMs = millis();
  Serial.println("READY CENTRADOR UNO");
}

void loop() {
  readSerialLines();
  handlePulseTimeout();
  handleWatchdog();
}

void readSerialLines() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      inputLine.trim();
      if (inputLine.length() > 0) {
        processCommand(inputLine);
      }
      inputLine = "";
    } else {
      if (inputLine.length() < 79) inputLine += c;
    }
  }
}

void handlePulseTimeout() {
  if (activeDirection != '-' && millis() >= pulseEndMs) {
    allOff();
    Serial.println("OK PULSE_DONE");
  }
}

void handleWatchdog() {
  if (enabled && (millis() - lastHeartbeatMs > WATCHDOG_MS)) {
    enabled = false;
    allOff();
    Serial.println("FAULT WATCHDOG");
  }
}

void processCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }

  if (cmd == "HB") {
    lastHeartbeatMs = millis();
    Serial.println("OK HB");
    return;
  }

  if (cmd == "STOP") {
    allOff();
    Serial.println("OK STOP");
    return;
  }

  if (cmd.startsWith("ENABLE")) {
    int spaceIdx = cmd.indexOf(' ');
    int value = 0;
    if (spaceIdx > 0) value = cmd.substring(spaceIdx + 1).toInt();
    enabled = (value == 1);
    lastHeartbeatMs = millis();
    if (!enabled) allOff();
    Serial.println(enabled ? "OK ENABLED" : "OK DISABLED");
    return;
  }

  if (cmd.startsWith("PULSE")) {
    handlePulseCommand(cmd);
    return;
  }

  Serial.print("ERR UNKNOWN ");
  Serial.println(cmd);
}

void handlePulseCommand(String cmd) {
  if (!enabled) {
    allOff();
    Serial.println("ERR NOT_ENABLED");
    return;
  }

  // Formato: PULSE L 100
  int first = cmd.indexOf(' ');
  int second = cmd.indexOf(' ', first + 1);
  if (first < 0 || second < 0) {
    Serial.println("ERR BAD_PULSE_FORMAT");
    return;
  }

  String dir = cmd.substring(first + 1, second);
  unsigned int ms = (unsigned int)cmd.substring(second + 1).toInt();
  if (ms == 0) {
    Serial.println("ERR BAD_PULSE_MS");
    return;
  }
  if (ms > MAX_PULSE_MS) ms = MAX_PULSE_MS;

  allOff(); // enclavamiento simple: nunca quedan ambas salidas.

  if (dir == "L" || dir == "LEFT" || dir == "IZQUIERDA") {
    relayWrite(PIN_RELAY_LEFT, true);
    activeDirection = 'L';
  } else if (dir == "R" || dir == "RIGHT" || dir == "DERECHA") {
    relayWrite(PIN_RELAY_RIGHT, true);
    activeDirection = 'R';
  } else {
    Serial.println("ERR BAD_DIRECTION");
    return;
  }

  pulseEndMs = millis() + ms;
  lastHeartbeatMs = millis();
  Serial.print("OK PULSE ");
  Serial.print(activeDirection);
  Serial.print(" ");
  Serial.println(ms);
}
