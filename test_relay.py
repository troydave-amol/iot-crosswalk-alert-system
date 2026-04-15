"""
Quick ESP32 relay test — run this AFTER stopping app.py
Usage: python test_relay.py
"""
import time
import serial

PORT = "COM5"
BAUD = 115200

print(f"Opening {PORT} at {BAUD} baud...")
ser = serial.Serial(PORT, BAUD, timeout=2)

# Wait for ESP32 to boot (opening serial resets it)
print("Waiting 3 seconds for ESP32 to boot...")
time.sleep(3)

# Read boot message
if ser.in_waiting:
    boot = ser.read(ser.in_waiting).decode(errors="ignore")
    print(f"ESP32 boot message: {boot.strip()}")

# Test ON
print("\n--- Sending '1' (ON) ---")
ser.write(b'1')
ser.flush()
time.sleep(0.5)
if ser.in_waiting:
    response = ser.read(ser.in_waiting).decode(errors="ignore").strip()
    print(f"ESP32 response: {response}")
else:
    print("No response from ESP32!")

print(">> Check: Is the ESP32 blue LED on? Is the relay clicking?")
input(">> Press Enter to continue...")

# Test OFF
print("\n--- Sending '0' (OFF) ---")
ser.write(b'0')
ser.flush()
time.sleep(0.5)
if ser.in_waiting:
    response = ser.read(ser.in_waiting).decode(errors="ignore").strip()
    print(f"ESP32 response: {response}")
else:
    print("No response from ESP32!")

print(">> Check: Did the blue LED turn off? Did the relay click again?")

# Cleanup
ser.close()
print("\nDone! Serial port closed.")
