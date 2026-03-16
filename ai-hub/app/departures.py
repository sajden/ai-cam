"""SL departure board — proxy + HTML page for Chromecast TV display."""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
import threading
import urllib.request
import zipfile
from typing import Any

TRAFIKLAB_REALTIME_KEY = os.getenv("TRAFIKLAB_REALTIME_KEY", "").strip()
TRAFIKLAB_GTFS_REALTIME_KEY = os.getenv("TRAFIKLAB_GTFS_REALTIME_KEY", "").strip()
# Separate key for GTFS Regional (static) API — needed for trip→line mapping
TRAFIKLAB_GTFS_STATIC_KEY = os.getenv("TRAFIKLAB_GTFS_STATIC_KEY", "").strip()

# Chromecast host for direct casting (no HA Cast / HTTPS required)
CHROMECAST_HOST = os.getenv("CHROMECAST_HOST", "192.168.50.213").strip()
# URL that the Chromecast will load — must be reachable from the TV's network
DEPARTURE_BOARD_CAST_URL = os.getenv(
    "DEPARTURE_BOARD_CAST_URL", "http://192.168.50.215:8080/departures"
).strip()

# ── Hållplatser ───────────────────────────────────────────────────────────────
# Lista med (site_id, visningsnamn, lat, lon)
SL_STOPS = [
    (3652, "Rånövägen",  59.3331, 17.9247),
    (3650, "Nockeby",    59.3297, 17.9167),
]

# Används för kartan (första hållplatsen = primär)
SL_SITE_ID  = SL_STOPS[0][0]
SL_SITE_LAT = SL_STOPS[0][2]
SL_SITE_LON = SL_STOPS[0][3]

# Destination (för märkning på kartan)
DEST_NAME   = "Brommaplan"
DEST_LAT    = 59.3383
DEST_LON    = 17.9379

# Filtrera avgångstavlan — bara mot dessa destinationer (lowercase, delsträng)
DEST_FILTER = ["brommaplan"]

# ── Avgångsfilter ──────────────────────────────────────────────────────────────
# Linjer som BARA går från Nockeby (inte via Rånövägen) — visas som backup
NOCKEBY_ONLY_LINES = {"176", "176X", "177", "177E"}
# Slutdestinationer för Nockeby-linjer som kör BORT från Brommaplan — filtrera bort
NOCKEBY_WRONG_TERMINI = {"skärvik", "stenhamra", "solbacka"}

# ── Störningsfilter ────────────────────────────────────────────────────────────
RELEVANT_LINES = {
    "127", "176", "177",
    "301", "302", "303", "304", "305",
    "309", "311", "316", "317", "318", "323", "396",
    "19",
}
# Störningar med dessa riktningar filtreras bort (bussar som kör bort från Brommaplan)
WRONG_DIRECTIONS = {
    "mot mörby", "mot solbacka", "mot skärvik",
    "mot hagsätra", "mot farsta", "mot gullmarsplan",
}

SL_DEPARTURES_URL = "https://transport.integration.sl.se/v1/sites/{site_id}/departures"
GTFS_STATIC_URL = (
    "https://opendata.samtrafiken.se/gtfs/sl/sl.zip"
    f"?key={TRAFIKLAB_GTFS_STATIC_KEY}"
)

# In-memory cache: trip_id → route short name (line number)
_trip_to_line: dict[str, str] = {}
_gtfs_lock = threading.Lock()


