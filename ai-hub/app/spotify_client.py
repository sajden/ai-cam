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


_SPECIAL_COLLECTIONS: dict[str, tuple[str, str]] = {
    "liked songs": ("spotify:collection:tracks", "Gillade låtar"),
    "liked song": ("spotify:collection:tracks", "Gillade låtar"),
    "gillade låtar": ("spotify:collection:tracks", "Gillade låtar"),
    "gillade": ("spotify:collection:tracks", "Gillade låtar"),
    "mina låtar": ("spotify:collection:tracks", "Gillade låtar"),
    "sparade låtar": ("spotify:collection:tracks", "Gillade låtar"),
    "favoriter": ("spotify:collection:tracks", "Gillade låtar"),
    "mina favoriter": ("spotify:collection:tracks", "Gillade låtar"),
}


def search_spotify(query: str) -> tuple[str, str] | None:
    """Search Spotify for a track or artist by text query.

    Returns ``(spotify_uri, human_readable_title)`` or ``None`` on failure.

    Strategy:
    - Special collections (e.g. Liked Songs) → resolved via hardcoded URI map
    - If all query words appear in the top artist name → play the artist
      (HA will start the artist's top tracks)
    - Otherwise → play the top matching track
    """
    if not query.strip():
        return None

    # Special collections that can't be found via search API
    special = _SPECIAL_COLLECTIONS.get(query.strip().lower())
    if special:
        log.debug("Spotify special collection: %r → %s", query, special[0])
        return special

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


# ---------------------------------------------------------------------------
# Authorization Code Flow (user-scoped token)
# ---------------------------------------------------------------------------
import secrets  # noqa: E402 — stdlib, no extra dependency

_SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
_TOKEN_FILE = "/data/spotify_auth.json"
_SPOTIFY_SCOPES = (
    "user-library-read playlist-read-private playlist-read-collaborative "
    "user-modify-playback-state user-read-playback-state"
)
_user_token_cache: dict[str, object] = {}
_user_token_lock = threading.Lock()


def _load_token_file() -> dict:
    try:
        with open(_TOKEN_FILE, "r", encoding="utf-8") as fh:
            return json.loads(fh.read())
    except Exception:
        return {}


def _save_token_file(data: dict) -> None:
    try:
        with open(_TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data))
    except Exception as exc:
        log.warning("Could not save Spotify token file: %s", exc)


def build_auth_url() -> str:
    """Generate a Spotify authorization URL (Authorization Code flow).

    A CSRF state token is persisted to the token file so the callback can
    verify it.  Returns the full URL the user must visit in a browser.
    """
    state = secrets.token_urlsafe(16)
    data = _load_token_file()
    data["state"] = state
    _save_token_file(data)

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": _SPOTIFY_CLIENT_ID,
            "scope": _SPOTIFY_SCOPES,
            "redirect_uri": _SPOTIFY_REDIRECT_URI,
            "state": state,
        }
    )
    return f"https://accounts.spotify.com/authorize?{params}"


def exchange_code(code: str, state: str) -> bool:
    """Exchange an authorization code for access + refresh tokens.

    Verifies the CSRF state, POSTs to Spotify's token endpoint, persists
    the result, and updates the in-memory cache.  Returns True on success.
    """
    saved = _load_token_file()
    if not saved.get("state") or saved["state"] != state:
        log.warning("Spotify OAuth state mismatch — possible CSRF")
        return False

    credentials = f"{_SPOTIFY_CLIENT_ID}:{_SPOTIFY_CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _SPOTIFY_REDIRECT_URI,
        }
    ).encode()
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
            token_data = json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("Spotify code exchange failed: %s", exc)
        return False

    now = time.time()
    payload = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": now + int(token_data.get("expires_in", 3600)),
    }
    _save_token_file(payload)

    with _user_token_lock:
        _user_token_cache.update(payload)

    log.info("Spotify user token obtained successfully")
    return True


def _get_user_token() -> str | None:
    """Return a valid user-scoped Bearer token, refreshing if expired."""
    with _user_token_lock:
        now = time.time()
        token = _user_token_cache.get("access_token")
        expires_at = float(_user_token_cache.get("expires_at", 0))

        if not token:
            # Try loading from disk
            data = _load_token_file()
            if data.get("access_token"):
                _user_token_cache.update(data)
                token = data["access_token"]
                expires_at = float(data.get("expires_at", 0))

        if token and now < expires_at - 60:
            return str(token)

        # Need refresh
        refresh_token = _user_token_cache.get("refresh_token") or _load_token_file().get("refresh_token")
        if not refresh_token:
            return None

        credentials = f"{_SPOTIFY_CLIENT_ID}:{_SPOTIFY_CLIENT_SECRET}"
        encoded = base64.b64encode(credentials.encode()).decode()
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
            }
        ).encode()
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
        except Exception as exc:
            log.warning("Spotify token refresh failed: %s", exc)
            return None

        new_token = data["access_token"]
        now = time.time()
        new_expires_at = now + int(data.get("expires_in", 3600))
        new_refresh = data.get("refresh_token", str(refresh_token))

        payload = {
            "access_token": new_token,
            "refresh_token": new_refresh,
            "expires_at": new_expires_at,
        }
        _user_token_cache.update(payload)
        _save_token_file(payload)
        log.debug("Spotify user token refreshed")
        return new_token


