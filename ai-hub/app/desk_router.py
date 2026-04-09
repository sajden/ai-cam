"""desk_router.py — FastAPI router for the desk activity dashboard."""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(prefix="/desk", tags=["desk"])

_DB_PATH = os.getenv("AIHUB_DB_PATH", "/data/aihub.db")

# Stockholm offset: UTC+1 in winter (UTC+2 from last Sunday March DST).
# March 29 2026 is the DST switch; until then we use +1.
_STOCKHOLM = timezone(timedelta(hours=1))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now_sthlm() -> datetime:
    return datetime.now(tz=_STOCKHOLM)


def _parse_utc(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp stored as UTC, return as Stockholm-local datetime."""
    if not ts:
        return None
    try:
        # fromisoformat handles +00:00, Z, and naive strings (Python 3.11+)
        ts_clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_STOCKHOLM)
    except ValueError:
        return None


def _fetch_today_trips() -> list[dict]:
    today = _now_sthlm().strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, date, left_at, returned_at, duration_sec, time_of_day "
            "FROM desk_trips WHERE date = ? ORDER BY left_at ASC",
            (today,),
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "date": r["date"],
                "left_at": r["left_at"],
                "returned_at": r["returned_at"],
                "duration_sec": r["duration_sec"],
                "time_of_day": r["time_of_day"],
            })
        return result
    finally:
        conn.close()


def _fetch_input_stats(date: str) -> dict:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT keypresses, clicks, first_active_at FROM input_stats WHERE date = ?", (date,)
        ).fetchone()
        if row:
            return {
                "keypresses": row["keypresses"],
                "clicks": row["clicks"],
                "first_active_at": row["first_active_at"],
            }
        return {"keypresses": 0, "clicks": 0, "first_active_at": None}
    finally:
        conn.close()


def _fetch_week_input_stats() -> list[dict]:
    """Fetch input_stats for the last 7 days, one entry per day."""
    now = _now_sthlm()
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    conn = _get_conn()
    try:
        placeholders = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT date, keypresses, clicks, first_active_at FROM input_stats WHERE date IN ({placeholders})",
            dates,
        ).fetchall()
        by_date = {r["date"]: dict(r) for r in rows}
        return [
            {"date": d,
             "keypresses": by_date.get(d, {}).get("keypresses", 0),
             "clicks": by_date.get(d, {}).get("clicks", 0),
             "first_active_at": by_date.get(d, {}).get("first_active_at")}
            for d in dates
        ]
    finally:
        conn.close()


def _fetch_total_input_stats() -> dict:
    """Fetch all-time totals from input_stats."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT SUM(keypresses) as kp, SUM(clicks) as cl FROM input_stats"
        ).fetchone()
        return {
            "keypresses": row["kp"] or 0,
            "clicks": row["cl"] or 0,
        }
    finally:
        conn.close()


def _fetch_week_trips() -> list[dict]:
    now = _now_sthlm()
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    conn = _get_conn()
    try:
        placeholders = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT id, date, left_at, returned_at, duration_sec, time_of_day "
            f"FROM desk_trips WHERE date IN ({placeholders}) ORDER BY date, left_at",
            dates,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

