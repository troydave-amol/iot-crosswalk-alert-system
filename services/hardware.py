"""
hardware.py — ESP32 warning relay singleton.

Lazily initialises the hardware relay based on .env configuration.
Import ``esp32_relay`` from here instead of creating one in app.py.
"""

from config import ESP32_ENABLED, ESP32_PORT, ESP32_BAUD
from hardware_controller import ESP32Relay

esp32_relay = ESP32Relay(
    port=ESP32_PORT,
    baud=ESP32_BAUD,
    enabled=ESP32_ENABLED,
)