def get_user_playlists() -> list[dict]:
    """Return the current user's playlists as [{id, name, uri}]."""
    token = _get_user_token()
    if not token:
        return []

    results: list[dict] = []
    url = "https://api.spotify.com/v1/me/playlists?limit=50"
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode())
        except Exception as exc:
            log.warning("get_user_playlists failed: %s", exc)
            break
        for item in body.get("items", []):
            if item:
                results.append({"id": item["id"], "name": item["name"], "uri": item["uri"]})
        url = body.get("next")  # pagination

    return results


def find_user_playlist(query: str) -> tuple[str, str] | None:
    """Find a user playlist by exact or substring match against ``query``.

    Returns ``(uri, name)`` or ``None``.
    """
    playlists = get_user_playlists()
    q = query.strip().lower()

    # Exact match first
    for pl in playlists:
        if pl["name"].lower() == q:
            return (pl["uri"], pl["name"])

    # Substring match
    for pl in playlists:
        if q in pl["name"].lower():
            return (pl["uri"], pl["name"])

    return None


def get_active_device_id() -> str | None:
    """Return the id of the currently active Spotify playback device, or None."""
    token = _get_user_token()
    if not token:
        return None

    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("get_active_device_id failed: %s", exc)
        return None

    devices = body.get("devices", [])
    # Prefer the currently active device; fall back to the first available one.
    for device in devices:
        if device.get("is_active"):
            return device["id"]
    for device in devices:
        if not device.get("is_restricted"):
            return device["id"]
    return None


def _get_liked_song_uris(token: str, limit: int = 50) -> list[str]:
    """Fetch the user's most recently liked tracks and return their Spotify URIs."""
    params = urllib.parse.urlencode({"limit": limit, "offset": 0})
    req = urllib.request.Request(
        f"https://api.spotify.com/v1/me/tracks?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("_get_liked_song_uris failed: %s", exc)
        return []
    return [item["track"]["uri"] for item in body.get("items", []) if item.get("track")]


def play_liked_songs(device_id: str | None = None) -> tuple[bool, str]:
    """Start playback of the user's Liked Songs (most recent first).

    Fetches up to 50 liked tracks and queues them via the play endpoint.
    Returns ``(True, "ok")`` on success or ``(False, reason)`` on failure.
    """
    token = _get_user_token()
    if not token:
        return (False, "no_user_token")

    active_device = device_id or get_active_device_id()
    if not active_device:
        return (False, "no_active_device")

    uris = _get_liked_song_uris(token)
    if not uris:
        return (False, "no_liked_songs")

    body = json.dumps({"uris": uris}).encode()
    params = urllib.parse.urlencode({"device_id": active_device})
    req = urllib.request.Request(
        f"https://api.spotify.com/v1/me/player/play?{params}",
        method="PUT",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return (False, "premium_required")
        if exc.code == 404:
            return (False, "no_active_device")
        log.warning("play_liked_songs HTTP %s", exc.code)
        return (False, f"http_{exc.code}")
    except Exception as exc:
        log.warning("play_liked_songs failed: %s", exc)
        return (False, str(exc))

    if status_code in (200, 204):
        log.info("play_liked_songs: started %d tracks on device %s", len(uris), active_device)
        return (True, "ok")
    return (False, f"unexpected_status_{status_code}")


def get_device_id_by_name(name: str) -> str | None:
    """Return the device_id of a Spotify Connect device matching *name* (case-insensitive)."""
    token = _get_user_token()
    if not token:
        return None

    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("get_device_id_by_name failed: %s", exc)
        return None

    name_lower = name.lower()
    for device in body.get("devices", []):
        if device.get("name", "").lower() == name_lower:
            return device["id"]
    log.info("Device %r not found. Available: %s", name, [d.get("name") for d in body.get("devices", [])])
    return None


def play_context_uri(context_uri: str, device_name: str | None = None) -> tuple[bool, str]:
    """Play a Spotify context URI (playlist/album/artist) on a named device.

    Falls back to the active device if *device_name* is not found.
    Returns (True, "ok") on success or (False, reason) on failure.
    """
    token = _get_user_token()
    if not token:
        return (False, "no_user_token")

    if device_name:
        device_id = get_device_id_by_name(device_name) or get_active_device_id()
    else:
        device_id = get_active_device_id()

    if not device_id:
        return (False, "no_active_device")

    body = json.dumps({"context_uri": context_uri}).encode()
    params = urllib.parse.urlencode({"device_id": device_id})
    req = urllib.request.Request(
        f"https://api.spotify.com/v1/me/player/play?{params}",
        method="PUT",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return (False, "premium_required")
        if exc.code == 404:
            return (False, "no_active_device")
        log.warning("play_context_uri HTTP %s", exc.code)
        return (False, f"http_{exc.code}")
    except Exception as exc:
        log.warning("play_context_uri failed: %s", exc)
        return (False, str(exc))

    if status_code in (200, 204):
        log.info("play_context_uri: %s on %s", context_uri, device_id)
        return (True, "ok")
    return (False, f"unexpected_status_{status_code}")


def has_user_auth() -> bool:
    """Return True if a user-scoped token is available (in cache or on disk)."""
    token = _get_user_token()
    return token is not None


def is_liked_songs_uri(uri: str) -> bool:
    """Return True if *uri* refers to the Liked Songs collection."""
    return uri == "spotify:collection:tracks"