def _compute_sitting_periods(
    trips: list[dict], today_date: str, session_start_dt: datetime | None = None
) -> list[tuple[datetime, datetime]]:
    """Return list of (start, end) datetime pairs representing time AT desk.

    If session_start_dt is provided (first keyboard activity of the day) it
    is used as the cursor start so that sitting time before the first break
    is counted. Otherwise falls back to first_left.
    """
    if not trips:
        return []

    now = _now_sthlm()
    day_end_dt = datetime.strptime(today_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=_STOCKHOLM
    )
    day_cap = min(now, day_end_dt)

    first_left = _parse_utc(trips[0]["left_at"])
    if first_left is None:
        return []

    sitting: list[tuple[datetime, datetime]] = []
    # Use session_start only if it plausibly represents the same session —
    # gap > 5 h means overnight activity, fall back to first_left.
    if (session_start_dt and session_start_dt < first_left
            and (first_left - session_start_dt).total_seconds() <= 5 * 3600):
        cursor = min(session_start_dt, day_cap)
    else:
        cursor = min(first_left, day_cap)

    for trip in trips:
        left = _parse_utc(trip["left_at"])
        if left is None:
            continue
        left = min(left, day_cap)
        if left > cursor:
            sitting.append((cursor, left))
        ret = _parse_utc(trip["returned_at"])
        cursor = min(ret, day_cap) if ret else day_cap

    # Final sitting period up to day cap (only if not currently away)
    if cursor < day_cap and trips[-1]["returned_at"] is not None:
        sitting.append((cursor, day_cap))

    return [(s, e) for s, e in sitting if e > s]


