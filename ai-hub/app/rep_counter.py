from __future__ import annotations

import logging
import re
import time
from typing import Any

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


log = logging.getLogger("aihub.rep_counter")


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _guess_activity(task_goal: str, task_type: str) -> str:
    text = f"{task_goal} {task_type}".lower()
    if re.search(r"\b(pushups?|armhäv|armhav)\b", text):
        return "pushup"
    if re.search(r"\b(squats?|knäböj|knaboj)\b", text):
        return "squat"
    if re.search(r"\b(situps?)\b", text):
        return "situp"
    return "workout"


class SimpleVerticalRepCounter:
    """Very lightweight local rep counter from live video using OpenCV HOG."""

    def __init__(
        self,
        *,
        min_amplitude: float = 0.09,
        min_rep_interval_sec: float = 0.45,
    ) -> None:
        self._min_amplitude = max(0.03, float(min_amplitude))
        self._min_rep_interval_sec = max(0.2, float(min_rep_interval_sec))

        self._hog = None
        if cv2 is not None:
            try:
                hog = cv2.HOGDescriptor()
                hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                self._hog = hog
            except Exception:
                self._hog = None

        self.reset()

    def available(self) -> bool:
        return self._hog is not None and cv2 is not None

    def reset(self) -> None:
        self._rep_count = 0
        self._state = "init"
        self._ema_y: float | None = None
        self._min_y: float | None = None
        self._max_y: float | None = None
        self._last_transition = 0.0
        self._last_rep_at = 0.0
        self._last_tempo_ms: float | None = None
        self._missing_streak = 0

    def process(
        self,
        frame_bgr: Any,
        *,
        task_goal: str = "",
        task_type: str = "",
    ) -> dict[str, Any]:
        activity = _guess_activity(task_goal, task_type)
        if not self.available() or frame_bgr is None:
            return {
                "activity": activity,
                "rep_count": None,
                "form_flags": [],
                "fatigue_score": 0.0,
                "confidence": 0.0,
                "summary_sv": "Lokal CV-analys är inte tillgänglig.",
                "depth_score": None,
                "tempo_ms": None,
            }

        found, y_norm, h_norm, det_conf = self._detect_person(frame_bgr)
        if not found or y_norm is None:
            self._missing_streak += 1
            return {
                "activity": activity,
                "rep_count": None,
                "form_flags": [],
                "fatigue_score": _clamp01(min(1.0, self._missing_streak / 12.0)),
                "confidence": 0.0,
                "summary_sv": "Jag tappar personen i bild.",
                "depth_score": None,
                "tempo_ms": None,
            }

        self._missing_streak = 0
        if self._ema_y is None:
            self._ema_y = y_norm
            self._min_y = y_norm
            self._max_y = y_norm
            return {
                "activity": activity,
                "rep_count": None,
                "form_flags": [],
                "fatigue_score": 0.0,
                "confidence": 0.2,
                "summary_sv": "Kalibrerar rörelse.",
                "depth_score": 0.0,
                "tempo_ms": None,
            }

        alpha = 0.28
        self._ema_y = (1.0 - alpha) * self._ema_y + alpha * y_norm
        assert self._min_y is not None
        assert self._max_y is not None

        # Keep moving range while slowly adapting drift.
        self._min_y = min(self._min_y, self._ema_y)
        self._max_y = max(self._max_y, self._ema_y)
        self._min_y = min(self._ema_y, self._min_y + 0.0012)
        self._max_y = max(self._ema_y, self._max_y - 0.0012)
        amplitude = max(0.0, self._max_y - self._min_y)

        down_threshold = self._min_y + amplitude * 0.72
        up_threshold = self._min_y + amplitude * 0.38

        phase = "mid"
        if self._ema_y >= down_threshold:
            phase = "down"
        elif self._ema_y <= up_threshold:
            phase = "up"

        now = time.monotonic()
        rep_incremented = False
        if self._state == "init" and phase in {"up", "down"}:
            self._state = phase
        elif amplitude >= self._min_amplitude:
            if self._state in {"init", "up"} and phase == "down":
                if (now - self._last_transition) >= self._min_rep_interval_sec * 0.5:
                    self._state = "down"
                    self._last_transition = now
            elif self._state == "down" and phase == "up":
                if (now - self._last_transition) >= self._min_rep_interval_sec:
                    self._state = "up"
                    self._last_transition = now
                    self._rep_count += 1
                    rep_incremented = True
                    if self._last_rep_at > 0:
                        self._last_tempo_ms = max(1.0, (now - self._last_rep_at) * 1000.0)
                    self._last_rep_at = now

        depth_score = _clamp01(0.0 if self._min_amplitude <= 0 else amplitude / (self._min_amplitude * 1.8))
        conf = _clamp01(0.18 + min(0.42, amplitude * 2.1) + min(0.25, det_conf))

        form_flags: list[str] = []
        if amplitude < self._min_amplitude:
            form_flags.append("kort_rörelse")
        if self._last_tempo_ms is not None and self._last_tempo_ms < 450:
            form_flags.append("för_snabb_tempo")
        if self._last_tempo_ms is not None and self._last_tempo_ms > 4200:
            form_flags.append("ojämn_tempo")
        if h_norm < 0.18:
            form_flags.append("person_långt_bort")

        fatigue = 0.0
        if self._last_tempo_ms is not None:
            fatigue = _clamp01((self._last_tempo_ms - 2200.0) / 3500.0)

        summary = (
            f"Rep {self._rep_count}. Fortsätt stabilt."
            if rep_incremented
            else "Fortsätt, jag följer rörelsen."
        )
        if form_flags and not rep_incremented:
            summary = "Justera lite: håll jämn rörelse."

        return {
            "activity": activity,
            "rep_count": self._rep_count if rep_incremented else None,
            "form_flags": form_flags[:4],
            "fatigue_score": round(fatigue, 3),
            "confidence": round(conf, 3),
            "summary_sv": summary,
            "depth_score": round(depth_score, 3),
            "tempo_ms": round(self._last_tempo_ms, 1) if self._last_tempo_ms is not None else None,
        }

    def _detect_person(self, frame_bgr: Any) -> tuple[bool, float | None, float | None, float]:
        assert cv2 is not None
        assert self._hog is not None

        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            rects, weights = self._hog.detectMultiScale(
                gray,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.04,
            )
        except Exception as exc:  # pragma: no cover
            log.debug("HOG detect failed: %s", exc)
            return False, None, None, 0.0

        if rects is None or len(rects) == 0:
            return False, None, None, 0.0

        best_idx = -1
        best_score = -1.0
        best_rect = None
        for idx, rect in enumerate(rects):
            x, y, w, h = [int(v) for v in rect]
            area = max(1, w * h)
            weight = 0.0
            if weights is not None and len(weights) > idx:
                try:
                    weight = float(weights[idx])
                except Exception:
                    weight = 0.0
            score = area * max(0.1, weight + 0.2)
            if score > best_score:
                best_score = score
                best_idx = idx
                best_rect = (x, y, w, h)

        if best_idx < 0 or best_rect is None:
            return False, None, None, 0.0

        fh, fw = frame_bgr.shape[:2]
        x, y, w, h = best_rect
        center_y = y + (h * 0.5)
        y_norm = float(center_y) / max(1.0, float(fh))
        h_norm = float(h) / max(1.0, float(fh))

        det_conf = 0.0
        if weights is not None and len(weights) > best_idx:
            try:
                det_conf = float(weights[best_idx])
            except Exception:
                det_conf = 0.0
        det_conf = _clamp01(det_conf / 2.0)
        return True, y_norm, h_norm, det_conf
