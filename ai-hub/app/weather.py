"""weather.py — Weather dashboard for Bromma/Stockholm"""
from __future__ import annotations
import json, os, urllib.request
from collections import defaultdict
from datetime import date, datetime

BROMMA_LAT = 59.354
BROMMA_LON = 17.941

_HA_URL   = os.getenv("AIHUB_HA_BASE_URL", "http://homeassistant:8123").rstrip("/")
_HA_TOKEN = os.getenv("AIHUB_HA_TOKEN", "").strip()

_OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={BROMMA_LAT}&longitude={BROMMA_LON}"
    "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m"
    ",precipitation_probability,precipitation,weather_code"
    ",wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,snow_depth"
    ",surface_pressure"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
    ",weather_code,sunrise,sunset,uv_index_max,wind_speed_10m_max"
    "&timezone=Europe%2FStockholm&forecast_days=6&wind_speed_unit=ms"
)
_SMHI_WARNINGS = "https://opendata-download-warnings.smhi.se/api/version/2/messages.json"
_SMHI_WATER = (
    "https://opendata-download-metobs.smhi.se/api/version/latest"
    "/parameter/7/station/98040/period/latest-day/data.json"
)
_POLLEN_REGIONS   = "https://api.pollenrapporten.se/v1/regions"
_POLLEN_TYPES     = "https://api.pollenrapporten.se/v1/pollen-types"
_POLLEN_FORECASTS = "https://api.pollenrapporten.se/v1/forecasts?current=true&limit=1&region_id="

_WMO = {
    0:("Klart","\u2600\ufe0f"),1:("Mestadels klart","\U0001f324\ufe0f"),
    2:("Delvis molnigt","\u26c5"),3:("Mulet","\u2601\ufe0f"),
    45:("Dimma","\U0001f32b\ufe0f"),48:("Rimfrostdimma","\U0001f32b\ufe0f"),
    51:("L\u00e4tt duggregn","\U0001f326\ufe0f"),53:("Duggregn","\U0001f326\ufe0f"),
    55:("Kraftigt duggregn","\U0001f327\ufe0f"),61:("L\u00e4tt regn","\U0001f327\ufe0f"),
    63:("Regn","\U0001f327\ufe0f"),65:("Kraftigt regn","\U0001f327\ufe0f"),
    71:("L\u00e4tt sn\u00f6fall","\U0001f328\ufe0f"),73:("Sn\u00f6fall","\u2744\ufe0f"),
    75:("Kraftigt sn\u00f6fall","\u2744\ufe0f"),77:("Sn\u00f6byar","\U0001f328\ufe0f"),
    80:("L\u00e4tta skurar","\U0001f326\ufe0f"),81:("Regnskurar","\U0001f327\ufe0f"),
    82:("Kraftiga skurar","\u26c8\ufe0f"),85:("Sn\u00f6byar","\U0001f328\ufe0f"),
    86:("Kraftiga sn\u00f6byar","\u2744\ufe0f"),95:("\u00c5ska","\u26c8\ufe0f"),
    96:("\u00c5ska med hagel","\u26c8\ufe0f"),99:("Kraftig \u00e5ska","\u26c8\ufe0f"),
}
_DAYS_SV   = ["M\u00e5n","Tis","Ons","Tor","Fre","L\u00f6r","S\u00f6n"]
_WIND_DIRS = ["N","NNO","NO","ONO","O","OSO","SO","SSO","S","SSV","SV","VSV","V","VNV","NV","NNV"]
_WINTER_KW = {"halka","is ","sn\u00f6","frost","isning","v\u00e4gis"}
_POL_DOT = ["#4b5563","#16a34a","#65a30d","#ca8a04","#ea580c","#ef4444","#dc2626","#991b1b"]
_POL_LBL = ["\u2013","L\u00e5g","L\u00e5g\u2013M\u00e5ttlig","M\u00e5ttlig","M\u00e5ttlig\u2013H\u00f6g","H\u00f6g","H\u00f6g\u2013Mycket h\u00f6g","Mycket h\u00f6g"]

_pollen_region_id: str | None = None
_pollen_id_to_name: dict[str, str] = {}

def _ensure_pollen_meta() -> bool:
    global _pollen_region_id, _pollen_id_to_name
    if _pollen_region_id and _pollen_id_to_name:
        return True
    regions = _fetch_json(_POLLEN_REGIONS)
    if regions:
        for r in regions.get("items", []):
            if "stockholm" in r.get("name", "").lower():
                _pollen_region_id = r.get("id"); break
    types_raw = _fetch_json(_POLLEN_TYPES)
    if types_raw:
        for pt in types_raw.get("items", []):
            _pollen_id_to_name[pt.get("id","")] = pt.get("swedishName") or pt.get("name","Ok\u00e4nd")
    return bool(_pollen_region_id)

def _fetch_json(url, post_body=None, content_type="application/json", headers=None):
    try:
        hdrs = {"User-Agent": "ai-cam/1.0"}
        if headers: hdrs.update(headers)
        if post_body: hdrs["Content-Type"] = content_type
        req = urllib.request.Request(url, data=post_body, headers=hdrs)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None

def _wind_dir_sv(deg):
    return _WIND_DIRS[round(deg / 22.5) % 16]

