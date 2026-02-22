from __future__ import annotations

import os


ROUTING_PROFILE = os.getenv("AIHUB_ROUTING_PROFILE", "codex_first").strip().lower()
ALLOW_CAMERA_TEXT_TO_CODEX = (
    os.getenv("AIHUB_ALLOW_CAMERA_TEXT_TO_CODEX", "0").strip() == "1"
)


def should_use_codex(
    text: str,
    allow_codex: bool,
    contains_camera_derived_text: bool,
) -> bool:
    if not allow_codex:
        return False

    lowered = text.lower()
    explicit = "hey codex" in lowered or "hej codex" in lowered

    if contains_camera_derived_text and not ALLOW_CAMERA_TEXT_TO_CODEX and not explicit:
        return False

    if explicit:
        return True

    if ROUTING_PROFILE == "codex_first":
        return True

    return False


def evaluate_candidate_egress(
    intent: str,
    candidate_egress: str,
    contains_camera_derived_text: bool,
) -> tuple[bool, str, str]:
    if candidate_egress not in {"none", "text-only"}:
        return False, "none", "invalid_egress_value"

    if contains_camera_derived_text and not ALLOW_CAMERA_TEXT_TO_CODEX:
        return False, "none", "camera_text_blocked_by_policy"

    return True, candidate_egress, "allowed"
