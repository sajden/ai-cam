from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


log = logging.getLogger("aihub.follow_tracker")


# How many consecutive same-direction bursts constitute a full 360° pan.
# At default burst=0.35s speed=14 this is roughly one full revolution.
_FULL_PAN_STEPS = int(20)


class SoftFollowController:
    """Local PTZ follow with explicit state machine and lock stabilization."""

    def __init__(
        self,
        *,
        frame_provider: Callable[[], Any | None],
        move_callback: Callable[[str], str],
        tick_sec: float = 0.34,
        move_cooldown_sec: float = 0.60,
        x_deadzone: float = 0.18,
        y_deadzone: float = 0.25,
        enable_tilt: bool = True,
        invert_x: bool = False,
        invert_y: bool = False,
        max_width: int = 640,
        motion_fallback: bool = False,
        motion_min_area_ratio: float = 0.004,
        lost_sweep_after_sec: float = 2.0,
        lost_sweep_cooldown_sec: float = 1.1,
        lost_sweep_pattern: list[str] | None = None,
        on_lock_callback: Callable[[str], None] | None = None,
        lock_lost_after_sec: float = 3.0,
        lock_require_consecutive: int = 3,
        lock_ack_after_consecutive: int = 5,
        sweep_max_moves: int = 6,
        sweep_pause_sec: float = 8.0,
        recover_max_moves: int = 4,
        smoothing_alpha: float = 0.35,
        full_pan_steps: int = _FULL_PAN_STEPS,
    ) -> None:
        self._frame_provider = frame_provider
        self._move_callback = move_callback
        self._tick_sec = max(0.12, float(tick_sec))
        self._move_cooldown_sec = max(0.12, float(move_cooldown_sec))
        self._x_deadzone = max(0.02, min(0.45, float(x_deadzone)))
        self._y_deadzone = max(0.02, min(0.45, float(y_deadzone)))
        self._enable_tilt = bool(enable_tilt)
        self._invert_x = bool(invert_x)
        self._invert_y = bool(invert_y)
        self._max_width = max(320, int(max_width))
        self._motion_fallback = bool(motion_fallback)
        self._motion_min_area_ratio = max(0.0005, float(motion_min_area_ratio))
        self._lost_sweep_after_sec = max(0.4, float(lost_sweep_after_sec))
        self._lost_sweep_cooldown_sec = max(0.25, float(lost_sweep_cooldown_sec))
        self._on_lock_callback = on_lock_callback
        self._lock_lost_after_sec = max(0.4, float(lock_lost_after_sec))
        self._lock_require_consecutive = max(1, int(lock_require_consecutive))
        self._lock_ack_after_consecutive = max(
            self._lock_require_consecutive,
            int(lock_ack_after_consecutive),
        )
        self._sweep_max_moves = max(1, int(sweep_max_moves))
        self._sweep_pause_sec = max(0.5, float(sweep_pause_sec))
        self._recover_max_moves = max(1, int(recover_max_moves))
        self._smoothing_alpha = max(0.05, min(0.95, float(smoothing_alpha)))
        self._full_pan_steps = max(4, int(full_pan_steps))

        self._lock = threading.Lock()
        self._running = False
        self._suspended = False  # pause PTZ moves without stopping the loop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # State
        self._state = "SEEKING"
        self._last_error = ""
        self._last_seen_at = 0.0
        self._last_target_seen_at = 0.0
        self._last_move_at = 0.0
        self._last_move_dir = ""
        self._move_count = 0
        self._move_fail_count = 0
        self._last_move_result = ""
        self._locked = False
        self._lock_source = ""
        self._consecutive_person_hits = 0
        self._search_moves = 0
        self._recover_moves = 0
        self._pause_until = 0.0
        self._person_lock_announced = False
        self._smoothed_x: float | None = None
        self._smoothed_y: float | None = None
        self._prev_gray: Any | None = None

        # Sweep state: systematic 360° search
        self._sweep_phase = 0  # 0=pan right, 1=pan left, 2=tilt+pan combos
        self._sweep_step = 0   # steps within current phase

        self._hog = None
        if cv2 is not None:
            try:
                hog = cv2.HOGDescriptor()
                hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                self._hog = hog
            except Exception:
                self._hog = None

    def available(self) -> bool:
        if cv2 is None:
            return False
        if self._hog is not None:
            return True
        return self._motion_fallback

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            return {
                "available": self.available(),
                "running": self._running,
                "state": self._state,
                "last_mode": self._state,
                "last_error": self._last_error,
                "locked": self._locked,
                "lock_source": self._lock_source,
                "consecutive_person_hits": self._consecutive_person_hits,
                "lock_require_consecutive": self._lock_require_consecutive,
                "lock_ack_after_consecutive": self._lock_ack_after_consecutive,
                "search_moves": self._search_moves,
                "recover_moves": self._recover_moves,
                "sweep_phase": self._sweep_phase,
                "sweep_step": self._sweep_step,
                "pause_seconds_left": round(max(0.0, self._pause_until - now), 2),
                "last_seen_age_sec": round(max(0.0, now - self._last_seen_at), 3)
                if self._last_seen_at > 0
                else -1.0,
                "last_move_dir": self._last_move_dir,
                "move_count": self._move_count,
                "move_fail_count": self._move_fail_count,
                "last_move_result": self._last_move_result,
                "hog_ready": self._hog is not None,
                "motion_fallback": self._motion_fallback,
            }

    def start(self) -> tuple[bool, str]:
        if not self.available():
            return False, "tracker_unavailable"
        with self._lock:
            if self._running:
                return True, "already_running"
            self._running = True
            self._state = "SEEKING"
            self._last_error = ""
            self._locked = False
            self._lock_source = ""
            self._consecutive_person_hits = 0
            self._search_moves = 0
            self._recover_moves = 0
            self._pause_until = 0.0
            self._person_lock_announced = False
            self._smoothed_x = None
            self._smoothed_y = None
            self._sweep_phase = 0
            self._sweep_step = 0
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        log.info("Soft follow started")
        return True, "started"

    def suspend_ptz(self) -> None:
        """Block PTZ moves (e.g. during a conversation turn). Thread-safe."""
        self._suspended = True

    def resume_ptz(self) -> None:
        """Re-enable PTZ moves after a conversation turn. Thread-safe."""
        self._suspended = False
        self._last_move_at = 0.0  # skip cooldown so follow re-locks quickly

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self._running:
                return True, "already_stopped"
            self._running = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        log.info("Soft follow stopped")
        return True, "stopped"

    def _run(self) -> None:
        _tick_count = 0
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            now = time.monotonic()
            _tick_count += 1
            try:
                frame = self._frame_provider()
                if frame is None:
                    if _tick_count % 10 == 1:
                        log.debug("Soft follow tick %d: no frame", _tick_count)
                    self._set_error("no_frame")
                    self._handle_no_person(now)
                    self._sleep_tick(t0)
                    continue

                found, x_norm, y_norm = self._detect_person(frame)
                if _tick_count % 5 == 1:
                    log.info(
                        "follow tick=%d state=%s found=%s pos=(%.2f,%.2f) consec=%d smooth=(%.2f,%.2f)",
                        _tick_count,
                        self._state,
                        found,
                        x_norm or 0.0,
                        y_norm or 0.0,
                        self._consecutive_person_hits,
                        self._smoothed_x or 0.0,
                        self._smoothed_y or 0.0,
                    )
                if found and x_norm is not None and y_norm is not None:
                    self._handle_person(now, x_norm, y_norm)
                    self._sleep_tick(t0)
                    continue

                if self._motion_fallback and self._state in {"LOCKED", "LOCKING"}:
                    m_found, mx, my, _ = self._detect_motion_center(frame)
                    if m_found and mx is not None and my is not None:
                        direction = self._decide_direction(mx, my)
                        self._maybe_issue_move(direction, now, "motion")
                        self._set_error("motion_fallback_no_person")
                        self._sleep_tick(t0)
                        continue

                self._set_error("person_not_found")
                self._handle_no_person(now)
            except Exception as exc:  # pragma: no cover
                self._set_error(f"follow_loop_error:{type(exc).__name__}")
            self._sleep_tick(t0)

    def _sleep_tick(self, t0: float) -> None:
        sleep_for = self._tick_sec - (time.monotonic() - t0)
        if sleep_for > 0:
            self._stop_event.wait(timeout=sleep_for)

    def _set_error(self, reason: str) -> None:
        with self._lock:
            self._last_error = reason[:200]

    def _set_state(self, state: str) -> None:
        old = self._state
        with self._lock:
            self._state = state
        if old != state:
            log.info("follow state: %s -> %s", old, state)

    def _handle_person(self, now: float, x_norm: float, y_norm: float) -> None:
        self._last_seen_at = now
        self._last_target_seen_at = now

        # Smoothing — but reset if we were searching (old position is stale)
        if self._state in {"SEEKING", "RECOVERING", "PAUSED"} or self._smoothed_x is None:
            self._smoothed_x = float(x_norm)
            self._smoothed_y = float(y_norm)
        else:
            a = self._smoothing_alpha
            self._smoothed_x = (a * float(x_norm)) + ((1.0 - a) * self._smoothed_x)
            self._smoothed_y = (a * float(y_norm)) + ((1.0 - a) * self._smoothed_y)

        if self._state in {"SEEKING", "RECOVERING", "PAUSED"}:
            self._set_state("LOCKING")
            self._consecutive_person_hits = 0
            self._recover_moves = 0
            self._search_moves = 0
            self._pause_until = 0.0

        if self._state == "LOCKING":
            self._consecutive_person_hits += 1
            if self._consecutive_person_hits >= self._lock_require_consecutive:
                self._set_state("LOCKED")
                self._locked = True
                self._lock_source = "person"
        elif self._state == "LOCKED":
            self._consecutive_person_hits = min(
                self._consecutive_person_hits + 1,
                self._lock_ack_after_consecutive + 2,
            )
            self._locked = True
            self._lock_source = "person"
        else:
            self._consecutive_person_hits = max(1, self._consecutive_person_hits)

        if (
            self._state == "LOCKED"
            and not self._person_lock_announced
            and self._consecutive_person_hits >= self._lock_ack_after_consecutive
        ):
            self._person_lock_announced = True
            if self._on_lock_callback is not None:
                try:
                    self._on_lock_callback("person")
                except Exception:  # pragma: no cover
                    log.exception("Soft follow on_lock callback failed")

        direction = self._decide_direction(self._smoothed_x, self._smoothed_y)
        if direction:
            self._maybe_issue_move(direction, now, "person")
        self._set_error("")

    def _handle_no_person(self, now: float) -> None:
        if self._state == "PAUSED":
            if now < self._pause_until:
                return
            self._set_state("SEEKING")
            self._sweep_phase = 0
            self._sweep_step = 0

        if self._state == "LOCKED":
            if (now - self._last_target_seen_at) < self._lock_lost_after_sec:
                return  # grace period — don't move
            self._set_state("RECOVERING")
            self._locked = False
            self._lock_source = ""
            self._consecutive_person_hits = 0
            self._recover_moves = 0
            self._person_lock_announced = False
            self._smoothed_x = None  # reset stale position
            self._smoothed_y = None

        if self._state == "LOCKING":
            self._set_state("SEEKING")
            self._consecutive_person_hits = 0
            self._smoothed_x = None
            self._smoothed_y = None

        lost_for = now - self._last_seen_at if self._last_seen_at > 0 else 999.0
        if lost_for < self._lost_sweep_after_sec:
            return
        if (now - self._last_move_at) < self._lost_sweep_cooldown_sec:
            return

        if self._state == "RECOVERING":
            if self._recover_moves >= self._recover_max_moves:
                self._pause_search(now, "recover_max_reached")
                return
            self._recover_moves += 1
            # Short search near last position
            dirs = ["camera_ptz_left", "camera_ptz_right"]
            direction = dirs[self._recover_moves % len(dirs)]
            self._maybe_issue_move(direction, now, "recover")
            return

        # SEEKING: systematic 360° search
        self._set_state("SEEKING")
        direction = self._next_sweep_direction()
        if direction is None:
            self._pause_search(now, "full_sweep_done")
            return
        self._search_moves += 1
        self._maybe_issue_move(direction, now, "search")

    def _next_sweep_direction(self) -> str | None:
        """Systematic search pattern:
        Phase 0: Pan right for full_pan_steps (360° one way)
        Phase 1: Pan left for full_pan_steps (360° back)
        Phase 2: Tilt up + pan right for full_pan_steps
        Phase 3: Tilt down + pan left for full_pan_steps
        Then pause.
        """
        if self._sweep_phase == 0:
            if self._sweep_step < self._full_pan_steps:
                self._sweep_step += 1
                return "camera_ptz_right"
            # Done with phase 0 -> phase 1
            self._sweep_phase = 1
            self._sweep_step = 0
            log.info("follow sweep: phase 0 done (pan right), starting phase 1 (pan left)")

        if self._sweep_phase == 1:
            if self._sweep_step < self._full_pan_steps:
                self._sweep_step += 1
                return "camera_ptz_left"
            # Done with phase 1 -> phase 2
            self._sweep_phase = 2
            self._sweep_step = 0
            log.info("follow sweep: phase 1 done (pan left), starting phase 2 (tilt up + pan)")

        if self._sweep_phase == 2:
            if self._sweep_step == 0:
                self._sweep_step += 1
                return "camera_ptz_up"
            if self._sweep_step < self._full_pan_steps + 1:
                self._sweep_step += 1
                return "camera_ptz_right"
            self._sweep_phase = 3
            self._sweep_step = 0
            log.info("follow sweep: phase 2 done, starting phase 3 (tilt down + pan)")

        if self._sweep_phase == 3:
            if self._sweep_step == 0:
                self._sweep_step += 1
                return "camera_ptz_down"
            if self._sweep_step < self._full_pan_steps + 1:
                self._sweep_step += 1
                return "camera_ptz_left"
            log.info("follow sweep: all phases done")
            return None

        return None

    def _pause_search(self, now: float, reason: str) -> None:
        self._set_state("PAUSED")
        self._pause_until = now + self._sweep_pause_sec
        self._search_moves = 0
        self._recover_moves = 0
        self._sweep_phase = 0
        self._sweep_step = 0
        self._set_error(reason)
        log.info("Soft follow paused %.1fs (%s)", self._sweep_pause_sec, reason)

    def _maybe_issue_move(self, direction: str, now: float, source: str) -> None:
        if not direction:
            return
        if self._suspended:
            return
        if (now - self._last_move_at) < self._move_cooldown_sec:
            return
        self._last_move_at = now
        self._last_move_dir = direction
        self._move_count += 1
        result = self._move_callback(direction)
        self._last_move_result = str(result)[:200]
        lower_result = str(result).strip().lower()
        if lower_result.startswith("kunde inte"):
            self._move_fail_count += 1
            self._set_error(f"move_failed:{result}")
            log.warning("Soft follow move failed (%s): %s -> %s", source, direction, result)
            return
        log.info("follow move(%s): %s -> %s", source, direction, result)

    def _decide_direction(self, x_norm: float, y_norm: float) -> str:
        err_x = float(x_norm) - 0.5
        err_y = float(y_norm) - 0.5
        if abs(err_x) >= self._x_deadzone:
            move_right = err_x > 0
            if self._invert_x:
                move_right = not move_right
            return "camera_ptz_right" if move_right else "camera_ptz_left"
        if self._enable_tilt and abs(err_y) >= self._y_deadzone:
            move_down = err_y > 0
            if self._invert_y:
                move_down = not move_down
            return "camera_ptz_down" if move_down else "camera_ptz_up"
        return ""

    def _detect_person(self, frame_bgr: Any) -> tuple[bool, float | None, float | None]:
        if cv2 is None or self._hog is None or frame_bgr is None:
            return False, None, None
        try:
            fh, fw = frame_bgr.shape[:2]
            if fw <= 0 or fh <= 0:
                return False, None, None
            scale = min(1.0, float(self._max_width) / float(fw))
            if scale < 0.999:
                resized = cv2.resize(frame_bgr, (int(fw * scale), int(fh * scale)))
            else:
                resized = frame_bgr
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            rects, weights = self._hog.detectMultiScale(
                gray,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
            if rects is None or len(rects) == 0:
                return False, None, None
            best_idx = 0
            best_area = -1
            for idx, rect in enumerate(rects):
                _x, _y, w, h = [int(v) for v in rect]
                area = max(1, w * h)
                weight_bonus = 0.0
                if weights is not None and len(weights) > idx:
                    try:
                        weight_bonus = float(weights[idx])
                    except Exception:
                        weight_bonus = 0.0
                area = int(area * max(0.25, (weight_bonus + 0.5)))
                if area > best_area:
                    best_area = area
                    best_idx = idx
            x, y, w, h = [int(v) for v in rects[best_idx]]
            rw, rh = resized.shape[1], resized.shape[0]
            cx = (x + (w * 0.5)) / max(1.0, float(rw))
            cy = (y + (h * 0.5)) / max(1.0, float(rh))
            return True, float(cx), float(cy)
        except Exception:
            return False, None, None

    def _detect_motion_center(
        self,
        frame_bgr: Any,
    ) -> tuple[bool, float | None, float | None, float]:
        if cv2 is None or frame_bgr is None:
            return False, None, None, 0.0
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (9, 9), 0)
            if self._prev_gray is None:
                self._prev_gray = gray
                return False, None, None, 0.0
            delta = cv2.absdiff(self._prev_gray, gray)
            self._prev_gray = gray
            _ret, thresh = cv2.threshold(delta, 20, 255, cv2.THRESH_BINARY)
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours, _hier = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return False, None, None, 0.0
            h, w = gray.shape[:2]
            frame_area = max(1.0, float(h * w))
            best = None
            best_area = 0.0
            for c in contours:
                area = float(cv2.contourArea(c))
                if area > best_area:
                    best_area = area
                    best = c
            if best is None:
                return False, None, None, 0.0
            area_ratio = best_area / frame_area
            if area_ratio < self._motion_min_area_ratio:
                return False, None, None, area_ratio
            m = cv2.moments(best)
            if not m or float(m.get("m00", 0.0)) <= 0.0:
                return False, None, None, area_ratio
            cx = float(m["m10"] / m["m00"]) / max(1.0, float(w))
            cy = float(m["m01"] / m["m00"]) / max(1.0, float(h))
            return True, cx, cy, area_ratio
        except Exception:
            return False, None, None, 0.0