def fetch_weather() -> dict:
    data = _fetch_json(_OPEN_METEO)
    if not data: return {"error": "fetch_failed"}
    hourly = data["hourly"]; daily = data["daily"]
    now = datetime.now(); times = hourly["time"]
    now_str = now.strftime("%Y-%m-%dT%H:00")
    ci = next((i for i,t in enumerate(times) if t >= now_str), 0)
    def h(key): return hourly[key][ci]
    code = h("weather_code")
    desc, icon = _WMO.get(code, ("Ok\u00e4nt","?"))
    current = {
        "temp": round(h("temperature_2m"),1), "feels_like": round(h("apparent_temperature"),1),
        "humidity": h("relative_humidity_2m"), "precip_prob": h("precipitation_probability"),
        "precip": h("precipitation"), "wind_speed": round(h("wind_speed_10m"),1),
        "wind_dir_deg": h("wind_direction_10m"), "wind_dir": _wind_dir_sv(h("wind_direction_10m")),
        "wind_gust": round(h("wind_gusts_10m"),1), "uv": round(h("uv_index"),1),
        "snow_depth": round(h("snow_depth"),1), "pressure": round(h("surface_pressure"),1),
        "code": code, "desc": desc, "icon": icon,
        "sunrise": daily["sunrise"][0].split("T")[1], "sunset": daily["sunset"][0].split("T")[1],
    }
    pressure_history = [round(hourly["surface_pressure"][i],1) for i in range(max(0,ci-11),ci+1)]
    hourly_fc = []
    for i in range(ci, min(ci+13, len(times))):
        c = hourly["weather_code"][i]
        hourly_fc.append({"time":times[i].split("T")[1],"temp":round(hourly["temperature_2m"][i],1),
            "precip_prob":hourly["precipitation_probability"][i],"code":c,"icon":_WMO.get(c,("","?"))[1],
            "wind":round(hourly["wind_speed_10m"][i],1)})
    daily_fc = []
    for i in range(1, min(6,len(daily["time"]))):
        c = daily["weather_code"][i]; desc_d,icon_d = _WMO.get(c,("Ok\u00e4nt","?"))
        dt = date.fromisoformat(daily["time"][i])
        daily_fc.append({"day":_DAYS_SV[dt.weekday()],"date":dt.strftime("%d/%m"),
            "max":round(daily["temperature_2m_max"][i],1),"min":round(daily["temperature_2m_min"][i],1),
            "precip":round(daily["precipitation_sum"][i],1),"code":c,"desc":desc_d,"icon":icon_d,
            "uv_max":round(daily["uv_index_max"][i],1),"wind_max":round(daily["wind_speed_10m_max"][i],1),
            "sunrise":daily["sunrise"][i].split("T")[1],"sunset":daily["sunset"][i].split("T")[1]})
    return {"current":current,"hourly":hourly_fc,"daily":daily_fc,
            "pressure_history":pressure_history,"updated":now.strftime("%H:%M")}

def fetch_warnings() -> list:
    data = _fetch_json(_SMHI_WARNINGS)
    if not data: return []
    month = datetime.now().month; is_winter = month in (10,11,12,1,2,3,4)
    result = []
    for msg in (data if isinstance(data,list) else []):
        area_ids = [str(a.get("id","")) for a in msg.get("area",[])]
        if not any(aid.startswith("01") or aid in ("","SE") for aid in area_ids): continue
        title = msg.get("event",{}).get("sv","")
        if not is_winter and any(w in title.lower() for w in _WINTER_KW): continue
        descriptions = msg.get("descriptions",[])
        text = descriptions[0].get("text",{}).get("sv","") if descriptions else ""
        result.append({"title":title,"text":text[:200],"severity":msg.get("severity","").lower()})
    return result[:4]

def fetch_pollen() -> dict:
    if not _ensure_pollen_meta() or not _pollen_region_id: return {"items":[],"text":""}
    data = _fetch_json(_POLLEN_FORECASTS + _pollen_region_id)
    if not data: return {"items":[],"text":""}
    forecasts = data.get("items",[])
    if not forecasts: return {"items":[],"text":"Ingen aktiv pollenprognos"}
    forecast = forecasts[0]; text = forecast.get("text","")
    levels: dict[str,int] = defaultdict(int)
    for entry in forecast.get("levelSeries",[]):
        pid = entry.get("pollenId",""); levels[pid] = max(levels[pid],entry.get("level",0))
    result = []
    for pid,level in levels.items():
        if level == 0: continue
        lv = min(level,7)
        result.append({"name":_pollen_id_to_name.get(pid,"Ok\u00e4nd"),"level":level,"label":_POL_LBL[lv],"color":_POL_DOT[lv]})
    result.sort(key=lambda x: -x["level"])
    return {"items":result[:8],"text":text[:300] if text else ""}

def fetch_water_temp() -> dict:
    data = _fetch_json(_SMHI_WATER)
    if not data: return {}
    values = data.get("value",[])
    if not values: return {}
    latest = values[-1]
    try: temp = float(latest.get("value",""))
    except (ValueError,TypeError): return {}
    ts = latest.get("date",0)
    updated = datetime.fromtimestamp(ts/1000).strftime("%d/%m %H:%M") if ts else ""
    return {"temp":temp,"station":data.get("station",{}).get("name","Adels\u00f6"),"updated":updated}