def _load_gtfs_trip_map() -> None:
    """Download SL GTFS static zip and build trip_id → line number map."""
    global _trip_to_line
    if not TRAFIKLAB_GTFS_STATIC_KEY:
        return
    try:
        req = urllib.request.Request(
            GTFS_STATIC_URL, headers={"Accept-Encoding": "gzip"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            # Build route_id → short_name from routes.txt
            route_name: dict[str, str] = {}
            with zf.open("routes.txt") as f:
                for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                    route_name[row["route_id"]] = row.get("route_short_name", "")
            # Build trip_id → route_id from trips.txt
            mapping: dict[str, str] = {}
            with zf.open("trips.txt") as f:
                for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                    name = route_name.get(row["route_id"], "")
                    if name:
                        mapping[row["trip_id"]] = name
        with _gtfs_lock:
            _trip_to_line = mapping
    except Exception:
        pass


def _ensure_gtfs_loaded() -> None:
    """Load GTFS trip map in background if not yet loaded."""
    with _gtfs_lock:
        loaded = bool(_trip_to_line)
    if not loaded:
        threading.Thread(target=_load_gtfs_trip_map, daemon=True).start()

# ── Karta ─────────────────────────────────────────────────────────────────────
MAP_CENTER_LAT  = 59.3197   # Kartans mittpunkt lat
MAP_CENTER_LON  = 17.8821   # Kartans mittpunkt lon
MAP_ZOOM        = 13        # Zoom-nivå

# ── Fordon (GTFS-RT) ──────────────────────────────────────────────────────────
# Sökradius i grader från hållplatsen (~0.015° ≈ 1 km)
VEHICLE_RADIUS  = 0.08      # ~5 km — täcker inkommande bussar på rutten

# Filtrera på bäring (riktning) — visa bara fordon som kör MOT Brommaplan
# Brommaplan är öster/nordöst om de flesta inkommande hållplatser ⇒ bäring ~20–160°
# Sätt till None för att visa alla fordon inom radien
VEHICLE_BEARING_MIN = 20
VEHICLE_BEARING_MAX = 160

# ─────────────────────────────────────────────────────────────────────────────

GTFS_RT_VEHICLES_URL = (
    "https://opendata.samtrafiken.se/gtfs-rt/sl/VehiclePositions.pb"
    f"?key={TRAFIKLAB_GTFS_REALTIME_KEY}"
)


def fetch_departures() -> dict[str, Any]:
    """Fetch departures from all configured stops.

    Rånövägen (first stop): show all departures.
    Nockeby (subsequent stops): only show NOCKEBY_ONLY_LINES — lines that
    don't serve Rånövägen — so duplicates are suppressed.
    """
    all_deps: list[dict[str, Any]] = []
    for idx, (site_id, stop_name, _, _) in enumerate(SL_STOPS):
        is_primary = idx == 0
        try:
            url = SL_DEPARTURES_URL.format(site_id=site_id)
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            for dep in data.get("departures", []):
                dest_lower = (dep.get("destination") or "").lower()
                if is_primary:
                    # Primary stop: only show departures toward Brommaplan
                    if not any(f in dest_lower for f in DEST_FILTER):
                        continue
                else:
                    # Secondary stop: only lines unique to this stop
                    desig = (dep.get("line") or {}).get("designation", "").upper()
                    if desig not in NOCKEBY_ONLY_LINES:
                        continue
                    # Skip wrong-direction termini (away from Brommaplan)
                    if any(t in dest_lower for t in NOCKEBY_WRONG_TERMINI):
                        continue
                dep["_stop"] = stop_name
                all_deps.append(dep)
        except Exception:
            pass
    # Sort by expected departure time
    def sort_key(d: dict) -> str:
        return d.get("expected") or d.get("scheduled") or ""
    all_deps.sort(key=sort_key)
    return {"departures": all_deps}


def fetch_vehicles() -> list[dict[str, Any]]:  # noqa: C901
    """Fetch nearby vehicle positions from GTFS-RT (protobuf)."""
    _ensure_gtfs_loaded()
    if not TRAFIKLAB_GTFS_REALTIME_KEY:
        return []
    try:
        from google.transit import gtfs_realtime_pb2  # type: ignore
    except ImportError:
        return []
    try:
        req = urllib.request.Request(
            GTFS_RT_VEHICLES_URL,
            headers={"Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(raw)

        vehicles = []
        for entity in feed.entity:
            v = entity.vehicle
            pos = v.position
            if not pos.latitude:
                continue
            dlat = pos.latitude - SL_SITE_LAT
            dlon = pos.longitude - SL_SITE_LON
            dist = (dlat ** 2 + dlon ** 2) ** 0.5
            if dist > VEHICLE_RADIUS:
                continue
            bearing = pos.bearing
            if (VEHICLE_BEARING_MIN is not None and VEHICLE_BEARING_MAX is not None
                    and not (VEHICLE_BEARING_MIN <= bearing <= VEHICLE_BEARING_MAX)):
                continue
            trip_id = v.trip.trip_id
            with _gtfs_lock:
                line = _trip_to_line.get(trip_id, "")
            vehicles.append({
                "id": entity.id,
                "lat": round(pos.latitude, 6),
                "lon": round(pos.longitude, 6),
                "bearing": round(bearing),
                "line": line,
            })
        return vehicles
    except Exception:
        return []


def fetch_disruptions() -> list[dict[str, Any]]:
    """Fetch active SL traffic disruptions (no key needed)."""
    try:
        url = "https://deviations.integration.sl.se/v1/messages?transport_authority=1&future=false"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        # Keywords that indicate non-acute disruptions (infrastructure, long-running)
        IGNORE_KEYWORDS = [
            # Physical infrastructure
            "hiss", "utgång", "utgången", "trappa", "trappor",
            "dörr", "ingång", "passage", "toalett", "wc",
            # Long-running / planned work — not acute delays
            "sprängning", "sprängningsarbete", "hastighetsbegränsning",
            "tidtabellen justeras", "avgår ca", "tills vidare",
            "anpassad tidtabell", "tidtabellsjustering",
            "planerat arbete", "planerade arbeten",
        ]

        result = []
        for d in data:
            variants = d.get("message_variants", [])
            sv = next((v for v in variants if v.get("language") == "sv"), variants[0] if variants else None)
            if not sv:
                continue
            header = sv.get("header", "")
            details = sv.get("details", "")
            combined = (header + " " + details).lower()

            # Skip infrastructure-only / long-running disruptions
            if any(kw in combined for kw in IGNORE_KEYWORDS):
                continue

            # Skip wrong-direction disruptions (buses heading away from Brommaplan)
            if any(wd in combined for wd in WRONG_DIRECTIONS):
                continue

            scope = d.get("scope", {})
            lines = [str(l["designation"]) for l in scope.get("lines", [])]

            # Skip if none of the affected lines are relevant to us
            if lines and not any(l in RELEVANT_LINES for l in lines):
                continue

            result.append({
                "header": header,
                "details": details,
                "scope": sv.get("scope_alias", ", ".join(lines)),
                "importance": d.get("priority", {}).get("importance_level", 5),
            })

        result.sort(key=lambda x: x["importance"])
        return result
    except Exception:
        return []


def cast_departure_board() -> dict[str, str]:
    """Cast the departure board directly to the Chromecast via pychromecast."""
    try:
        import pychromecast  # type: ignore
        from pychromecast.controllers.dashcast import DashCastController  # type: ignore

        import time as _time

        cast = pychromecast.get_chromecast_from_host(
            (CHROMECAST_HOST, 8009, None, None, "Badrum")
        )
        cast.wait(timeout=10)

        # Kill any running app so DashCast gets a clean start
        cast.quit_app()
        _time.sleep(2)

        d = DashCastController()
        cast.register_handler(d)
        url = f"{DEPARTURE_BOARD_CAST_URL}?t={int(_time.time())}"
        d.load_url(url, force=True)
        return {"status": "ok", "url": DEPARTURE_BOARD_CAST_URL, "host": CHROMECAST_HOST}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def stop_cast() -> dict[str, str]:
    """Stop whatever is playing on the Chromecast."""
    try:
        import pychromecast  # type: ignore
        cast = pychromecast.get_chromecast_from_host(
            (CHROMECAST_HOST, 8009, None, None, "Badrum")
        )
        cast.wait(timeout=10)
        cast.quit_app()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


DEPARTURE_BOARD_HTML = r"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rånövägen avgångar</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --bg: #06071a;
    --surface: #0e1030;
    --surface2: #161840;
    --accent: #3d7eff;
    --text: #f0f2ff;
    --muted: #6b7299;
    --green: #2ecc71;
    --yellow: #f1c40f;
    --red: #e74c3c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    height: 100%;
    overflow: hidden;
  }
  .layout {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }

  /* ── Header ── */
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 22px 44px 16px;
    border-bottom: 1px solid #1e2350;
    flex-shrink: 0;
  }
  .header-left h1 { font-size: 1.8rem; font-weight: 700; letter-spacing: -0.5px; }
  .header-left .subtitle { font-size: 0.9rem; color: var(--muted); margin-top: 3px; }
  .clock { font-size: 3.4rem; font-weight: 200; letter-spacing: 2px; font-variant-numeric: tabular-nums; }
  .date { font-size: 0.85rem; color: var(--muted); text-align: right; margin-top: 2px; }

  /* ── Main content ── */
  .content {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* ── Table pane ── */
  .table-pane {
    flex: 0 0 58%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 16px 0 0 44px;
  }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    padding: 0 14px 10px;
    text-align: left;
  }
  thead th:last-child { text-align: right; }
  tbody tr { border-top: 1px solid #1a1e45; }
  tbody tr.dep-now { background: var(--surface2); }
  td { padding: 9px 12px; font-size: 1.05rem; }
  .badge {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 44px; height: 28px; border-radius: 6px;
    font-weight: 700; font-size: 0.9rem; background: var(--accent); color: #fff; padding: 0 8px;
  }
  .destination { font-weight: 400; }
  .departs { font-size: 1.1rem; font-weight: 300; font-variant-numeric: tabular-nums; }
  .countdown { font-size: 0.8rem; color: var(--muted); text-align: right; margin-top: 1px; }
  .countdown.soon { color: var(--yellow); font-weight: 600; }
  .countdown.dep-now  { color: var(--green);  font-weight: 700; }
  .time-col { text-align: right; }
  .error-msg { text-align: center; color: var(--red); padding: 40px; font-size: 1.1rem; }

  /* ── Map pane ── */
  .map-pane {
    flex: 1;
    position: relative;
    border-left: 1px solid #1e2350;
    overflow: hidden;
  }
  #map {
    position: absolute;
    inset: 0;
    filter: brightness(0.85) saturate(0.7);
  }
  /* Dark map tiles via CSS */
  .leaflet-tile { filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6); }

  /* ── Störningar ── */
  .disruptions {
    border-top: 2px solid #2a1f00;
    background: #120d00;
    padding: 10px 44px 12px;
    flex-shrink: 0;
  }
  .disruptions-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--yellow);
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .disruption-ticker {
    display: flex;
    flex-direction: column;
    gap: 5px;
    overflow: hidden;
    max-height: 110px;
  }
  .disruption-item {
    font-size: 0.9rem;
    color: #ccc;
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  .disruption-item .scope {
    color: var(--yellow);
    font-weight: 700;
    font-size: 0.85rem;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .disruption-item .text { overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .disruption-item.high .scope { color: var(--red); }
  .disruption-item.high .text  { color: #ff9999; }

  /* ── Footer ── */
  footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 44px 12px;
    font-size: 0.75rem;
    color: var(--muted);
    border-top: 1px solid #1e2350;
    flex-shrink: 0;
  }
  .pulse {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; background: var(--green); margin-right: 5px;
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
</style>
</head>
<body>
<div class="layout">

  <header>
    <div class="header-left">
      <h1>Rånövägen &rarr; Brommaplan</h1>
      <div class="subtitle">Nästa avgångar i realtid</div>
    </div>
    <div>
      <div class="clock" id="clock">--:--</div>
      <div class="date" id="date"></div>
    </div>
  </header>

  <div class="content">
    <div class="table-pane">
      <table>
        <thead>
          <tr>
            <th>Linje</th>
            <th>Hållplats</th>
            <th>Mot</th>
            <th class="time-col">Avgår</th>
          </tr>
        </thead>
        <tbody id="tbody">
          <tr><td colspan="4" class="error-msg">Hämtar avgångar…</td></tr>
        </tbody>
      </table>
    </div>

    <div class="map-pane">
      <div id="map"></div>
    </div>
  </div>

  <div class="disruptions">
    <div class="disruptions-label" id="disruptions-label"><i class="fa-solid fa-triangle-exclamation"></i> &nbsp;Störningar</div>
    <div class="disruption-ticker" id="disruptions">Hämtar störningar…</div>
  </div>

  <footer>
    <div><span class="pulse"></span><span id="status">Uppdaterar…</span></div>
    <div>SL Realtid &middot; Rånövägen</div>
  </footer>

</div>

<script>
const STOP_LAT = 59.3331, STOP_LON = 17.9247;
const BROMMAPLAN_LAT = 59.3383, BROMMAPLAN_LON = 17.9379;
const DAYS   = ['Sön','Mån','Tis','Ons','Tor','Fre','Lör'];
const MONTHS = ['jan','feb','mar','apr','maj','jun','jul','aug','sep','okt','nov','dec'];
const LINE_COLORS = {
  '127':'#1e88e5','176':'#00897b','179':'#00897b',
  '301':'#8e24aa','323':'#8e24aa','307':'#43a047',
};
function lineColor(n) { return LINE_COLORS[String(n)] || '#3d7eff'; }
function pad(n) { return String(n).padStart(2,'0'); }

function updateClock() {
  const n = new Date();
  document.getElementById('clock').textContent = pad(n.getHours())+':'+pad(n.getMinutes());
  document.getElementById('date').textContent = DAYS[n.getDay()]+' '+n.getDate()+' '+MONTHS[n.getMonth()];
}

function minutesUntil(iso) {
  if (!iso) return null;
  return Math.round((new Date(iso) - Date.now()) / 60000);
}

function makeCountdown(mins) {
  const el = document.createElement('div');
  el.className = 'countdown';
  if (mins === null) return el;
  if (mins <= 0)      { el.textContent = 'Nu';      el.classList.add('dep-now'); }
  else if (mins <= 2) { el.textContent = mins+' min'; el.classList.add('soon'); }
  else if (mins > 60) { el.textContent = Math.floor(mins/60)+'h '+(mins%60)+'min'; }
  else                { el.textContent = mins+' min'; }
  return el;
}

/* ── Leaflet map ── */
const map = L.map('map', { zoomControl: false, attributionControl: false })
              .setView([59.3197, 17.8821], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

// Rånövägen stop marker
const stopIcon = L.divIcon({
  html: '<div style="width:14px;height:14px;border-radius:50%;background:#3d7eff;border:3px solid #fff;box-shadow:0 0 6px #3d7eff99"></div>',
  className: '', iconAnchor: [7,7]
});
L.marker([STOP_LAT, STOP_LON], {icon: stopIcon})
 .bindTooltip('Rånövägen', {permanent:true, direction:'right'})
 .addTo(map);

// Brommaplan destination marker
const brommaIcon = L.divIcon({
  html: '<div style="width:14px;height:14px;border-radius:50%;background:#2ecc71;border:3px solid #fff;box-shadow:0 0 6px #2ecc7199"></div>',
  className: '', iconAnchor: [7,7]
});
L.marker([BROMMAPLAN_LAT, BROMMAPLAN_LON], {icon: brommaIcon})
 .bindTooltip('Brommaplan', {permanent:true, direction:'left'})
 .addTo(map);

// Bus markers layer
let busMarkers = [];

function updateBuses(vehicles) {
  busMarkers.forEach(m => map.removeLayer(m));
  busMarkers = [];
  vehicles.forEach(v => {
    const bearing = v.bearing || 0;
    const line = v.line || '';
    const icon = L.divIcon({
      html: `<div style="
          display:flex;flex-direction:column;align-items:center;
          transform:rotate(${bearing}deg);
          filter:drop-shadow(0 2px 4px rgba(0,0,0,0.6))">
        <i class="fa-solid fa-bus" style="
          font-size:22px;color:#f1c40f;"></i>
        ${line ? `<span style="
          margin-top:1px;font-size:9px;font-weight:700;
          background:#f1c40f;color:#000;border-radius:3px;
          padding:0 3px;line-height:14px;
          transform:rotate(-${bearing}deg)">${line}</span>` : ''}
      </div>`,
      className: '', iconAnchor: [11, 11]
    });
    const m = L.marker([v.lat, v.lon], {icon}).addTo(map);
    busMarkers.push(m);
  });
}

/* ── Departures ── */
async function fetchDepartures() {
  try {
    const resp = await fetch('/departures/api');
    if (!resp.ok) throw new Error(resp.status);
    const data = await resp.json();
    const deps = (data.departures || []).slice(0, 9);
    const tbody = document.getElementById('tbody');
    if (!deps.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="error-msg">Inga avgångar mot Brommaplan just nu</td></tr>';
      return;
    }
    tbody.innerHTML = '';
    deps.forEach(dep => {
      const line   = dep.line || {};
      const desig  = line.designation || '?';
      const dest   = dep.destination || '';
      const exp    = dep.expected || dep.scheduled;
      const disp   = dep.display || (exp ? pad(new Date(exp).getHours())+':'+pad(new Date(exp).getMinutes()) : '');
      const mins   = minutesUntil(exp);
      const tr     = document.createElement('tr');
      if (mins !== null && mins <= 0) tr.classList.add('dep-now');

      const tdB = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.style.background = lineColor(desig);
      badge.textContent = desig;
      tdB.appendChild(badge);

      const tdS = document.createElement('td');
      tdS.style.cssText = 'font-size:0.85rem;color:var(--muted)';
      tdS.textContent = dep._stop || '';

      const tdD = document.createElement('td');
      tdD.className = 'destination';
      tdD.textContent = dest;

      const tdT = document.createElement('td');
      tdT.className = 'time-col';
      const dEl = document.createElement('div');
      dEl.className = 'departs';
      dEl.textContent = disp;
      tdT.appendChild(dEl);
      tdT.appendChild(makeCountdown(mins));

      tr.append(tdB, tdS, tdD, tdT);
      tbody.appendChild(tr);
    });
    document.getElementById('status').textContent =
      'Uppdaterad '+pad(new Date().getHours())+':'+pad(new Date().getMinutes())+':'+pad(new Date().getSeconds());
  } catch(e) {
    document.getElementById('tbody').innerHTML =
      `<tr><td colspan="3" class="error-msg">Fel: ${e.message}</td></tr>`;
  }
}

/* ── Vehicle positions ── */
async function fetchVehicles() {
  try {
    const resp = await fetch('/departures/vehicles');
    if (!resp.ok) return;
    const vehicles = await resp.json();
    updateBuses(vehicles);
  } catch(_) {}
}

/* ── Disruptions ticker ── */
let _disruptions = [];
let _disruptionIdx = 0;
let _disruptionTimer = null;

const DISRUPTION_WINDOW = 3;

function renderDisruption() {
  const el = document.getElementById('disruptions');
  const label = document.getElementById('disruptions-label');
  if (!_disruptions.length) {
    label.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> &nbsp;Störningar';
    el.innerHTML = '<span style="color:var(--green)"><i class="fa-solid fa-circle-check"></i> Inga störningar</span>';
    return;
  }
  const n = _disruptions.length;
  const start = _disruptionIdx % n;
  const visible = Array.from({length: Math.min(DISRUPTION_WINDOW, n)}, (_, i) => _disruptions[(start + i) % n]);
  label.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> &nbsp;Störningar <span style="color:var(--muted);font-weight:400">(${n} totalt)</span>`;
  el.innerHTML = visible.map(d => {
    const hi = d.importance <= 2 ? ' high' : '';
    const detail = d.details ? ' — ' + d.details : '';
    return `<div class="disruption-item${hi}">
      <span class="scope"><i class="fa-solid fa-triangle-exclamation"></i> ${d.scope}</span>
      <span class="text">${d.header}${detail}</span>
    </div>`;
  }).join('');
}

function nextDisruption() {
  _disruptionIdx++;
  renderDisruption();
}

async function fetchDisruptions() {
  try {
    const resp = await fetch('/departures/disruptions');
    if (!resp.ok) return;
    const fresh = await resp.json();
    _disruptions = fresh;
    _disruptionIdx = 0;
    if (_disruptionTimer) clearInterval(_disruptionTimer);
    if (_disruptions.length > DISRUPTION_WINDOW) {
      _disruptionTimer = setInterval(nextDisruption, 6000);
    }
    renderDisruption();
  } catch(_) {
    // Keep existing display — don't overwrite with empty state
  }
}

setInterval(updateClock, 1000);
setInterval(fetchDepartures, 60000);
setInterval(fetchVehicles, 10000);
setInterval(fetchDisruptions, 120000);

updateClock();
fetchDepartures();
fetchVehicles();
fetchDisruptions();
</script>
</body>
</html>
"""
