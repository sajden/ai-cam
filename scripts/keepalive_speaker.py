"""
keepalive_speaker.py
Plays silent audio every 4 minutes to prevent Bluetooth speaker from sleeping.
"""
import time
import numpy as np
import sounddevice as sd

INTERVAL_SEC = 240  # every 4 minutes
DURATION_SEC = 2

print("[keepalive] Started — playing silent audio every", INTERVAL_SEC, "seconds")

while True:
    try:
        silence = np.zeros(int(44100 * DURATION_SEC), dtype=np.float32)
        sd.play(silence, samplerate=44100)
        sd.wait()
    except Exception as e:
        print("[keepalive] Warning:", e)
    time.sleep(INTERVAL_SEC)