def fetch_indoor_air() -> dict:
    if not _HA_TOKEN: return {}
    result = {}
    simple = {
        "temp":"sensor.sovrum_temperature","humidity":"sensor.sovrum_humidity",
        "pm25":"sensor.sovrum_pm2_5","allergen":"sensor.sovrum_indoor_allergen_index",
        "water_level":"sensor.sovrum_water_level",
    }
    for key,entity_id in simple.items():
        data = _fetch_json(f"{_HA_URL}/api/states/{entity_id}",
                           headers={"Authorization":f"Bearer {_HA_TOKEN}"})
        if data and data.get("state") not in (None,"unavailable","unknown"):
            try: result[key] = float(data["state"])
            except (ValueError,TypeError): pass
    # Fan mode and humidifier target from attributes
    fan = _fetch_json(f"{_HA_URL}/api/states/fan.sovrum",
                      headers={"Authorization":f"Bearer {_HA_TOKEN}"})
    if fan:
        result["fan_mode"] = fan.get("attributes",{}).get("preset_mode","")
        result["fan_on"]   = fan.get("state") == "on"
    hum = _fetch_json(f"{_HA_URL}/api/states/humidifier.sovrum",
                      headers={"Authorization":f"Bearer {_HA_TOKEN}"})
    if hum:
        attrs = hum.get("attributes",{})
        result["humidity_target"] = attrs.get("humidity")
        result["humidifier_action"] = attrs.get("action","")
    return result


