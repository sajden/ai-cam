"""Post-conversation fact extraction and follow-up scheduling."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

from . import db

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Analysera följande konversation och extrahera viktiga fakta om personen.
Returnera ett JSON-array med objekt i formatet:
[{{"fact": "kort faktapåstående på svenska", "category": "health|fitness|schedule|preference|personal|general", "follow_up_date": "YYYY-MM-DD eller null"}}]

Regler:
- Max 10 fakta per konversation
- Bara konkreta, minnesvärda fakta (inte tom konversation)
- follow_up_date: sätt ett datum om personen nämnde något med ett tidsfönster (t.ex. "ska träffa läkaren på torsdag"), annars null
- Returnera bara JSON, ingen annan text

Konversation:
{turns}"""


async def extract_and_store_facts(
    conversation_id: str,
    person_name: str,
) -> None:
    """
    Extract facts from the last N turns of a conversation and store in memory_facts.

    Runs async; called at conversation close. Failures are logged but never raised.
    """
    if not os.getenv("AIHUB_MEMORY_EXTRACTION_ENABLED", "0").strip() == "1":
        return
    if not person_name or not conversation_id:
        return

    try:
        turns = db.get_memory_context(conversation_id, k=20)
        if not turns:
            return

        turn_lines = "\n".join(
            f"{t['role'].upper()}: {t['text']}"
            for t in turns
            if t.get("text", "").strip()
        )
        if len(turn_lines) < 30:
            return

        prompt = _EXTRACTION_PROMPT.format(turns=turn_lines)

        from .codex_client import ask_codex
        ok, raw_text, _ = ask_codex(prompt, conversation_id + "_mem_extract", [])
        if not ok or not raw_text:
            logger.warning("memory extraction: Codex returned no response")
            return

        # Parse JSON array from response
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not match:
            logger.warning("memory extraction: no JSON array in response: %r", raw_text[:200])
            return

        facts = json.loads(match.group(0))
        if not isinstance(facts, list):
            return

        for item in facts[:10]:
            if not isinstance(item, dict) or not item.get("fact"):
                continue
            fact_text = str(item["fact"]).strip()
            category = str(item.get("category", "general")).strip()
            follow_up_date = item.get("follow_up_date")
            if follow_up_date and str(follow_up_date).lower() in ("null", "none", ""):
                follow_up_date = None

            fact_id = db.insert_fact(
                person_name=person_name,
                fact_text=fact_text,
                category=category,
                source_conv_id=conversation_id,
                follow_up_date=str(follow_up_date) if follow_up_date else None,
            )
            logger.info("Stored fact for %s (id=%d): %s", person_name, fact_id, fact_text[:60])

            # Schedule follow-up if a date is set
            if follow_up_date:
                _schedule_followup_for_fact(fact_id, person_name, fact_text, str(follow_up_date))

    except Exception as exc:
        logger.warning("memory extraction failed for %s / %s: %s", person_name, conversation_id, exc)


def _schedule_followup_for_fact(
    fact_id: int,
    person_name: str,
    fact_text: str,
    date_str: str,
) -> None:
    """Schedule a threading.Timer to fire a proactive follow-up on the given date."""
    try:
        target_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delay_sec = (target_dt - now).total_seconds()
        if delay_sec <= 0:
            return

        from .actions import speak_to_camera

        def _fire() -> None:
            try:
                active_person = db.get_mode_state().get("active_person_name", "")
                if active_person and active_person.lower() != person_name.lower():
                    logger.info("Skipping follow-up: different person home (%s)", active_person)
                    return
                privacy = db.get_mode_state().get("privacy_mode", "false")
                if privacy == "true":
                    logger.info("Skipping follow-up: privacy mode active")
                    return
                follow_up_text = f"Förresten, {fact_text.lower()[:80]} — hur gick det med det?"
                speak_to_camera(follow_up_text, "memory_followup", event="reply")
                db.mark_followed_up(fact_id)
                logger.info("Proactive follow-up fired for fact_id=%d", fact_id)
            except Exception as exc:
                logger.warning("Proactive follow-up failed: %s", exc)

        timer = threading.Timer(delay_sec, _fire)
        timer.daemon = True
        timer.start()
        logger.info(
            "Scheduled follow-up in %.0fs for fact_id=%d (%s)",
            delay_sec, fact_id, fact_text[:40],
        )
    except Exception as exc:
        logger.warning("Failed to schedule follow-up for fact_id=%d: %s", fact_id, exc)
