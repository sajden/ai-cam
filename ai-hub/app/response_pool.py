"""
response_pool.py — Phrase pool definitions and LRU variant selector.

All Swedish phrases are tuned for Microsoft Sofie Neural TTS prosody.
Thread-safe via a single threading.Lock guarding all _pool_lru mutations.
LRU state is persisted to SQLite via db.upsert_pool_usage() on each pick
and seeded from DB on startup via load_lru_from_db().
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from . import db


@dataclass
class PoolContext:
    time_of_day: str          # "morning" | "afternoon" | "evening" | "night"
    recency: bool             # True if last interaction < 10 min ago
    identity_name: str | None
    companion_mode: bool      # False = minimal/direct mode active
    last_action: str | None   # e.g. "training_stop", "spotify_play"


# ---------------------------------------------------------------------------
# Phrase pool definitions
# Each entry: {"key": str, "text": str}
# {name} placeholder is substituted at pick() time if ctx.identity_name is set
# ---------------------------------------------------------------------------

_POOLS: dict[str, list[dict[str, str]]] = {
    "wake_morning": [
        {"key": "wm1", "text": "God morgon! Vad kan jag hjälpa dig med?"},
        {"key": "wm2", "text": "Morgon! Vad gäller det?"},
        {"key": "wm3", "text": "Hej hej, god morgon. Vad behöver du?"},
        {"key": "wm4", "text": "God morgon! Vad önskar du?"},
        {"key": "wm5", "text": "Morgon! Vad kan jag göra för dig?"},
    ],
    "wake_afternoon": [
        {"key": "wa1", "text": "Hej! Vad kan jag göra för dig?"},
        {"key": "wa2", "text": "Här är jag. Vad är det?"},
        {"key": "wa3", "text": "Ja, hej! Vad önskar du?"},
        {"key": "wa4", "text": "Hej! Vad behöver du?"},
        {"key": "wa5", "text": "Hej! Vad kan jag hjälpa dig med?"},
    ],
    "wake_evening": [
        {"key": "we1", "text": "God kväll! Vad kan jag hjälpa till med?"},
        {"key": "we2", "text": "Hej igen. Vad gäller det?"},
        {"key": "we3", "text": "Här är jag. Vad behöver du?"},
        {"key": "we4", "text": "God kväll! Vad önskar du?"},
        {"key": "we5", "text": "Hej! Vad kan jag göra för dig ikväll?"},
    ],
    "wake_continuity": [
        {"key": "wc1", "text": "Ja?"},
        {"key": "wc2", "text": "Vad mer?"},
        {"key": "wc3", "text": "Ja, vad är det?"},
        {"key": "wc4", "text": "Mm, vad gäller det?"},
        {"key": "wc5", "text": "Hör på."},
    ],
    "spotify_play": [
        {"key": "sp1", "text": "Kör igång musiken."},
        {"key": "sp2", "text": "Sätter på musik nu."},
        {"key": "sp3", "text": "Startar musiken."},
    ],
    "spotify_pause": [
        {"key": "spu1", "text": "Pausar musiken."},
        {"key": "spu2", "text": "Okej, tyst nu."},
        {"key": "spu3", "text": "Stannar musiken."},
    ],
    "spotify_next": [
        {"key": "sn1", "text": "Nästa låt."},
        {"key": "sn2", "text": "Hoppar vidare."},
        {"key": "sn3", "text": "Byter låt."},
    ],
    "spotify_prev": [
        {"key": "spv1", "text": "Går tillbaka."},
        {"key": "spv2", "text": "Spelar om igen."},
        {"key": "spv3", "text": "Föregående låt."},
    ],
    "follow_start": [
        {"key": "fs1", "text": "Håller koll på dig."},
        {"key": "fs2", "text": "Följer med dig nu."},
        {"key": "fs3", "text": "Okej, jag ser dig."},
    ],
    "follow_stop": [
        {"key": "fst1", "text": "Slutar följa."},
        {"key": "fst2", "text": "Stannar kameran."},
        {"key": "fst3", "text": "Okej, stannar här."},
    ],
    "training_start_named": [
        {"key": "tsn1", "text": "Kör på, {name}! Jag räknar."},
        {"key": "tsn2", "text": "Okej {name}, jag håller koll. Kör!"},
        {"key": "tsn3", "text": "Startar. Visa vad du går för, {name}!"},
    ],
    "training_stop": [
        {"key": "tst1", "text": "Bra jobbat! Sparar passet."},
        {"key": "tst2", "text": "Klart! Bra kämpat."},
        {"key": "tst3", "text": "Avrundar nu. Bra gjort."},
    ],
    "workout_followup": [
        {"key": "wf1", "text": "Hoppas det kändes bra."},
        {"key": "wf2", "text": "Starkt jobbat."},
        {"key": "wf3", "text": "Imponerande. Bra gjort."},
        {"key": "wf4", "text": "Kom ihåg att dricka vatten."},
        {"key": "wf5", "text": "Det där var riktigt fint."},
        {"key": "wf6", "text": "Du är bra på det här."},
    ],
    "processing_ack": [
        {"key": "pa1", "text": "Ja självklart, ett ögonblick."},
        {"key": "pa2", "text": "Låt mig kolla det."},
        {"key": "pa3", "text": "En sekund, jag letar upp det."},
        {"key": "pa4", "text": "Vänta lite, jag kollar."},
        {"key": "pa5", "text": "Okej, jag tar reda på det."},
    ],
    "error_generic": [
        {"key": "eg1", "text": "Oj, något gick snett. Förlåt."},
        {"key": "eg2", "text": "Hmm, det funkade inte den här gången."},
        {"key": "eg3", "text": "Det gick inte som planerat, förlåt."},
    ],
    "identity_bind": [
        {"key": "ib1", "text": "Tack {name}. Jag känner igen dig nu."},
        {"key": "ib2", "text": "Perfekt, {name}. Nu vet jag vem du är."},
        {"key": "ib3", "text": "Okej {name}, jag har sparat dig. Välkommen!"},
    ],
}

# ---------------------------------------------------------------------------
# In-memory LRU state
# _pool_lru[pool_name] = OrderedDict(variant_key -> last_used_epoch)
# Oldest entry is first (least recently used)
# ---------------------------------------------------------------------------
_pool_lru: dict[str, OrderedDict[str, float]] = {}
_pool_lock = threading.Lock()


def load_lru_from_db() -> None:
    """Seed in-memory LRU from DB on startup. Ordered by used_at ASC (oldest first)."""
    rows = db.load_pool_usage()
    with _pool_lock:
        _pool_lru.clear()
        for row in rows:
            pool_name = str(row["pool_name"])
            variant_key = str(row["variant_key"])
            lru = _pool_lru.setdefault(pool_name, OrderedDict())
            lru[variant_key] = 0.0  # epoch not critical; order is what matters


def pick(pool_name: str, ctx: PoolContext) -> str:
    """
    Select the least-recently-used eligible variant from the named pool.
    Updates in-memory LRU and writes through to SQLite.
    Falls back to global LRU if context filter removes all candidates.
    """
    pool = _POOLS.get(pool_name, [])
    if not pool:
        return ""

    eligible = _filter_eligible(pool, pool_name, ctx)
    if eligible is None:
        return ""  # hard gate (e.g. companion_mode=False blocks workout_followup)
    if not eligible:
        eligible = pool  # fallback for recency/LRU exhaustion

    with _pool_lock:
        lru = _pool_lru.setdefault(pool_name, OrderedDict())
        chosen = _lru_pick(eligible, lru)
        lru.pop(chosen["key"], None)
        lru[chosen["key"]] = time.time()  # move to end (most recently used)
        chosen_key = chosen["key"]

    # Write-through to DB outside lock
    db.upsert_pool_usage(pool_name, chosen_key)

    text = chosen["text"]
    if ctx.identity_name and "{name}" in text:
        text = text.format(name=ctx.identity_name)
    return text


def _filter_eligible(
    pool: list[dict[str, str]],
    pool_name: str,
    ctx: PoolContext,
) -> list[dict[str, str]] | None:
    """
    Return pool entries that pass context filters.
    Returns None for hard gates (caller should return "" immediately).
    Returns [] for soft exhaustion (caller should fallback to full pool).
    """
    if pool_name == "workout_followup" and not ctx.companion_mode:
        return None  # hard gate
    return pool


def _lru_pick(
    eligible: list[dict[str, str]],
    lru: OrderedDict[str, float],
) -> dict[str, str]:
    """
    Pick the eligible variant that appears earliest in the LRU OrderedDict
    (least recently used), or the first variant not yet in the LRU.
    """
    eligible_keys = {v["key"] for v in eligible}
    key_to_variant = {v["key"]: v for v in eligible}

    # Prefer variants never seen (not in LRU)
    for v in eligible:
        if v["key"] not in lru:
            return v

    # All have been used — find the one that appears first in LRU (oldest)
    for k in lru:
        if k in eligible_keys:
            return key_to_variant[k]

    # Shouldn't reach here, but fall back to first eligible
    return eligible[0]