WEATHER_DASHBOARD_HTML = '<!DOCTYPE html>\n<html lang="sv">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">\n<title>Bromma V&#228;der</title>\n<link rel="preconnect" href="https://fonts.googleapis.com">\n<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">\n<style>\n:root{\n  --bg:#06080f;--panel:rgba(255,255,255,0.038);--border:rgba(255,255,255,0.075);\n  --t1:#e2e8f0;--t2:#94a3b8;--t3:#475569;\n  --accent:#60a5fa;--amber:#f59e0b;--green:#34d399;--red:#f87171;--cyan:#22d3ee;\n}\nhtml,body{height:100%;width:100%;margin:0;padding:0;overflow:hidden;background:var(--bg);color:var(--t1);font-family:\'Inter\',system-ui,sans-serif;-webkit-font-smoothing:antialiased;}\n*{box-sizing:border-box;}\n.page{display:grid;grid-template-rows:46px 1fr;height:100vh;}\n/* Header */\n.hdr{display:flex;justify-content:space-between;align-items:center;padding:0 18px;background:rgba(255,255,255,0.018);border-bottom:1px solid var(--border);}\n.hdr-logo{display:flex;align-items:center;gap:9px;}\n.hdr-dot{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);animation:blink 3s ease-in-out infinite;}\n@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}\n.hdr-name{font-size:.65rem;font-weight:700;letter-spacing:.25em;text-transform:uppercase;color:var(--t3);}\n.hdr-clock{font-size:1.55rem;font-weight:300;color:var(--t1);letter-spacing:.04em;}\n.hdr-right{font-size:.62rem;color:var(--t3);text-align:right;line-height:1.7;}\n/* Body grid */\n.body{display:grid;grid-template-rows:58fr 42fr;gap:7px;padding:7px;min-height:0;}\n.top-row{display:grid;grid-template-columns:235px 1fr 1fr 180px;gap:7px;min-height:0;}\n.bot-row{display:grid;grid-template-columns:300px 200px 205px 175px;gap:7px;min-height:0;}\n/* Panel */\n.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;min-height:0;}\n.pi{padding:11px 13px;height:100%;display:flex;flex-direction:column;gap:5px;min-height:0;overflow:hidden;}\n.lbl{font-size:.54rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--t3);flex-shrink:0;}\n/* Current */\n.cur-hero{display:flex;align-items:center;gap:10px;flex-shrink:0;}\n.cur-icon{font-size:2.8rem;line-height:1;flex-shrink:0;}\n.cur-temp{font-size:3.5rem;font-weight:900;line-height:1;color:#fff;letter-spacing:-3px;}\n.cur-temp sup{font-size:1.6rem;color:var(--accent);letter-spacing:0;vertical-align:super;}\n.cur-feels{font-size:.63rem;color:var(--t3);margin-top:2px;}\n.cur-desc{font-size:.8rem;font-weight:600;color:var(--t2);flex-shrink:0;}\n.stats{display:flex;flex-direction:column;gap:2px;flex:1;min-height:0;}\n.stat{display:flex;justify-content:space-between;align-items:center;padding:3px 8px;border-radius:6px;background:rgba(255,255,255,0.02);font-size:.69rem;}\n.sk{color:var(--t3);}.sv{color:var(--t2);font-weight:600;}\n.sun-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex-shrink:0;}\n.sun-cell{display:flex;align-items:center;gap:5px;padding:4px 8px;border-radius:7px;background:rgba(245,158,11,.05);border:1px solid rgba(245,158,11,.1);}\n.sun-cell .ico{font-size:.9rem;}.sun-cell .st{font-size:.82rem;font-weight:700;color:var(--amber);line-height:1;}\n.sun-cell .sg{font-size:.48rem;color:var(--t3);margin-top:1px;}\n.prs-wrap{flex-shrink:0;}\n.prs-lbl{font-size:.5rem;color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:2px;}\n/* Map */\n.map-frame{flex:1;overflow:hidden;min-height:0;}\n.map-frame iframe{width:100%;height:100%;border:none;display:block;}\n.wb{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:#94a3b8;font-size:.53rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;cursor:pointer;font-family:inherit;transition:all .15s;}\n.wb.active{background:rgba(96,165,250,.15);border-color:rgba(96,165,250,.35);color:#60a5fa;}\n.wb:hover{background:rgba(255,255,255,.09);}\n/* Hourly */\n.hour-list{display:flex;flex-direction:column;flex:1;gap:1px;min-height:0;}\n.hour-row{display:grid;grid-template-columns:32px 18px 1fr 26px;align-items:center;gap:3px;padding:2px 6px;border-radius:5px;font-size:.67rem;flex:1;}\n.hour-row.now{background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.15);}\n.ht{color:var(--t3);font-weight:600;font-size:.59rem;}.hi{font-size:.85rem;text-align:center;}\n.hte{color:var(--t2);font-weight:700;}.hr{color:var(--t3);font-size:.57rem;text-align:right;}\n/* Daily */\n.daily-wrap{display:flex;flex-direction:column;flex:1;min-height:0;gap:1px;}\n.day-row{display:grid;grid-template-columns:36px 22px 1fr 82px;align-items:center;gap:4px;padding:0 8px;flex:1;border-radius:5px;}\n.dn{font-weight:700;color:var(--t2);font-size:.74rem;}.di{font-size:.85rem;text-align:center;}\n.dd{color:var(--t3);font-size:.61rem;}.hi2{color:var(--red);font-weight:700;font-size:.71rem;}\n.lo2{color:var(--accent);margin-left:4px;font-size:.71rem;}\n.warn-list{display:flex;flex-direction:column;gap:2px;flex-shrink:0;}\n.warn-strip{display:flex;align-items:center;gap:6px;padding:3px 8px;border-radius:5px;border:1px solid;font-size:.63rem;}\n.warn-strip.orange{background:rgba(251,146,60,.06);border-color:rgba(251,146,60,.2);}\n.warn-strip.red{background:rgba(239,68,68,.06);border-color:rgba(239,68,68,.2);}\n.warn-strip.yellow{background:rgba(234,179,8,.05);border-color:rgba(234,179,8,.15);}\n.warn-strip.default{background:rgba(255,255,255,.02);border-color:rgba(255,255,255,.06);}\n.wt{font-weight:600;color:var(--t2);}.wx{color:var(--t3);margin-left:3px;}\n/* Pollen — compact rows */\n.pollen-rows{display:flex;flex-direction:column;gap:6px;flex:1;min-height:0;justify-content:center;}\n.pollen-row2{display:grid;grid-template-columns:60px 1fr 90px;align-items:center;gap:7px;}\n.pollen-nm{font-size:.73rem;font-weight:600;color:var(--t2);}\n.pollen-bar-track{height:6px;border-radius:3px;background:rgba(255,255,255,0.07);overflow:hidden;}\n.pollen-bar-fill{height:100%;border-radius:3px;transition:width .5s;}\n.pollen-lbl2{font-size:.61rem;font-weight:700;text-align:right;}\n.pollen-empty{color:var(--t3);font-size:.72rem;flex:1;display:flex;align-items:center;justify-content:center;text-align:center;}\n.pollen-text{font-size:.56rem;color:var(--t3);line-height:1.5;flex-shrink:0;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}\n/* Indoor */\n.aq-rows{display:flex;flex-direction:column;gap:4px;flex:1;min-height:0;justify-content:center;}\n.aq-row{display:flex;align-items:center;gap:8px;padding:5px 9px;border-radius:8px;}\n.aq-ico{font-size:1rem;width:20px;text-align:center;flex-shrink:0;}\n.aq-info{flex:1;min-width:0;}\n.aq-key{font-size:.56rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--t3);}\n.aq-val2{font-size:.9rem;font-weight:800;line-height:1.1;}\n.aq-sub2{font-size:.56rem;margin-top:1px;}\n.aq-badge{font-size:.62rem;font-weight:700;padding:2px 7px;border-radius:12px;flex-shrink:0;}\n/* Water + Moon */\n.extra-wrap{display:flex;flex-direction:column;gap:5px;flex:1;min-height:0;}\n.water-card{flex:1;display:flex;flex-direction:column;justify-content:center;gap:3px;padding:7px 10px;border-radius:9px;background:rgba(96,165,250,.04);border:1px solid rgba(96,165,250,.09);}\n.water-big{font-size:2rem;font-weight:900;line-height:1;letter-spacing:-1px;}\n.water-big sup{font-size:.9rem;vertical-align:super;font-weight:600;}\n.water-sub{font-size:.56rem;color:var(--t3);}\n.moon-card{flex:1;display:flex;flex-direction:column;justify-content:center;gap:2px;padding:7px 10px;border-radius:9px;background:rgba(245,158,11,.03);border:1px solid rgba(245,158,11,.08);}\n.moon-ico{font-size:1.8rem;line-height:1;}.moon-name{font-size:.73rem;font-weight:600;color:var(--t2);}\n.moon-next{font-size:.58rem;color:var(--t3);}\n</style>\n</head>\n<body>\n<div class="page">\n  <div class="hdr">\n    <div class="hdr-logo"><div class="hdr-dot"></div><div class="hdr-name">Bromma V&#228;der</div></div>\n    <div class="hdr-clock" id="clock">--:--</div>\n    <div class="hdr-right"><div id="hdr-date">--</div><div id="hdr-updated">Laddar...</div></div>\n  </div>\n  <div class="body">\n    <div class="top-row" id="top-row"><div style="grid-column:1/-1;display:flex;align-items:center;justify-content:center;color:#1a2030;">Laddar...</div></div>\n    <div class="bot-row" id="bot-row"></div>\n  </div>\n</div>\n<script>\nfunction getMoonPhase(){\n  var kn=Date.UTC(2000,0,6,18,14,0),lu=29.53058867*86400000;\n  var ph=((Date.now()-kn)%lu+lu)%lu,days=ph/86400000,p=days/29.53058867;\n  var E=[\'&#x1F311;\',\'&#x1F312;\',\'&#x1F313;\',\'&#x1F314;\',\'&#x1F315;\',\'&#x1F316;\',\'&#x1F317;\',\'&#x1F318;\'];\n  var N=[\'Nym\\u00e5ne\',\'Tilltagande sk\\u00e4r\',\'Halfm\\u00e5ne \\u2191\',\'Gibbs\\u00f6s \\u2191\',\'Fullm\\u00e5ne\',\'Gibbs\\u00f6s \\u2193\',\'Halfm\\u00e5ne \\u2193\',\'Avtagande sk\\u00e4r\'];\n  var i=p<.0625?0:p<.1875?1:p<.3125?2:p<.4375?3:p<.5625?4:p<.6875?5:p<.8125?6:p<.9375?7:0;\n  var dtf=days<14.77?(14.77-days):(29.53-days+14.77),dtn=29.53-days;\n  return {emoji:E[i],name:N[i],nextTxt:(dtn<dtf?\'Nym\\u00e5ne om \'+Math.round(dtn):\' Fullm\\u00e5ne om \'+Math.round(dtf))+\' dagar\'};\n}\nfunction pressureSparkline(h){\n  if(!h||h.length<2)return \'\';\n  var W=175,H=28,mn=Math.min.apply(null,h)-.5,mx=Math.max.apply(null,h)+.5,rng=mx-mn||1;\n  var pts=h.map(function(p,i){return ((i/(h.length-1))*W).toFixed(1)+\',\'+(H-((p-mn)/rng)*H).toFixed(1);}).join(\' \');\n  var tr=h[h.length-1]-h[0],col=tr>.5?\'#34d399\':tr<-.5?\'#f87171\':\'#94a3b8\';\n  var txt=tr>.5?\'\\u2191 Stigande\':tr<-.5?\'\\u2193 Fallande\':\'\\u2192 Stabilt\';\n  return \'<div class="prs-lbl">Lufttryck 12h</div>\'\n    +\'<svg width="\'+W+\'" height="\'+H+\'" viewBox="0 0 \'+W+\' \'+H+\'" style="display:block;overflow:visible">\'\n    +\'<polyline points="\'+pts+\'" fill="none" stroke="\'+col+\'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\'\n    +\'<div style="font-size:.59rem;color:\'+col+\';margin-top:2px;">\'+txt+\' \\u00b7 \'+h[h.length-1]+\' hPa</div>\';\n}\nfunction pm25Color(v){return v<12?\'#34d399\':v<35?\'#f59e0b\':v<55?\'#ea580c\':\'#ef4444\';}\nfunction pm25Label(v){return v<12?\'Bra\':v<35?\'M\\u00e5ttlig\':\'D\\u00e5lig\';}\nfunction algColor(v){return v<=1?\'#34d399\':v<=2?\'#65a30d\':v<=3?\'#f59e0b\':v<=4?\'#ea580c\':\'#ef4444\';}\nfunction algLabel(v){return[\'\',\'Utm\\u00e4rkt\',\'Bra\',\'Till\\u00e5tlig\',\'D\\u00e5lig\',\'V\\u00e4ldigt d\\u00e5lig\'][Math.min(Math.round(v),5)]||\'\';}\nfunction humColor(v){return v>=40&&v<=60?\'#34d399\':v>=30&&v<=70?\'#f59e0b\':\'#ef4444\';}\nfunction fanModeLabel(m){var MAP={\'auto\':\'Auto\',\'allergen\':\'Allergen\',\'sleep\':\'S\\u00f6mn\',\'speed_1\':\'Hastighet 1\',\'speed_2\':\'Hastighet 2\',\'speed_3\':\'Hastighet 3\',\'turbo\':\'Turbo\'};return MAP[m]||m||\'\';}\n\nfunction setWindyLayer(layer){\n  var base=\'https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=7&level=surface&overlay=\'+layer+\'&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1\';\n  var f=document.getElementById(\'windy-frame\');\n  if(f)f.src=base;\n  [\'rain\',\'wind\',\'waves\',\'pm2p5\'].forEach(function(l){\n    var b=document.getElementById(\'wb-\'+l);\n    if(b)b.classList.toggle(\'active\',l===layer);\n  });\n}\nfunction setPollenLayer(layer){\n  var base=\'https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=6&level=surface&overlay=\'+layer+\'&product=ecmwf&menu=&message=&marker=true&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1\';\n  var f=document.getElementById(\'pollen-frame\');\n  if(f)f.src=base;\n  [\'pollenTree\',\'pollenGrass\',\'pollenRagweed\'].forEach(function(l){\n    var b=document.getElementById(\'pb-\'+l);\n    if(b)b.classList.toggle(\'active\',l===layer);\n  });\n}\nasync function fetchAll(){\n  var [w,wn,pol,water,indoor]=await Promise.all([\n    fetch(\'/weather/api\').then(r=>r.json()).catch(()=>null),\n    fetch(\'/weather/warnings\').then(r=>r.json()).catch(()=>[]),\n    fetch(\'/weather/pollen\').then(r=>r.json()).catch(()=>({items:[],text:\'\'})),\n    fetch(\'/weather/water\').then(r=>r.json()).catch(()=>null),\n    fetch(\'/weather/indoor\').then(r=>r.json()).catch(()=>null),\n  ]);\n  if(!w||w.error)return;\n  render(w,wn||[],pol||{items:[],text:\'\'},water||null,indoor||null);\n  document.getElementById(\'hdr-updated\').textContent=\'Uppdaterad \'+w.updated;\n}\n\nfunction render(w,warnings,pollen,water,indoor){\n  var cur=w.current;\n  var snowRow=cur.snow_depth>0?\'<div class="stat"><span class="sk">\\u2744 Sn\\u00f6djup</span><span class="sv">\'+cur.snow_depth+\' cm</span></div>\':\'\';\n\n  document.getElementById(\'top-row\').innerHTML=\n    \'<div class="panel"><div class="pi">\'\n    +\'<div class="lbl">Just nu \\u00b7 Bromma</div>\'\n    +\'<div class="cur-hero"><div class="cur-icon">\'+cur.icon+\'</div>\'\n    +\'<div><div class="cur-temp">\'+cur.temp+\'<sup>\\u00b0</sup></div>\'\n    +\'<div class="cur-feels">K\\u00e4nns som \'+cur.feels_like+\'\\u00b0</div></div></div>\'\n    +\'<div class="cur-desc">\'+cur.desc+\'</div>\'\n    +\'<div class="stats">\'\n    +\'<div class="stat"><span class="sk"><span style="display:inline-block;transform:rotate(\'+cur.wind_dir_deg+\'deg);margin-right:3px">\\u2191</span>Vind</span><span class="sv">\'+cur.wind_speed+\' m/s \'+cur.wind_dir+\'</span></div>\'\n    +\'<div class="stat"><span class="sk">Byar</span><span class="sv">\'+cur.wind_gust+\' m/s</span></div>\'\n    +\'<div class="stat"><span class="sk">Fuktighet</span><span class="sv">\'+cur.humidity+\'%</span></div>\'\n    +\'<div class="stat"><span class="sk">Regnchans</span><span class="sv">\'+cur.precip_prob+\'%</span></div>\'\n    +(cur.uv>0?\'<div class="stat"><span class="sk">UV</span><span class="sv">\'+cur.uv+\'</span></div>\':\'\')\n    +snowRow+\'</div>\'\n    +\'<div class="sun-grid">\'\n    +\'<div class="sun-cell"><span class="ico">&#x1F305;</span><div><div class="sg">Soluppg\\u00e5ng</div><div class="st">\'+cur.sunrise+\'</div></div></div>\'\n    +\'<div class="sun-cell"><span class="ico">&#x1F307;</span><div><div class="sg">Solnedg\\u00e5ng</div><div class="st">\'+cur.sunset+\'</div></div></div>\'\n    +\'</div><div class="prs-wrap">\'+pressureSparkline(w.pressure_history)+\'</div>\'\n    +\'</div></div>\'\n    +\'<div class="panel" style="display:flex;flex-direction:column;">\'\n    +\'<div style="padding:6px 10px 4px;display:flex;align-items:center;gap:5px;flex-shrink:0;">\'\n    +\'<span style="font-size:.54rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:#475569;flex:1;">V\u00e4derkarta</span>\'\n    +\'<button class="wb active" id="wb-rain" data-layer="rain" onclick="setWindyLayer(this.dataset.layer)">Regn</button>\'\n    +\'<button class="wb" id="wb-wind" data-layer="wind" onclick="setWindyLayer(this.dataset.layer)">Vind</button>\'\n    +\'<button class="wb" id="wb-waves" data-layer="waves" onclick="setWindyLayer(this.dataset.layer)">V\u00e5gor</button>\'\n    +\'<button class="wb" id="wb-pm2p5" data-layer="pm2p5" onclick="setWindyLayer(this.dataset.layer)">PM2.5</button>\'\n    +\'</div>\'\n    +\'<div class="map-frame" style="flex:1;min-height:0;">\'\n    +\'<iframe id="windy-frame" src="https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=7&level=surface&overlay=rain&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1" allowfullscreen style="width:100%;height:100%;border:none;display:block;"></iframe>\'\n    +\'</div></div>\'\n    +\'<div class="panel" style="display:flex;flex-direction:column;">\'\n    +\'<div style="padding:6px 10px 4px;display:flex;align-items:center;gap:5px;flex-shrink:0;">\'\n    +\'<span style="font-size:.54rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:#475569;flex:1;">Pollenkarta</span>\'\n    +\'<button class="wb active" id="pb-pollenTree" data-layer="pollenTree" onclick="setPollenLayer(this.dataset.layer)">Tr\u00e4d</button>\'\n    +\'<button class="wb" id="pb-pollenGrass" data-layer="pollenGrass" onclick="setPollenLayer(this.dataset.layer)">Gr\u00e4s</button>\'\n    +\'<button class="wb" id="pb-pollenRagweed" data-layer="pollenRagweed" onclick="setPollenLayer(this.dataset.layer)">Ambrosia</button>\'\n    +\'</div>\'\n    +\'<div class="map-frame" style="flex:1;min-height:0;">\'\n    +\'<iframe id="pollen-frame" src="https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=6&level=surface&overlay=pollenTree&product=ecmwf&menu=&message=&marker=true&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1" allowfullscreen style="width:100%;height:100%;border:none;display:block;"></iframe>\'\n    +\'</div></div>\'\n    +\'<div class="panel"><div class="pi"><div class="lbl">Timsvis \\u00b7 12h</div><div class="hour-list">\'\n    +w.hourly.slice(0,12).map(function(h,i){\n      return \'<div class="hour-row\'+(i===0?\' now\':\'\')+\'"><div class="ht">\'+(i===0?\'Nu\':h.time)+\'</div><div class="hi">\'+h.icon+\'</div><div class="hte">\'+h.temp+\'\\u00b0</div><div class="hr">\'+(h.precip_prob>0?h.precip_prob+\'%\':\'\')+\'</div></div>\';\n    }).join(\'\')+\'</div></div></div>\';\n\n  var warnHtml=warnings.length?\'<div class="warn-list">\'+warnings.map(function(wn){\n    var cls={orange:\'orange\',red:\'red\',yellow:\'yellow\'}[wn.severity]||\'default\';\n    return \'<div class="warn-strip \'+cls+\'"><span>\\u26a0</span><span class="wt">\'+wn.title+\'</span>\'+(wn.text?\'<span class="wx">\\u2014 \'+wn.text.substring(0,90)+\'</span>\':\'\')+\'</div>\';\n  }).join(\'\')+\'</div>\':\'\';\n\n  /* Pollen — compact rows */\n  var polItems=(pollen&&pollen.items)||[];\n  var pollenHtml=polItems.length===0\n    ?\'<div class="pollen-empty">\'+(pollen&&pollen.text?pollen.text:\'Inga f\\u00f6rh\\u00f6jda pollenniv\\u00e5er\')+\'</div>\'\n    :\'<div class="pollen-rows">\'+polItems.map(function(p){\n      var pct=Math.round((p.level/7)*100);\n      return \'<div class="pollen-row2">\'\n        +\'<div class="pollen-nm">\'+p.name+\'</div>\'\n        +\'<div class="pollen-bar-track"><div class="pollen-bar-fill" style="width:\'+pct+\'%;background:\'+p.color+\';"></div></div>\'\n        +\'<div class="pollen-lbl2" style="color:\'+p.color+\';">\'+p.label+\'</div>\'\n        +\'</div>\';\n    }).join(\'\')+\'</div>\'+(pollen&&pollen.text?\'<div class="pollen-text">\'+pollen.text+\'</div>\':\'\');\n\n  /* Indoor */\n  var indoorHtml;\n  if(indoor&&Object.keys(indoor).length>0){\n    var hC=indoor.humidity!=null?humColor(indoor.humidity):\'#94a3b8\';\n    var pC=indoor.pm25!=null?pm25Color(indoor.pm25):\'#94a3b8\';\n    var aC=indoor.allergen!=null?algColor(indoor.allergen):\'#94a3b8\';\n    var warnWater=indoor.water_level!=null&&indoor.water_level<15;\n    var fanLabel=fanModeLabel(indoor.fan_mode||\'\');\n    var humTarget=indoor.humidity_target!=null?\' / \'+indoor.humidity_target+\'%\':\'\';\n    var humStatus=indoor.humidity!=null?(indoor.humidity>=40&&indoor.humidity<=60?\'Bra niv\\u00e5\':indoor.humidity<40?\'F\\u00f6r torr\':\'F\\u00f6r fuktig\'):\'\';\n    indoorHtml=\'<div class="aq-rows">\'\n      /* Temp */\n      +\'<div class="aq-row" style="background:rgba(96,165,250,.06);border:1px solid rgba(96,165,250,.1);">\'\n      +\'<div class="aq-ico">&#x1F321;</div><div class="aq-info">\'\n      +\'<div class="aq-key">Temperatur</div>\'\n      +(indoor.temp!=null?\'<div class="aq-val2" style="color:#60a5fa;">\'+indoor.temp.toFixed(1)+\'\\u00b0C</div>\':\'<div class="aq-val2" style="color:#475569;">\\u2013</div>\')\n      +\'<div class="aq-sub2" style="color:var(--t3);">Sovrum</div></div></div>\'\n      /* Humidity */\n      +\'<div class="aq-row" style="background:rgba(34,211,238,.06);border:1px solid rgba(34,211,238,.1);">\'\n      +\'<div class="aq-ico">&#x1F4A7;</div><div class="aq-info">\'\n      +\'<div class="aq-key">Luftfuktighet</div>\'\n      +(indoor.humidity!=null?\'<div class="aq-val2" style="color:\'+hC+\';">\'+Math.round(indoor.humidity)+\'%<span style="font-size:.65rem;font-weight:500;color:var(--t3);">\'+humTarget+\'</span></div><div class="aq-sub2" style="color:\'+hC+\';">\'+humStatus+(indoor.humidifier_action?\' \\u00b7 \'+indoor.humidifier_action:\'\')+\'</div>\':\'<div class="aq-val2">\\u2013</div>\')\n      +\'</div></div>\'\n      /* PM2.5 */\n      +\'<div class="aq-row" style="background:rgba(52,211,153,.06);border:1px solid rgba(52,211,153,.1);">\'\n      +\'<div class="aq-ico">&#x1F32B;</div><div class="aq-info">\'\n      +\'<div class="aq-key">Luftkvalitet PM2.5</div>\'\n      +(indoor.pm25!=null?\'<div class="aq-val2" style="color:\'+pC+\';">\'+indoor.pm25.toFixed(0)+\' \\u03bcg/m\\u00b3</div><div class="aq-sub2" style="color:\'+pC+\';">\'+pm25Label(indoor.pm25)+\'</div>\':\'<div class="aq-val2">\\u2013</div>\')\n      +\'</div></div>\'\n      /* Allergen */\n      +\'<div class="aq-row" style="background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.1);">\'\n      +\'<div class="aq-ico">&#x1F33F;</div><div class="aq-info">\'\n      +\'<div class="aq-key">Allergenindex</div>\'\n      +(indoor.allergen!=null?\'<div class="aq-val2" style="color:\'+aC+\';">\'+indoor.allergen.toFixed(0)+\'/5</div><div class="aq-sub2" style="color:\'+aC+\';">\'+algLabel(indoor.allergen)+\'</div>\':\'<div class="aq-val2">\\u2013</div>\')\n      +\'</div></div>\'\n      /* Fan + Water */\n      +\'<div class="aq-row" style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);">\'\n      +\'<div class="aq-ico">\'+(indoor.fan_on?\'&#x1F300;\':\'&#x23F9;\')+\'</div>\'\n      +\'<div class="aq-info"><div class="aq-key">L\\u00e4ge</div>\'\n      +\'<div class="aq-val2" style="color:var(--t2);font-size:.8rem;">\'+fanLabel+\'</div></div>\'\n      +(indoor.water_level!=null?\'<div class="aq-badge" style="color:\'+(warnWater?\'#f87171\':\'#94a3b8\')+\';background:\'+(warnWater?\'rgba(239,68,68,.12)\':\'rgba(255,255,255,.05)\')+\';border:1px solid \'+(warnWater?\'rgba(239,68,68,.3)\':\'rgba(255,255,255,.1)\')+\';">\'+(warnWater?\'\\u26a0\\ufe0f \':\'\\uD83D\\uDCA7 \')+Math.round(indoor.water_level)+\'%</div>\':\'\')\n      +\'</div>\'\n      +\'</div>\';\n  } else {\n    indoorHtml=\'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--t3);font-size:.72rem;">Ingen data fr\\u00e5n luftrenaren</div>\';\n  }\n\n  var moon=getMoonPhase();\n  var wc=water&&water.temp!=null?(water.temp>=20?\'#f59e0b\':water.temp>=15?\'#34d399\':water.temp>=5?\'#22d3ee\':\'#60a5fa\'):\'#60a5fa\';\n  var waterHtml=water&&water.temp!=null\n    ?\'<div class="water-big" style="color:\'+wc+\';">\'+water.temp.toFixed(1)+\'<sup>\\u00b0C</sup></div><div class="water-sub">\'+(water.station||\'\')+\'</div><div class="water-sub">\'+(water.updated||\'\')+\'</div>\'\n    :\'<div class="water-big" style="color:#475569;font-size:1.3rem;">\\u2013</div><div class="water-sub">Ej tillg\\u00e4nglig</div>\';\n\n  document.getElementById(\'bot-row\').innerHTML=\n    \'<div class="panel"><div class="pi"><div class="lbl">5-Dagars prognos</div><div class="daily-wrap">\'\n    +w.daily.map(function(d){\n      return \'<div class="day-row"><div class="dn">\'+d.day+\'</div><div class="di">\'+d.icon+\'</div><div class="dd">\'+d.desc+\'</div><div><span class="hi2">\\u2191\'+d.max+\'\\u00b0</span><span class="lo2">\\u2193\'+d.min+\'\\u00b0</span></div></div>\';\n    }).join(\'\')+\'</div>\'+warnHtml+\'</div></div>\'\n    +\'<div class="panel"><div class="pi"><div class="lbl">&#x1F338; Pollen \\u00b7 Stockholm</div>\'+pollenHtml+\'</div></div>\'\n    +\'<div class="panel"><div class="pi"><div class="lbl">&#x1F3E0; Inomhus \\u00b7 Sovrum</div>\'+indoorHtml+\'</div></div>\'\n    +\'<div class="panel"><div class="pi"><div class="lbl">Vatten &amp; M\\u00e5ne</div>\'\n    +\'<div class="extra-wrap">\'\n    +\'<div class="water-card"><div class="lbl">&#x1F30A; Vattentemp</div>\'+waterHtml+\'</div>\'\n    +\'<div class="moon-card"><div class="lbl">&#x1F319; M\\u00e5nfas</div>\'\n    +\'<div class="moon-ico">\'+moon.emoji+\'</div><div class="moon-name">\'+moon.name+\'</div><div class="moon-next">\'+moon.nextTxt+\'</div>\'\n    +\'</div></div></div></div>\';\n}\n\nvar DAYS=[\'\\u00d6n\',\'M\\u00e5n\',\'Tis\',\'Ons\',\'Tor\',\'Fre\',\'L\\u00f6r\'];\nvar MONTHS=[\'jan\',\'feb\',\'mar\',\'apr\',\'maj\',\'jun\',\'jul\',\'aug\',\'sep\',\'okt\',\'nov\',\'dec\'];\nfunction tick(){var d=new Date();document.getElementById(\'clock\').textContent=String(d.getHours()).padStart(2,\'0\')+\':\'+String(d.getMinutes()).padStart(2,\'0\');}\nfunction setDate(){var d=new Date();document.getElementById(\'hdr-date\').textContent=DAYS[d.getDay()]+\' \'+d.getDate()+\' \'+MONTHS[d.getMonth()];}\nfetchAll();tick();setDate();setInterval(tick,1000);setInterval(fetchAll,5*60*1000);\n</script>\n</body>\n</html>'
