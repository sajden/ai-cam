"""
keepalive_speaker.py
Plays silent audio every N seconds to prevent Bluetooth speaker from sleeping.

Env vars:
  BT_SPEAKER_NAME   Partial name match for the BT device (case-insensitive).
                    If unset or empty, plays on the system default output device.
  KEEPALIVE_INTERVAL_SEC   Seconds between keepalive pings (default: 240)
  KEEPALIVE_DURATION_SEC   Duration of each silent clip in seconds (default: 1)
"""
import os
import time

import numpy as np
import sounddevice as sd

INTERVAL_SEC = int(os.getenv("KEEPALIVE_INTERVAL_SEC", "240"))
DURATION_SEC = float(os.getenv("KEEPALIVE_DURATION_SEC", "1"))
BT_NAME = os.getenv("BT_SPEAKER_NAME", "").strip().lower()
SAMPLE_RATE = 44100


def _find_device(partial_name: str) -> int | None:
    """Return the first output device index whose name contains partial_name (case-insensitive)."""
    for dev in sd.query_devices():
        if dev["max_output_channels"] > 0 and partial_name in dev["name"].lower():
            return dev["index"]
    return None


def _list_output_devices() -> None:
    print("[keepalive] Available output devices:")
    for dev in sd.query_devices():
        if dev["max_output_channels"] > 0:
            print(f"  [{dev['index']}] {dev['name']}")


def _play_silence(device: int | None) -> None:
    silence = np.zeros(int(SAMPLE_RATE * DURATION_SEC), dtype=np.float32)
    sd.play(silence, samplerate=SAMPLE_RATE, device=device)
    sd.wait()


def main() -> None:
    if BT_NAME:
        print(f"[keepalive] Looking for BT speaker matching: '{BT_NAME}'")
        _list_output_devices()
    else:
        print("[keepalive] BT_SPEAKER_NAME not set — using system default output device")

    print(f"[keepalive] Interval: {INTERVAL_SEC}s, clip duration: {DURATION_SEC}s")

    while True:
        device: int | None = None

        if BT_NAME:
            device = _find_device(BT_NAME)
            if device is None:
                print(f"[keepalive] Device '{BT_NAME}' not found — speaker may be off or disconnected. Will retry.")
                time.sleep(INTERVAL_SEC)
                continue
            # Only log device name on first successful find or after reconnect
            dev_name = sd.query_devices(device)["name"]
            print(f"[keepalive] Pinging '{dev_name}' (device {device})")

        try:
            _play_silence(device)
        except Exception as exc:
            print(f"[keepalive] Warning: {exc}")

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