def _build_day_timeline(
    trips: list[dict], today_date: str, now: datetime,
    session_start_dt: datetime | None = None,
) -> list[dict]:
    """Build ordered list of at-desk and away periods for the day."""
    if not trips:
        return []

    day_end_dt = datetime.strptime(today_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=_STOCKHOLM
    )
    day_cap = min(now, day_end_dt)

    first_left = _parse_utc(trips[0]["left_at"])
    if first_left is None:
        return []

    def _fmt(dt: datetime) -> str:
        return dt.strftime("%H:%M")

    def _dur(a: datetime, b: datetime) -> int:
        return int((b - a).total_seconds() // 60)

    periods: list[dict] = []
    if (session_start_dt and session_start_dt < first_left
            and (first_left - session_start_dt).total_seconds() <= 5 * 3600):
        cursor = min(session_start_dt, day_cap)
    else:
        cursor = min(first_left, day_cap)

    for trip in trips:
        left = _parse_utc(trip["left_at"])
        if left is None:
            continue
        left = min(left, day_cap)

        # At-desk period from cursor to this departure
        if left > cursor:
            periods.append({
                "type": "at",
                "start": cursor.isoformat(),
                "end": left.isoformat(),
                "start_label": _fmt(cursor),
                "end_label": _fmt(left),
                "duration_min": _dur(cursor, left),
                "open": False,
            })

        # Away period
        ret = _parse_utc(trip["returned_at"])
        away_end = min(ret, day_cap) if ret else day_cap
        periods.append({
            "type": "away",
            "start": left.isoformat(),
            "end": away_end.isoformat(),
            "start_label": _fmt(left),
            "end_label": _fmt(away_end) if ret else "nu",
            "duration_min": _dur(left, away_end),
            "open": ret is None,
        })
        cursor = away_end

    # Final at-desk period if not currently away
    if cursor < day_cap and trips[-1]["returned_at"] is not None:
        periods.append({
            "type": "at",
            "start": cursor.isoformat(),
            "end": day_cap.isoformat(),
            "start_label": _fmt(cursor),
            "end_label": "nu",
            "duration_min": _dur(cursor, day_cap),
            "open": True,
        })

    return periods


def _build_api_data() -> dict:
    now = _now_sthlm()
    today = now.strftime("%Y-%m-%d")

    today_trips = _fetch_today_trips()
    week_trips = _fetch_week_trips()

    # --- Current status ---
    currently_away = False
    away_min = 0
    if today_trips:
        last = today_trips[-1]
        if last["returned_at"] is None:
            currently_away = True
            left_dt = _parse_utc(last["left_at"])
            if left_dt:
                away_min = int((now - left_dt).total_seconds() // 60)

    # Current sitting streak (only when at desk)
    current_sitting_min = 0
    if not currently_away and today_trips:
        last = today_trips[-1]
        ret_dt = _parse_utc(last["returned_at"])
        if ret_dt:
            current_sitting_min = int((now - ret_dt).total_seconds() // 60)
    elif not currently_away and not today_trips:
        # No trips yet — use first_active_at from input_stats as session start
        current_sitting_min = 0  # will be overridden below after input_stats fetch

    if currently_away:
        current_status = f"borta {away_min} min"
    else:
        current_status = f"vid skrivbordet {current_sitting_min} min" if current_sitting_min else "vid skrivbordet"

    # --- Today stats ---
    input_stats = _fetch_input_stats(today)
    first_active = _parse_utc(input_stats.get("first_active_at"))

    sitting_periods = _compute_sitting_periods(today_trips, today, session_start_dt=first_active)
    total_sitting_sec = sum((e - s).total_seconds() for s, e in sitting_periods)
    total_sitting_min = int(total_sitting_sec // 60)

    break_count = len(today_trips)

    longest_sitting_sec = max((e - s).total_seconds() for s, e in sitting_periods) if sitting_periods else 0
    longest_sitting_min = int(longest_sitting_sec // 60)

    # No trips yet — compute from first_active_at
    if not today_trips and not currently_away and first_active:
        session_min = int((now - first_active).total_seconds() // 60)
        current_sitting_min = session_min
        total_sitting_min = session_min
        longest_sitting_min = session_min

    # --- Week summary per day ---
    from collections import defaultdict
    trips_by_date: dict[str, list[dict]] = defaultdict(list)
    for t in week_trips:
        trips_by_date[t["date"]].append(t)

    # Fetch first_active_at for all 7 days in one query
    week_input_stats = _fetch_week_input_stats()
    first_active_by_date: dict[str, datetime | None] = {
        row["date"]: _parse_utc(row["first_active_at"]) for row in week_input_stats
    }

    week_summary = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_trips = trips_by_date.get(d, [])
        day_first_active = first_active_by_date.get(d)
        sp = _compute_sitting_periods(day_trips, d, session_start_dt=day_first_active)
        sit_sec = sum((e - s).total_seconds() for s, e in sp)
        bc = len(day_trips)
        longest_sit = max((e - s).total_seconds() for s, e in sp) if sp else 0
        # Today with no trips: fall back to first_active
        if not day_trips and d == today and first_active:
            sit_sec = (now - first_active).total_seconds()
            longest_sit = sit_sec
        week_summary.append({
            "date": d,
            "sitting_min": int(sit_sec // 60),
            "break_count": bc,
            "longest_sitting_min": int(longest_sit // 60),
        })

    day_timeline = _build_day_timeline(today_trips, today, now, session_start_dt=first_active)
    total_input_stats = _fetch_total_input_stats()

    return {
        "today_trips": today_trips,
        "week_summary": week_summary,
        "current_status": current_status,
        "day_timeline": day_timeline,
        "stats_today": {
            "total_sitting_min": total_sitting_min,
            "break_count": break_count,
            "longest_sitting_min": longest_sitting_min,
            "currently_away": currently_away,
            "away_min": away_min,
            "current_sitting_min": current_sitting_min,
            "session_start": input_stats.get("first_active_at"),
            "keypresses": input_stats["keypresses"],
            "clicks": input_stats["clicks"],
        },
        "week_input_stats": week_input_stats,
        "total_input_stats": total_input_stats,
    }


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Skrivbord</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #0d0d1a;
    color: #e0e0e0;
    font-family: \'Segoe UI\', system-ui, sans-serif;
    min-height: 100vh;
    padding: 16px;
  }

  .page {
    max-width: 1000px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* ── Header ── */
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .page-title { font-size: 0.95rem; color: #555; text-transform: uppercase; letter-spacing: 0.1em; }
  .updated-at { font-size: 0.80rem; color: #444; }

  /* ── Hero status card ── */
  .hero {
    background: #13132b;
    border-radius: 14px;
    padding: 20px 24px;
    border: 1px solid #1e1e40;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 16px;
    align-items: center;
  }

  .hero-left { display: flex; flex-direction: column; gap: 6px; }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: 0.01em;
  }
  .status-badge .dot {
    width: 16px; height: 16px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .status-badge.at-desk { color: #66bb6a; }
  .status-badge.at-desk .dot { background: #66bb6a; box-shadow: 0 0 8px #66bb6a88; }
  .status-badge.away { color: #ffa726; }
  .status-badge.away .dot { background: #ffa726; box-shadow: 0 0 8px #ffa72688; }

  .status-sub {
    font-size: 1rem;
    color: #666;
  }

  /* right side quick stats */
  .hero-right {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px 20px;
    text-align: right;
  }
  .qs { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .qs-val { font-size: 1.35rem; font-weight: 700; color: #90caf9; font-variant-numeric: tabular-nums; }
  .qs-lbl { font-size: 0.75rem; color: #555; text-transform: uppercase; letter-spacing: 0.06em; }

  /* ── Cards ── */
  .card {
    background: #13132b;
    border-radius: 12px;
    padding: 18px 20px;
    border: 1px solid #1e1e40;
  }
  .card-title {
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #5c6bc0;
    margin-bottom: 14px;
  }

  /* ── Timeline ── */
  #timeline-svg { display: block; width: 100%; min-width: 400px; }
  .tl-legend { display: flex; gap: 18px; margin-top: 10px; font-size: 0.72rem; color: #666; }
  .tl-legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend-dot { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }

  /* ── 2-col lower grid ── */
  .lower-grid {
    display: grid;
    grid-template-columns: 340px 1fr;
    gap: 14px;
  }
  @media (max-width: 720px) { .lower-grid { grid-template-columns: 1fr; } }

  /* ── Trips list ── */
  .trip-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid #1a1a32;
    font-size: 0.84rem;
  }
  .trip-row:last-child { border-bottom: none; }
  .trip-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .trip-dot.at  { background: #4fc3f7; }
  .trip-dot.away { background: #ff8a65; }
  .trip-time { color: #777; font-variant-numeric: tabular-nums; min-width: 110px; font-size: 0.92rem; }
  .trip-label { color: #ccc; flex: 1; font-size: 0.92rem; }
  .trip-label.away { color: #ffa726; }
  .trip-label.at   { color: #81c784; }
  #trips-list-empty { color: #444; font-size: 0.82rem; padding: 6px 0; }

  /* ── Week charts ── */
  .charts-stack { display: flex; flex-direction: column; gap: 24px; }

  .bar-chart {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    height: 100px;
  }
  .bar-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 100%;
    justify-content: flex-end;
    gap: 4px;
  }
  .bar {
    width: 100%;
    border-radius: 3px 3px 0 0;
    min-height: 2px;
  }
  .bar-val { font-size: 0.76rem; color: #888; text-align: center; }
  .bar-lbl { font-size: 0.76rem; color: #666; text-align: center; }
  .bar-lbl.today { color: #90caf9; }

  /* ── Totals row ── */
  .totals-row {
    display: flex;
    gap: 24px;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid #1a1a32;
  }
  .total-item { display: flex; flex-direction: column; gap: 2px; }
  .total-val { font-size: 1.5rem; font-weight: 700; color: #ce93d8; font-variant-numeric: tabular-nums; }
  .total-lbl { font-size: 0.78rem; color: #555; text-transform: uppercase; letter-spacing: 0.06em; }
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="page-header">
    <span class="page-title">Skrivbordsaktivitet</span>
    <span class="updated-at" id="updated-at"></span>
  </div>

  <!-- Hero -->
  <div class="hero">
    <div class="hero-left">
      <div class="status-badge" id="hero-badge">
        <span class="dot"></span>
        <span id="hero-status-text">–</span>
      </div>
      <div class="status-sub" id="hero-sub"></div>
    </div>
    <div class="hero-right">
      <div class="qs"><span class="qs-val" id="qs-sitting">–</span><span class="qs-lbl">Sitttid</span></div>
      <div class="qs"><span class="qs-val" id="qs-breaks">–</span><span class="qs-lbl">Raster</span></div>
      <div class="qs"><span class="qs-val" id="qs-longest">–</span><span class="qs-lbl">Längsta pass</span></div>
      <div class="qs"><span class="qs-val" id="qs-keys">–</span><span class="qs-lbl">Tangenter</span></div>
      <div class="qs"><span class="qs-val" id="qs-clicks">–</span><span class="qs-lbl">Klick</span></div>
      <div class="qs"><span class="qs-val" id="qs-streak">–</span><span class="qs-lbl">Nu i sträck</span></div>
    </div>
  </div>

  <!-- Timeline -->
  <div class="card">
    <div class="card-title">Tidslinje idag</div>
    <svg id="timeline-svg" height="60"></svg>
    <div class="tl-legend">
      <span><span class="legend-dot" style="background:#4fc3f7"></span>Vid skrivbordet</span>
      <span><span class="legend-dot" style="background:#ff8a65"></span>Rast</span>
    </div>
  </div>

  <!-- Lower grid: trips list + week charts -->
  <div class="lower-grid">

    <!-- Trips list -->
    <div class="card">
      <div class="card-title">Perioder idag</div>
      <div id="trips-list"></div>
    </div>

    <!-- Week charts -->
    <div class="card">
      <div class="charts-stack">
        <div>
          <div class="card-title">Sitttid / vecka</div>
          <div class="bar-chart" id="week-chart"></div>
        </div>
        <div>
          <div class="card-title">Tangenter / vecka</div>
          <div class="bar-chart" id="input-week-chart"></div>
          <div class="totals-row" id="totals-row"></div>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
const API = \'/desk/api\';
const REFRESH_MS = 30000;

function fmtMin(min) {
  if (!min || min <= 0) return \'0 min\';
  if (min < 60) return min + \' min\';
  const h = Math.floor(min / 60), m = min % 60;
  return m > 0 ? h + \'h \' + m + \'m\' : h + \'h\';
}

function fmtCount(n) {
  if (n >= 1000000) return (n/1000000).toFixed(1).replace(\'.\',\',\') + \'M\';
  if (n >= 1000)    return (n/1000).toFixed(1).replace(\'.\',\',\') + \'k\';
  return n.toString();
}

function parseISOtoDate(ts) {
  if (!ts) return null;
  let s = ts.replace(\' \',\'T\');
  // Only append Z if there is no timezone info at all (no Z, no +HH:MM, no -HH:MM at end)
  if (!/Z$/.test(s) && !/[+-]\\d{2}:\\d{2}$/.test(s)) s += \'Z\';
  const d = new Date(s);
  return isNaN(d) ? null : d;
}
function toSthlm(d) { return new Date(d.getTime() + 3600000); }
function totalMinutes(d) { return d.getHours()*60 + d.getMinutes(); }
function shortDay(ds) {
  return new Date(ds + \'T12:00:00Z\').toLocaleDateString(\'sv-SE\', {weekday:\'short\', timeZone:\'UTC\'});
}

// ── Hero ──────────────────────────────────────────
function renderHero(stats) {
  const badge = document.getElementById(\'hero-badge\');
  const txt   = document.getElementById(\'hero-status-text\');
  const sub   = document.getElementById(\'hero-sub\');

  if (stats.currently_away) {
    badge.className = \'status-badge away\';
    txt.textContent = \'Rast\';
    sub.textContent = \'Borta sedan \' + fmtMin(stats.away_min);
  } else {
    badge.className = \'status-badge at-desk\';
    txt.textContent = \'Vid skrivbordet\';
    sub.textContent = stats.current_sitting_min > 0
      ? \'I sträck: \' + fmtMin(stats.current_sitting_min)
      : \'Aktiv nu\';
  }

  document.getElementById(\'qs-sitting\').textContent  = fmtMin(stats.total_sitting_min);
  document.getElementById(\'qs-breaks\').textContent   = stats.break_count;
  document.getElementById(\'qs-longest\').textContent  = fmtMin(stats.longest_sitting_min);
  document.getElementById(\'qs-keys\').textContent     = fmtCount(stats.keypresses || 0);
  document.getElementById(\'qs-clicks\').textContent   = fmtCount(stats.clicks || 0);
  document.getElementById(\'qs-streak\').textContent   = stats.currently_away ? \'–\' : fmtMin(stats.current_sitting_min);
}

// ── Timeline ─────────────────────────────────────
function renderTimeline(dayTimeline, stats) {
  const svg = document.getElementById(\'timeline-svg\');
  svg.innerHTML = \'\';

  // No breaks yet — draw current session as a blue bar if we have a session start
  if (!dayTimeline || dayTimeline.length === 0) {
    const sessionStart = stats && stats.session_start ? parseISOtoDate(stats.session_start) : null;
    if (!sessionStart) {
      svg.setAttribute(\'height\', \'32\');
      const msg = document.createElementNS(\'http://www.w3.org/2000/svg\',\'text\');
      msg.setAttribute(\'x\',\'50%\'); msg.setAttribute(\'y\',\'20\');
      msg.setAttribute(\'text-anchor\',\'middle\'); msg.setAttribute(\'font-size\',\'13\');
      msg.setAttribute(\'fill\',\'#444\'); msg.textContent = \'Ingen aktivitet ännu idag\';
      svg.appendChild(msg);
      return;
    }
    // Synthesise a single "at desk" period from session_start to now
    const nowUtc = new Date();
    dayTimeline = [{type:\'at\', start: sessionStart.toISOString(), end: nowUtc.toISOString(),
                    start_label:\'\', end_label:\'nu\', duration_min:0, open:true}];
  }

  const W = svg.clientWidth || 600, H = 60, barY = 14, barH = 28;
  const now = new Date();

  const first = parseISOtoDate(dayTimeline[0].start);
  const startMin = first ? Math.max(0, totalMinutes(first) - 10) : 6*60;
  const endMin   = Math.max(totalMinutes(now), startMin + 60);
  const spanMin  = endMin - startMin;

  function xPos(dt) {
    return Math.max(0, Math.min(W, ((totalMinutes(dt) - startMin) / spanMin) * W));
  }

  // Background
  const bg = document.createElementNS(\'http://www.w3.org/2000/svg\',\'rect\');
  bg.setAttribute(\'x\',0); bg.setAttribute(\'y\',barY);
  bg.setAttribute(\'width\',W); bg.setAttribute(\'height\',barH);
  bg.setAttribute(\'fill\',\'#1a1a32\'); bg.setAttribute(\'rx\',4);
  svg.appendChild(bg);

  // Segments
  for (const p of dayTimeline) {
    const s = parseISOtoDate(p.start), e = parseISOtoDate(p.end);
    if (!s || !e) continue;
    const x1 = xPos(s), x2 = xPos(e);
    if (x2 <= x1) continue;
    const r = document.createElementNS(\'http://www.w3.org/2000/svg\',\'rect\');
    r.setAttribute(\'x\',x1); r.setAttribute(\'y\',barY);
    r.setAttribute(\'width\',x2-x1); r.setAttribute(\'height\',barH);
    r.setAttribute(\'fill\', p.type===\'at\' ? \'#4fc3f7\' : \'#ff8a65\');
    svg.appendChild(r);
  }

  // Axis labels — auto step so ~5-7 labels fit
  const step = [30, 60, 120, 180].find(s => spanMin / s <= 7) || 60;
  const firstMark = Math.ceil(startMin / step) * step;
  for (let m = firstMark; m <= endMin; m += step) {
    const x = ((m - startMin) / spanMin) * W;
    if (x < 20 || x > W - 20) continue;  // skip near-edge labels
    const hh = Math.floor(m / 60) % 24, mm = m % 60;
    const lbl = String(hh).padStart(2,\'0\') + \':\' + String(mm).padStart(2,\'0\');
    const t = document.createElementNS(\'http://www.w3.org/2000/svg\',\'text\');
    t.setAttribute(\'x\',x); t.setAttribute(\'y\',barY+barH+14);
    t.setAttribute(\'text-anchor\',\'middle\'); t.setAttribute(\'font-size\',\'10\');
    t.setAttribute(\'fill\',\'#555\'); t.textContent = lbl;
    svg.appendChild(t);
    const l = document.createElementNS(\'http://www.w3.org/2000/svg\',\'line\');
    l.setAttribute(\'x1\',x); l.setAttribute(\'x2\',x);
    l.setAttribute(\'y1\',barY+barH); l.setAttribute(\'y2\',barY+barH+5);
    l.setAttribute(\'stroke\',\'#333\'); l.setAttribute(\'stroke-width\',\'1\');
    svg.appendChild(l);
  }

  // now marker
  const nx = ((totalMinutes(now) - startMin) / spanMin) * W;
  if (nx >= 0 && nx <= W) {
    const nl = document.createElementNS(\'http://www.w3.org/2000/svg\',\'line\');
    nl.setAttribute(\'x1\',nx); nl.setAttribute(\'x2\',nx);
    nl.setAttribute(\'y1\',barY-6); nl.setAttribute(\'y2\',barY+barH+4);
    nl.setAttribute(\'stroke\',\'#fff\'); nl.setAttribute(\'stroke-width\',\'1.5\');
    nl.setAttribute(\'stroke-dasharray\',\'3,3\');
    svg.appendChild(nl);
    const nt = document.createElementNS(\'http://www.w3.org/2000/svg\',\'text\');
    nt.setAttribute(\'x\',nx); nt.setAttribute(\'y\',barY-9);
    nt.setAttribute(\'text-anchor\',\'middle\'); nt.setAttribute(\'font-size\',\'9\');
    nt.setAttribute(\'fill\',\'#aaa\'); nt.textContent = \'Nu\';
    svg.appendChild(nt);
  }
  svg.setAttribute(\'height\', H);
}

// ── Trips list ────────────────────────────────────
function renderTripsList(dayTimeline, stats) {
  const el = document.getElementById(\'trips-list\');
  el.innerHTML = \'\';
  if (!dayTimeline || dayTimeline.length === 0) {
    const sessionStart = stats && stats.session_start ? parseISOtoDate(stats.session_start) : null;
    if (sessionStart) {
      const hh = String(sessionStart.getHours()).padStart(2,\'0\');
      const mm = String(sessionStart.getMinutes()).padStart(2,\'0\');
      el.innerHTML = \'<div id="trips-list-empty" style="color:#4fc3f7;font-size:0.88rem;padding:6px 0">\'
        + \'Inga raster ännu — sitter sedan \' + hh + \':\' + mm + \'</div>\';
    } else {
      el.innerHTML = \'<div id="trips-list-empty">Ingen aktivitet registrerad idag.</div>\';
    }
    return;
  }
  for (const p of dayTimeline) {
    const row = document.createElement(\'div\');
    row.className = \'trip-row\';

    const dot = document.createElement(\'span\');
    dot.className = \'trip-dot \' + p.type;

    const time = document.createElement(\'span\');
    time.className = \'trip-time\';
    time.textContent = p.start_label + \' – \' + (p.open ? \'nu\' : p.end_label);

    const lbl = document.createElement(\'span\');
    lbl.className = \'trip-label \' + p.type;
    if (p.type === \'away\') {
      lbl.textContent = p.open ? \'Rast pågår — \' + fmtMin(p.duration_min) : \'Rast \' + fmtMin(p.duration_min);
    } else {
      lbl.textContent = \'Vid skrivbordet \' + fmtMin(p.duration_min);
    }

    row.appendChild(dot);
    row.appendChild(time);
    row.appendChild(lbl);
    el.appendChild(row);
  }
}

// ── Bar chart helper ──────────────────────────────
function renderBarChart(containerId, days, getValue, getLabel, color, todayColor) {
  const container = document.getElementById(containerId);
  container.innerHTML = \'\';
  const today = new Date().toISOString().slice(0,10);
  const max = Math.max(...days.map(getValue), 1);
  const maxH = 80;
  for (const day of days) {
    const isToday = day.date === today;
    const val = getValue(day);
    const barH = Math.max(val > 0 ? 3 : 1, Math.round((val / max) * maxH));
    const wrap = document.createElement(\'div\'); wrap.className = \'bar-wrap\';
    const valEl = document.createElement(\'div\'); valEl.className = \'bar-val\';
    valEl.textContent = val > 0 ? getLabel(val) : \'\';
    const bar = document.createElement(\'div\'); bar.className = \'bar\';
    bar.style.height = barH + \'px\';
    bar.style.background = isToday ? todayColor : color;
    if (isToday) bar.style.boxShadow = \'0 0 6px \' + todayColor + \'88\';
    bar.title = day.date + \': \' + getLabel(val);
    const lbl = document.createElement(\'div\');
    lbl.className = \'bar-lbl\' + (isToday ? \' today\' : \'\');
    lbl.textContent = shortDay(day.date);
    wrap.appendChild(valEl); wrap.appendChild(bar); wrap.appendChild(lbl);
    container.appendChild(wrap);
  }
}

// ── Refresh ───────────────────────────────────────
async function refresh() {
  try {
    const resp = await fetch(API);
    if (!resp.ok) throw new Error(\'HTTP \' + resp.status);
    const data = await resp.json();
    const stats = data.stats_today;

    renderHero(stats);
    renderTimeline(data.day_timeline || [], stats);
    renderTripsList(data.day_timeline || [], stats);

    renderBarChart(\'week-chart\', data.week_summary,
      d => d.sitting_min, fmtMin, \'#3949ab\', \'#5c6bc0\');

    renderBarChart(\'input-week-chart\', data.week_input_stats || [],
      d => d.keypresses, fmtCount, \'#6a1b9a\', \'#9c27b0\');

    // Totals
    const totals = data.total_input_stats || {};
    const tr = document.getElementById(\'totals-row\');
    tr.innerHTML = \'\';
    [{val:(totals.keypresses||0).toLocaleString(\'sv-SE\'), lbl:\'Totalt tangenter\'},
     {val:(totals.clicks||0).toLocaleString(\'sv-SE\'), lbl:\'Totalt klick\'}
    ].forEach(({val,lbl}) => {
      const d = document.createElement(\'div\'); d.className = \'total-item\';
      d.innerHTML = `<span class="total-val">${val}</span><span class="total-lbl">${lbl}</span>`;
      tr.appendChild(d);
    });

    const now = new Date();
    document.getElementById(\'updated-at\').textContent =
      \'Uppdaterad \' + now.toLocaleTimeString(\'sv-SE\',{hour:\'2-digit\',minute:\'2-digit\'});
  } catch(e) { console.error(\'Refresh failed:\', e); }
}

refresh();
setInterval(refresh, REFRESH_MS);
window.addEventListener(\'resize\', () => {
  fetch(API).then(r=>r.json()).then(data=>renderTimeline(data.day_timeline||[], data.stats_today)).catch(()=>{});
});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def desk_dashboard() -> HTMLResponse:
    return HTMLResponse(content=_DASHBOARD_HTML)


@router.get("/api")
def desk_api() -> JSONResponse:
    return JSONResponse(content=_build_api_data())
