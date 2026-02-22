"""Spotify search client using client credentials flow.

No user OAuth required — this is for searching and playing content only.
Playback is delegated to Home Assistant via media_player.play_media.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
_SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

_token_cache: dict[str, object] = {}
_token_lock = threading.Lock()


def _get_token() -> str | None:
    """Return a valid Bearer token, refreshing if expired or missing."""
    if not _SPOTIFY_CLIENT_ID or not _SPOTIFY_CLIENT_SECRET:
        log.debug("Spotify client credentials not configured")
        return None

    with _token_lock:
        now = time.monotonic()
        cached = _token_cache.get("token")
        expires_at = float(_token_cache.get("expires_at", 0))
        if cached and now < expires_at - 60:
            return str(cached)

        credentials = f"{_SPOTIFY_CLIENT_ID}:{_SPOTIFY_CLIENT_SECRET}"
        encoded = base64.b64encode(credentials.encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            method="POST",
            data=body,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            token = data["access_token"]
            _token_cache["token"] = token
            _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
            log.debug("Spotify token refreshed, expires in %ss", data.get("expires_in"))
            return token
        except Exception as exc:
            log.warning("Spotify token fetch failed: %s", exc)
            return None


_BY_PATTERN = re.compile(
    r"^(.+?)\s+(?:av|by|med|with|feat\.?|ft\.?)\s+(.+)$", re.IGNORECASE
)


def _build_search_query(raw: str) -> str:
    """Convert a natural-language query to an optimised Spotify search string.

    "concrete jungle av bob marley" → 'track:"concrete jungle" artist:"bob marley"'
    "shape of you by ed sheeran"    → 'track:"shape of you" artist:"ed sheeran"'
    "bob marley"                    → "bob marley"
    """
    m = _BY_PATTERN.match(raw.strip())
    if m:
        return f'track:"{m.group(1).strip()}" artist:"{m.group(2).strip()}"'
    return raw.strip()


def search_spotify(query: str) -> tuple[str, str] | None:
    """Search Spotify for a track or artist by text query.

    Returns ``(spotify_uri, human_readable_title)`` or ``None`` on failure.

    Strategy:
    - If all query words appear in the top artist name → play the artist
      (HA will start the artist's top tracks)
    - Otherwise → play the top matching track
    """
    if not query.strip():
        return None

    token = _get_token()
    if not token:
        return None

    search_q = _build_search_query(query)
    log.debug("Spotify search: %r → %r", query, search_q)
    params = urllib.parse.urlencode(
        {"q": search_q, "type": "track,artist", "limit": "3", "market": "SE"}
    )
    req = urllib.request.Request(
        f"https://api.spotify.com/v1/search?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            # Token may have been revoked — clear cache and give up
            _token_cache.clear()
        log.warning("Spotify search HTTP error %s for query %r", exc.code, query)
        return None
    except Exception as exc:
        log.warning("Spotify search failed for query %r: %s", query, exc)
        return None

    artists = body.get("artists", {}).get("items", [])
    tracks = body.get("tracks", {}).get("items", [])

    # Prefer artist if query words all appear in the top artist name
    if artists:
        top_artist = artists[0]
        artist_name_lower = top_artist.get("name", "").lower()
        query_words = query.lower().split()
        if query_words and all(w in artist_name_lower for w in query_words):
            return (top_artist["uri"], top_artist["name"])

    # Fallback: top track
    if tracks:
        track = tracks[0]
        name = track.get("name", "")
        artist_names = ", ".join(a["name"] for a in track.get("artists", []))
        title = f"{name} – {artist_names}" if artist_names else name
        return (track["uri"], title)

    log.info("Spotify search returned no results for %r", query)
    return None
