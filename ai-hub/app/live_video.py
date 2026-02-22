from __future__ import annotations

import logging
import threading
import time
from typing import Any

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


log = logging.getLogger("aihub.live_video")


class LiveVideoFeed:
    """Continuously reads frames from RTSP and keeps only the newest one."""

    def __init__(
        self,
        *,
        rtsp_url: str,
        target_fps: float = 10.0,
        max_stale_sec: float = 2.0,
        reconnect_sec: float = 1.0,
        jpeg_quality: int = 80,
    ) -> None:
        self._rtsp_url = (rtsp_url or "").strip()
        self._target_fps = max(1.0, float(target_fps))
        self._max_stale_sec = max(0.2, float(max_stale_sec))
        self._reconnect_sec = max(0.1, float(reconnect_sec))
        self._jpeg_quality = max(30, min(95, int(jpeg_quality)))

        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_error = ""

        self._last_frame_at = 0.0
        self._latest_jpeg: bytes = b""
        self._latest_frame: Any = None
        self._latest_shape: tuple[int, int] | None = None

    def available(self) -> bool:
        return cv2 is not None and bool(self._rtsp_url)

    def start(self) -> None:
        if self._running:
            return
        if not self.available():
            if cv2 is None:
                self._last_error = "opencv_missing"
                log.warning("Live video disabled: opencv missing")
            elif not self._rtsp_url:
                self._last_error = "rtsp_url_missing"
                log.warning("Live video disabled: rtsp URL missing")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Live video feed started (fps=%.1f)", self._target_fps)

    def stop(self) -> None:
        self._running = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            age_sec = max(0.0, time.monotonic() - self._last_frame_at) if self._last_frame_at else -1.0
            return {
                "running": self._running,
                "available": self.available(),
                "last_error": self._last_error,
                "has_frame": bool(self._latest_jpeg),
                "frame_age_sec": round(age_sec, 3),
                "frame_shape": self._latest_shape,
            }

    def get_latest(
        self,
        max_age_sec: float | None = None,
    ) -> tuple[bool, bytes, Any | None, str]:
        """Return (ok, jpeg_bytes, bgr_frame, reason)."""
        age_limit = self._max_stale_sec if max_age_sec is None else max(0.2, float(max_age_sec))
        with self._lock:
            if not self._latest_jpeg or self._latest_frame is None or self._last_frame_at <= 0:
                return False, b"", None, self._last_error or "no_frame"
            age = max(0.0, time.monotonic() - self._last_frame_at)
            if age > age_limit:
                return False, b"", None, f"stale_frame:{age:.2f}s"
            # Return copies to avoid races while the reader thread updates.
            frame_copy = self._latest_frame.copy()
            return True, bytes(self._latest_jpeg), frame_copy, ""

    def _run(self) -> None:
        assert cv2 is not None
        frame_interval = 1.0 / self._target_fps
        while self._running:
            cap = None
            try:
                cap = cv2.VideoCapture(self._rtsp_url)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                if not cap.isOpened():
                    self._set_error("rtsp_open_failed")
                    time.sleep(self._reconnect_sec)
                    continue

                while self._running:
                    t0 = time.monotonic()
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        self._set_error("rtsp_read_failed")
                        break

                    enc_ok, buf = cv2.imencode(
                        ".jpg",
                        frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
                    )
                    if not enc_ok:
                        self._set_error("jpeg_encode_failed")
                        continue

                    with self._lock:
                        self._latest_frame = frame
                        self._latest_jpeg = buf.tobytes()
                        self._last_frame_at = time.monotonic()
                        h, w = frame.shape[:2]
                        self._latest_shape = (int(w), int(h))
                        self._last_error = ""

                    elapsed = time.monotonic() - t0
                    sleep_for = frame_interval - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
            except Exception as exc:  # pragma: no cover
                self._set_error(f"video_loop_error:{type(exc).__name__}")
                time.sleep(self._reconnect_sec)
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
            if self._running:
                time.sleep(self._reconnect_sec)

    def _set_error(self, reason: str) -> None:
        with self._lock:
            self._last_error = reason[:200]
