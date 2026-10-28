"""
run_manual_relay_trials.py — Guided 10-Trial Manual Physical Relay Verification
=============================================================================
Conducts 10 sequential ON/OFF command trials to test the ESP32 relay and LED,
prompting the user after each command to verify physical illumination/switching.
Outputs a timestamped CSV and formatted Markdown table for Chapter 4 evidence.

Usage:
    venv\\Scripts\\python.exe scripts/run_manual_relay_trials.py
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load port from .env if available
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import serial
import serial.tools.list_ports
from config import ESP32_PORT, ESP32_BAUD

def find_available_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports

def main():
    print("=" * 72)
    print("   ESP32 PHYSICAL RELAY & LED WARNING TEST (10 MANUAL TRIALS)")
    print("=" * 72)
    print("This guided utility sends 5 ON and 5 OFF commands to the ESP32 relay,")
    print("prompting you to record physical LED illumination for each trial.\n")

    # Step 0: Port Check
    available = find_available_ports()
    target_port = ESP32_PORT
    print(f"Configured Port: {target_port} @ {ESP32_BAUD} baud")
    print(f"Detected Ports : {', '.join(available) if available else 'None detected'}")

    if target_port not in available:
        print(f"\n[!] WARNING: '{target_port}' was not found in active COM ports.")
        if available:
            print(f"    Available ports: {available}")
            choice = input(f"    Use {available[0]} instead? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                target_port = available[0]
            else:
                target_port = input("    Enter COM port manually (e.g. COM3, COM5): ").strip()
        else:
            print("    Please check that your ESP32 is plugged in via USB.")
            retry = input("    Press Enter to try opening anyway, or Ctrl+C to abort...")

    print(f"\nOpening {target_port} at {ESP32_BAUD} baud...")
    try:
        ser = serial.Serial(target_port, ESP32_BAUD, timeout=2)
    except serial.SerialException as e:
        print(f"\n[ERROR] Could not open {target_port}: {e}")
        print("Note: If app.py is running, STOP IT first so it releases the COM port.")
        sys.exit(1)

    print("Waiting 3 seconds for ESP32 serial initialization...")
    time.sleep(3)
    if ser.in_waiting:
        boot_msg = ser.read(ser.in_waiting).decode(errors="ignore").strip()
        print(f"[ESP32 Output]: {boot_msg}")

    # Prepare trials: 5 ON and 5 OFF alternating
    trials_def = [
        (1, "ON",  b"1", "Illuminated"),
        (2, "OFF", b"0", "Off"),
        (3, "ON",  b"1", "Illuminated"),
        (4, "OFF", b"0", "Off"),
        (5, "ON",  b"1", "Illuminated"),
        (6, "OFF", b"0", "Off"),
        (7, "ON",  b"1", "Illuminated"),
        (8, "OFF", b"0", "Off"),
        (9, "ON",  b"1", "Illuminated"),
        (10, "OFF", b"0", "Off"),
    ]

    results = []
    print("\n" + "-" * 72)
    print("READY TO BEGIN. Position your phone camera to capture the ESP32, relay,")
    print("and LED warning lamp during the test.")
    print("-" * 72)
    input("Press Enter to begin Trial 1...")

    for trial_no, cmd_name, cmd_byte, expected_state in trials_def:
        print(f"\n>>> Trial {trial_no}/10: Sending '{cmd_name}' command (byte {cmd_byte})...")
        t_sent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Flush and send
        ser.reset_input_buffer()
        ser.write(cmd_byte)
        ser.flush()
        time.sleep(0.4)

        esp_resp = ""
        if ser.in_waiting:
            esp_resp = ser.read(ser.in_waiting).decode(errors="ignore").strip()
            print(f"    [ESP32 Response]: {esp_resp}")

        # Prompt user for physical observation
        prompt = f"    [OBSERVE] Expected LED: '{expected_state}'. Is LED '{expected_state}'? [Y/n]: "
        ans = input(prompt).strip().lower()
        if ans in ("", "y", "yes"):
            observed_state = expected_state
            verdict = "Pass"
        else:
            observed_state = input("    Enter actual observed state (e.g. Off, Strobe, Unchanged): ").strip()
            verdict = "Fail"

        results.append({
            "trial": trial_no,
            "timestamp": t_sent,
            "command": cmd_name,
            "expected": expected_state,
            "observed": observed_state,
            "result": verdict,
            "esp_resp": esp_resp,
        })
        time.sleep(0.5)

    ser.close()
    print("\n[OK] Port closed successfully.")

    # Summary
    passes = sum(1 for r in results if r["result"] == "Pass")
    total = len(results)
    print("\n" + "=" * 72)
    print(f"TEST COMPLETED: {passes}/{total} Trials Passed ({passes/total*100:.1f}%)")
    print("=" * 72)

    # Save to CSV
    log_dir = ROOT / "docs" / "evidence"
    log_dir.mkdir(parents=True, exist_ok=True)
    csv_path = log_dir / "physical_relay_test_log.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Trial,Timestamp,Command Sent,Expected LED State,Observed LED State,Result,ESP32 Serial Response\n")
        for r in results:
            f.write(f"{r['trial']},{r['timestamp']},{r['command']},{r['expected']},{r['observed']},{r['result']},{r['esp_resp']}\n")
    print(f"\n[Saved CSV Log]: {csv_path}")

    # Generate Markdown Table ready for Chapter 4
    md_content = []
    md_content.append("\n### Physical Relay & LED Warning Actuation Test Log\n")
    md_content.append(f"**Date Executed:** {results[0]['timestamp'].split()[0]}\n")
    md_content.append(f"**Target Port:** {target_port} @ {ESP32_BAUD} baud\n\n")
    md_content.append("| Trial | Command Sent | Expected LED State | Observed LED State | Result |\n")
    md_content.append("| :---: | :---: | :--- | :--- | :---: |\n")
    for r in results:
        md_content.append(f"| {r['trial']} | {r['command']} | {r['expected']} | {r['observed']} | **{r['result']}** |\n")
    md_content.append(f"\n**Outcome:** {passes} of {total} command-response trials verified successfully.\n")

    md_str = "".join(md_content)
    print(md_str)

    md_path = log_dir / "physical_relay_test_log.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_str)
    print(f"[Saved Markdown Evidence]: {md_path}")

if __name__ == "__main__":
    main()
