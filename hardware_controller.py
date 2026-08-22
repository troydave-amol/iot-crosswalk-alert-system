"""
hardware_controller.py — ESP32 Relay Serial Bridge
====================================================
Manages the serial connection between the Python AI backend and the
ESP32 microcontroller that controls the physical warning relay.

Uses LAZY INITIALIZATION — connects on first use, not at import time.
This avoids COM port conflicts with Flask's debug reloader.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


class ESP32Relay:
    """
    Thread-safe controller for the ESP32-based relay module.

    - Lazily connects to the ESP32 on first use (avoids reloader conflicts).
    - Sends '1' (ON) or '0' (OFF) commands.
    - Non-blocking: if the ESP32 is disconnected, the AI keeps running.
    """

    def __init__(
        self,
        port: str = "COM5",
        baud: int = 115200,
        reconnect_interval: float = 5.0,
        enabled: bool = True,
    ):
        self.port = port
        self.baud = baud
        self.reconnect_interval = reconnect_interval
        self.enabled = enabled

        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False
        self._current_state: Optional[bool] = None
        self._last_connect_attempt: float = 0.0
        self._initialized = False  # Lazy init flag
        self._heartbeat_ok = False
        self._last_heartbeat_time: float = 0.0
        self._heartbeat_rtt_ms: float = 0.0

        if not SERIAL_AVAILABLE:
            print("[HW] pyserial not installed — hardware relay disabled")
            self.enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, warning_on: bool) -> bool:
        """Set relay state. Lazily connects on first call."""
        if not self.enabled:
            return False

        # Lazy init: connect on first actual use
        if not self._initialized:
            self._initialized = True
            print(f"[HW] First use — connecting to ESP32 on {self.port}...")
            self._try_connect()

        # Only send if state actually changed
        if self._current_state == warning_on:
            return True

        return self._send_command(warning_on)

    def turn_on(self) -> bool:
        return self.set_state(True)

    def turn_off(self) -> bool:
        return self.set_state(False)

    def check_heartbeat(self) -> bool:
        """
        Sends '?' ping to ESP32 and checks for 'STATUS:' response.
        Returns True if ESP32 responds, False otherwise.
        Non-blocking with short timeout (0.2s).
        """
        if not self.enabled or not SERIAL_AVAILABLE:
            return False

        if not self._initialized:
            self._initialized = True
            self._try_connect()

        if not self._connected or self._serial is None:
            self._heartbeat_ok = False
            return False

        with self._lock:
            if self._serial is None:
                self._heartbeat_ok = False
                return False
            try:
                # Flush any leftover input
                if self._serial.in_waiting:
                    self._serial.read(self._serial.in_waiting)

                t0 = time.perf_counter()
                self._serial.write(b'?')
                self._serial.flush()

                # Wait for response (up to 200ms)
                deadline = time.time() + 0.2
                response = ""
                while time.time() < deadline:
                    if self._serial.in_waiting:
                        line = self._serial.readline().decode(errors="ignore").strip()
                        if "STATUS:" in line or "ACK:" in line:
                            response = line
                            break
                    time.sleep(0.02)

                if response:
                    self._last_heartbeat_time = time.time()
                    self._heartbeat_ok = True
                    self._heartbeat_rtt_ms = round((time.perf_counter() - t0) * 1000, 1)
                    return True
                else:
                    self._heartbeat_ok = False
                    return False
            except Exception as e:
                print(f"[HW] Heartbeat error on {self.port}: {e}")
                self._connected = False
                self._heartbeat_ok = False
                return False

    def get_diagnostics(self) -> dict:
        """
        Returns plain-language diagnostic telemetry for the IT Specialist dashboard.
        """
        if not self.enabled:
            return {
                "connected": False,
                "label": "Disabled",
                "heartbeat_ok": False,
                "heartbeat_label": "Disabled",
                "port": self.port,
                "relay_state": "OFF"
            }

        is_conn = bool(self._connected)
        hb_ok = bool(getattr(self, "_heartbeat_ok", False)) and is_conn
        
        return {
            "connected": is_conn,
            "label": "Connected" if is_conn else "Disconnected",
            "heartbeat_ok": hb_ok,
            "heartbeat_label": "Responding" if hb_ok else "Not Responding",
            "port": self.port,
            "relay_state": "ON" if self._current_state else "OFF",
            "last_heartbeat": getattr(self, "_last_heartbeat_time", 0.0)
        }

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> str:
        if not self.enabled:
            return "Disabled"
        if not SERIAL_AVAILABLE:
            return "No pyserial"
        if not self._initialized:
            return "Standby"
        if self._connected:
            return "Connected"
        return "Disconnected"

    def close(self):
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.write(b'0')
                    time.sleep(0.05)
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            self._connected = False
            self._heartbeat_ok = False
            self._current_state = None
            print("[HW] Serial connection closed")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_connect(self) -> bool:
        now = time.time()
        if (now - self._last_connect_attempt) < self.reconnect_interval:
            return False

        self._last_connect_attempt = now

        with self._lock:
            # Close any existing stale connection
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

            try:
                self._serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baud,
                    timeout=1.0,
                    write_timeout=1.0,
                )

                # Wait for ESP32 to boot (opening serial resets it)
                time.sleep(2.5)

                # Drain boot message
                if self._serial.in_waiting:
                    boot_msg = self._serial.read(
                        self._serial.in_waiting
                    ).decode(errors="ignore").strip()
                    print(f"[HW] ESP32 says: {boot_msg}")

                self._connected = True
                self._current_state = None
                print(f"[HW] Connected to ESP32 on {self.port}")
                return True

            except Exception as e:
                self._connected = False
                self._serial = None
                print(f"[HW] Cannot connect to {self.port}: {e}")
                return False

    def _send_command(self, turn_on: bool) -> bool:
        if not self.enabled:
            return False

        # Reconnect if needed
        if not self._connected:
            self._try_connect()
            if not self._connected:
                return False

        cmd = b'1' if turn_on else b'0'
        label = "ON" if turn_on else "OFF"

        with self._lock:
            if self._serial is None:
                return False

            try:
                self._serial.write(cmd)
                self._serial.flush()
                self._current_state = turn_on
                print(f"[HW] Relay -> {label}")

                # Drain any ACK response (don't wait)
                try:
                    if self._serial.in_waiting:
                        self._serial.read(self._serial.in_waiting)
                except Exception:
                    pass

                return True

            except Exception as e:
                print(f"[HW] Serial error: {e} — will reconnect")
                self._connected = False
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                self._current_state = None
                return False
