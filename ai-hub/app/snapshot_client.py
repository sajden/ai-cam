"""Fetch a JPEG snapshot from go2rtc (via Frigate)."""

from __future__ import annotations

import os
import urllib.error
import urllib.request


GO2RTC_BASE_URL = os.getenv("AIHUB_GO2RTC_BASE_URL", "http://frigate:1984").rstrip("/")
SNAPSHOT_STREAM = os.getenv("AIHUB_SNAPSHOT_STREAM", "reolink_e1pro_main")
SNAPSHOT_TIMEOUT_SEC = float(os.getenv("AIHUB_SNAPSHOT_TIMEOUT_SEC", "5"))
SNAPSHOT_RETRIES = int(os.getenv("AIHUB_SNAPSHOT_RETRIES", "2"))


def fetch_snapshot() -> tuple[bool, bytes]:
    """Return (ok, jpeg_bytes) from the go2rtc frame endpoint.

    Uses the main stream for full resolution (1920x1080).
    """
    url = f"{GO2RTC_BASE_URL}/api/frame.jpeg?src={SNAPSHOT_STREAM}"
    req = urllib.request.Request(url, method="GET")
    last_err = b""
    attempts = max(1, SNAPSHOT_RETRIES)
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=max(0.5, SNAPSHOT_TIMEOUT_SEC)) as resp:
                data = resp.read()
                if not data:
                    last_err = b"go2rtc-fel: empty_response"
                    continue
                return True, data
        except urllib.error.HTTPError as exc:
            last_err = f"go2rtc HTTP {exc.code}".encode()
        except Exception as exc:
            last_err = f"go2rtc-fel: {type(exc).__name__}".encode()
    return False, last_err
