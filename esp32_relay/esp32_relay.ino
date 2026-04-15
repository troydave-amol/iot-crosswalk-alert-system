// ============================================================================
// ESP32 Relay Controller — Smart Crosswalk Alert System
// ============================================================================
// This sketch listens on the USB Serial port for simple commands from the
// Python AI backend and controls a 2-channel relay module accordingly.
//
// Protocol:
//   '1' → Turn Relay ON  (warning light activated)
//   '0' → Turn Relay OFF (warning light deactivated)
//   '?'  → Reply with current state ("ON" or "OFF")
//
// Wiring:
//   ESP32 GPIO4  → Relay IN1
//   ESP32 GND    → Relay GND
//   ESP32 VIN    → Relay VCC (5V from USB)
// ============================================================================

#define RELAY_PIN 4        // GPIO pin connected to Relay IN1
#define BAUD_RATE 115200   // Must match Python's serial config
#define BUILT_IN_LED 2     // ESP32 onboard blue LED (visual feedback)

bool relayState = false;   // Track current state

void setup() {
  Serial.begin(BAUD_RATE);

  // Configure pins
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUILT_IN_LED, OUTPUT);

  // Start with relay OFF (HIGH = OFF for most relay modules)
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(BUILT_IN_LED, LOW);

  // Signal that ESP32 is ready
  Serial.println("ESP32_RELAY_READY");
}

void loop() {
  // Check if the Python backend sent a command
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == '1') {
      // --- TURN ON ---
      digitalWrite(RELAY_PIN, LOW);   // LOW = ON for most relay modules
      digitalWrite(BUILT_IN_LED, HIGH);
      relayState = true;
      Serial.println("ACK:ON");

    } else if (command == '0') {
      // --- TURN OFF ---
      digitalWrite(RELAY_PIN, HIGH);  // HIGH = OFF for most relay modules
      digitalWrite(BUILT_IN_LED, LOW);
      relayState = false;
      Serial.println("ACK:OFF");

    } else if (command == '?') {
      // --- STATUS CHECK ---
      Serial.println(relayState ? "STATUS:ON" : "STATUS:OFF");
    }
    // Ignore any other characters (like newlines)
  }
}
