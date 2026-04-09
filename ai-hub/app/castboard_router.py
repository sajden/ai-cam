"""castboard_router.py — Combined TV castboard: weather + desk activity."""
import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(prefix="/castboard", tags=["castboard"])

CASTBOARD_CAST_URL = os.getenv(
    "CASTBOARD_CAST_URL", "http://192.168.50.215:8080/castboard"
).strip()

_HTML = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Castboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#06080f;--panel:rgba(255,255,255,0.038);--border:rgba(255,255,255,0.075);
  --t1:#e2e8f0;--t2:#94a3b8;--t3:#475569;
  --accent:#60a5fa;--amber:#f59e0b;--green:#34d399;--red:#f87171;--cyan:#22d3ee;
}
html,body{height:100%;width:100%;margin:0;padding:0;overflow:hidden;background:var(--bg);color:var(--t1);font-family:'Inter',system-ui,sans-serif;-webkit-font-smoothing:antialiased;}
*{box-sizing:border-box;}
.page{display:grid;grid-template-rows:46px 1fr;height:100vh;}
.hdr{display:flex;justify-content:space-between;align-items:center;padding:0 18px;background:rgba(255,255,255,0.018);border-bottom:1px solid var(--border);}
.hdr-logo{display:flex;align-items:center;gap:9px;}
.hdr-dot{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);animation:blink 3s ease-in-out infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.hdr-name{font-size:.65rem;font-weight:700;letter-spacing:.25em;text-transform:uppercase;color:var(--t3);}
.hdr-clock{font-size:1.55rem;font-weight:300;color:var(--t1);letter-spacing:.04em;}
.hdr-right{font-size:.62rem;color:var(--t3);text-align:right;line-height:1.7;}
.body{display:grid;grid-template-rows:60fr 40fr;gap:7px;padding:7px;min-height:0;}
.top-row{display:grid;grid-template-columns:235px 1fr 315px 182px;gap:7px;min-height:0;}
.bot-row{display:grid;grid-template-columns:205px 165px 195px 150px 1fr;gap:7px;min-height:0;}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;min-height:0;}
.pi{padding:11px 13px;height:100%;display:flex;flex-direction:column;gap:5px;min-height:0;overflow:hidden;}
.lbl{font-size:.54rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--t3);flex-shrink:0;}
/* Weather */
.cur-hero{display:flex;align-items:center;gap:10px;flex-shrink:0;}
.cur-icon{font-size:2.8rem;line-height:1;flex-shrink:0;}
.cur-temp{font-size:3.5rem;font-weight:900;line-height:1;color:#fff;letter-spacing:-3px;}
.cur-temp sup{font-size:1.6rem;color:var(--accent);letter-spacing:0;vertical-align:super;}
.cur-feels{font-size:.63rem;color:var(--t3);margin-top:2px;}
.cur-desc{font-size:.8rem;font-weight:600;color:var(--t2);flex-shrink:0;}
.stats{display:flex;flex-direction:column;gap:2px;flex:1;min-height:0;}
.stat{display:flex;justify-content:space-between;align-items:center;padding:3px 8px;border-radius:6px;background:rgba(255,255,255,0.02);font-size:.69rem;}
.sk{color:var(--t3);}.sv{color:var(--t2);font-weight:600;}
.sun-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex-shrink:0;}
.sun-cell{display:flex;align-items:center;gap:5px;padding:4px 8px;border-radius:7px;background:rgba(245,158,11,.05);border:1px solid rgba(245,158,11,.1);}
.sun-cell .ico{font-size:.9rem;}.sun-cell .st{font-size:.82rem;font-weight:700;color:var(--amber);line-height:1;}.sun-cell .sg{font-size:.48rem;color:var(--t3);margin-top:1px;}
.prs-wrap{flex-shrink:0;}
.prs-lbl{font-size:.5rem;color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:2px;}
.map-frame{flex:1;overflow:hidden;min-height:0;}
.map-frame iframe{width:100%;height:100%;border:none;display:block;}
.wb{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:#94a3b8;font-size:.53rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:10px;cursor:pointer;font-family:inherit;transition:all .15s;}
.wb.active{background:rgba(96,165,250,.15);border-color:rgba(96,165,250,.35);color:#60a5fa;}
.wb:hover{background:rgba(255,255,255,.09);}
.hour-list{display:flex;flex-direction:column;flex:1;gap:1px;min-height:0;}
.hour-row{display:grid;grid-template-columns:32px 18px 1fr 26px;align-items:center;gap:3px;padding:2px 6px;border-radius:5px;font-size:.67rem;flex:1;}
.hour-row.now{background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.15);}
.ht{color:var(--t3);font-weight:600;font-size:.59rem;}.hi{font-size:.85rem;text-align:center;}.hte{color:var(--t2);font-weight:700;}.hr{color:var(--t3);font-size:.57rem;text-align:right;}
.daily-wrap{display:flex;flex-direction:column;flex:1;min-height:0;gap:1px;}
.day-row{display:grid;grid-template-columns:32px 20px 60px;align-items:center;gap:5px;padding:0 8px;flex:1;border-radius:5px;}
.dn{font-weight:700;color:var(--t2);font-size:.72rem;}.di{font-size:.82rem;text-align:center;}
.day-temps{display:flex;gap:4px;align-items:center;}
.hi2{color:var(--red);font-weight:700;font-size:.69rem;}.lo2{color:var(--accent);font-size:.69rem;}
.warn-list{display:flex;flex-direction:column;gap:2px;flex-shrink:0;}
.warn-strip{display:flex;align-items:center;gap:6px;padding:3px 8px;border-radius:5px;border:1px solid;font-size:.63rem;}
.warn-strip.orange{background:rgba(251,146,60,.06);border-color:rgba(251,146,60,.2);}
.warn-strip.red{background:rgba(239,68,68,.06);border-color:rgba(239,68,68,.2);}
.warn-strip.yellow{background:rgba(234,179,8,.05);border-color:rgba(234,179,8,.15);}
.warn-strip.default{background:rgba(255,255,255,.02);border-color:rgba(255,255,255,.06);}
.wt{font-weight:600;color:var(--t2);}
.pollen-rows{display:flex;flex-direction:column;gap:6px;flex:1;min-height:0;justify-content:center;}
.pollen-row2{display:grid;grid-template-columns:58px 1fr 88px;align-items:center;gap:6px;}
.pollen-nm{font-size:.72rem;font-weight:600;color:var(--t2);}
.pollen-bar-track{height:6px;border-radius:3px;background:rgba(255,255,255,0.07);overflow:hidden;}
.pollen-bar-fill{height:100%;border-radius:3px;}
.pollen-lbl2{font-size:.6rem;font-weight:700;text-align:right;}
.pollen-empty{color:var(--t3);font-size:.72rem;flex:1;display:flex;align-items:center;justify-content:center;text-align:center;}
.aq-rows{display:flex;flex-direction:column;gap:4px;flex:1;min-height:0;justify-content:center;}
.aq-row{display:flex;align-items:center;gap:8px;padding:5px 9px;border-radius:8px;}
.aq-ico{font-size:1rem;width:20px;text-align:center;flex-shrink:0;}
.aq-info{flex:1;min-width:0;}
.aq-key{font-size:.56rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--t3);}
.aq-val2{font-size:.9rem;font-weight:800;line-height:1.1;}
.aq-sub2{font-size:.56rem;margin-top:1px;}
.aq-badge{font-size:.62rem;font-weight:700;padding:2px 7px;border-radius:12px;flex-shrink:0;}
.extra-wrap{display:flex;flex-direction:column;gap:5px;flex:1;min-height:0;}
.water-card{flex:1;display:flex;flex-direction:column;justify-content:center;gap:3px;padding:7px 10px;border-radius:9px;background:rgba(96,165,250,.04);border:1px solid rgba(96,165,250,.09);}
.water-big{font-size:2rem;font-weight:900;line-height:1;letter-spacing:-1px;}
.water-big sup{font-size:.9rem;vertical-align:super;font-weight:600;}
.water-sub{font-size:.56rem;color:var(--t3);}
.moon-card{flex:1;display:flex;flex-direction:column;justify-content:center;gap:2px;padding:7px 10px;border-radius:9px;background:rgba(245,158,11,.03);border:1px solid rgba(245,158,11,.08);}
.moon-ico{font-size:1.8rem;line-height:1;}.moon-name{font-size:.73rem;font-weight:600;color:var(--t2);}
.moon-next{font-size:.58rem;color:var(--t3);}
/* ── Desk panel ── */
.desk-status{display:flex;align-items:center;gap:9px;flex-shrink:0;}
.desk-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;}
.desk-dot.at{background:#66bb6a;box-shadow:0 0 10px #66bb6a88;}
.desk-dot.away{background:#ffa726;box-shadow:0 0 10px #ffa72688;}
.desk-status-txt{font-size:1.4rem;font-weight:700;}
.desk-status-txt.at{color:#66bb6a;}.desk-status-txt.away{color:#ffa726;}
.desk-sub{font-size:.78rem;color:var(--t3);padding-bottom:4px;flex-shrink:0;}
.desk-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px 10px;flex-shrink:0;}
.dk{display:flex;flex-direction:column;gap:2px;}
.dk-val{font-size:1.15rem;font-weight:800;color:#90caf9;font-variant-numeric:tabular-nums;line-height:1.1;}
.dk-lbl{font-size:.52rem;color:var(--t3);text-transform:uppercase;letter-spacing:.07em;}
/* ── Desk week panel ── */
.dw-chart{display:flex;align-items:flex-end;gap:4px;flex:1;min-height:0;padding-top:4px;}
.dwrap{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end;gap:3px;}
.dbar{width:100%;border-radius:2px 2px 0 0;min-height:2px;}
.dval{font-size:.58rem;color:#888;text-align:center;}
.dlbl{font-size:.58rem;color:#666;text-align:center;}.dlbl.today{color:#90caf9;}
.dw-totals{display:flex;gap:14px;flex-shrink:0;padding-top:7px;border-top:1px solid #1a1a32;margin-top:2px;}
.dt-item{display:flex;flex-direction:column;gap:2px;}
.dt-val{font-size:1.35rem;font-weight:800;color:#ce93d8;font-variant-numeric:tabular-nums;}
.dt-lbl{font-size:.54rem;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;}

/* ── Mobile ── */
@media(max-width:900px){
  html,body{overflow-y:auto;height:auto;}
  .page{grid-template-rows:42px auto;height:auto;}
  .body{grid-template-rows:none;height:auto;overflow:visible;}
  .top-row{grid-template-columns:1fr 1fr;}
  /* hide windy map (2nd child) */
  .top-row .panel:nth-child(2){display:none;}
  /* hourly (4th child, 3rd visible) full width */
  .top-row .panel:nth-child(4){grid-column:1/-1;}
  .bot-row{grid-template-columns:1fr 1fr;}
  /* desk week (5th child) full width */
  .bot-row .panel:nth-child(5){grid-column:1/-1;}
  /* auto height panels */
  .panel{min-height:140px;height:auto;}
  .pi{height:auto;}
  /* slightly larger readable text */
  .lbl{font-size:.6rem;}
  .stat{font-size:.75rem;}
  .dk-val{font-size:1rem;}
  .dk-lbl{font-size:.58rem;}
  .hdr-name{font-size:.58rem;}
  .hdr-right{font-size:.58rem;}
}
@media(max-width:480px){
  .top-row,.bot-row{grid-template-columns:1fr;}
  .top-row .panel:nth-child(4){grid-column:auto;}
  .bot-row .panel:nth-child(5){grid-column:auto;}
  .panel{min-height:120px;}
}
</style>
</head>
<body>
<div class="page">
  <div class="hdr">
    <div class="hdr-logo"><div class="hdr-dot"></div><div class="hdr-name">Bromma &middot; Skrivbord</div></div>
    <div class="hdr-clock" id="clock">--:--</div>
    <div class="hdr-right" style="display:flex;align-items:center;gap:12px;">
      <div style="text-align:right"><div id="hdr-date">--</div><div id="hdr-updated">Laddar...</div></div>
      <button id="cast-btn" onclick="castToTV()" title="Casta till TV" style="background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:#94a3b8;font-size:.75rem;font-weight:600;padding:4px 10px;border-radius:8px;cursor:pointer;font-family:inherit;transition:all .2s;display:flex;align-items:center;gap:5px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 8.5A12.5 12.5 0 0 1 14.5 21"/><path d="M2 12.5A8.5 8.5 0 0 1 10.5 21"/><path d="M2 16.5A4.5 4.5 0 0 1 6.5 21"/><circle cx="2" cy="21" r="1" fill="currentColor"/><rect x="14" y="3" width="8" height="6" rx="1"/><path d="M14 6h8"/></svg>
        Casta
      </button>
    </div>
  </div>
  <div class="body">
    <div class="top-row" id="top-row"><div style="grid-column:1/-1;display:flex;align-items:center;justify-content:center;color:#1a2030;">Laddar...</div></div>
    <div class="bot-row" id="bot-row"></div>
  </div>
</div>
<script>
// ── Utilities ──────────────────────────────────────────────────────────
function getMoonPhase(){
  var kn=Date.UTC(2000,0,6,18,14,0),lu=29.53058867*86400000;
  var ph=((Date.now()-kn)%lu+lu)%lu,days=ph/86400000,p=days/29.53058867;
  var E=['&#x1F311;','&#x1F312;','&#x1F313;','&#x1F314;','&#x1F315;','&#x1F316;','&#x1F317;','&#x1F318;'];
  var N=['Nym\\u00e5ne','Tilltagande sk\\u00e4r','Halfm\\u00e5ne \\u2191','Gibbs\\u00f6s \\u2191','Fullm\\u00e5ne','Gibbs\\u00f6s \\u2193','Halfm\\u00e5ne \\u2193','Avtagande sk\\u00e4r'];
  var i=p<.0625?0:p<.1875?1:p<.3125?2:p<.4375?3:p<.5625?4:p<.6875?5:p<.8125?6:7;
  var dtf=days<14.77?(14.77-days):(29.53-days+14.77),dtn=29.53-days;
  return {emoji:E[i],name:N[i],nextTxt:(dtn<dtf?'Nym\\u00e5ne om '+Math.round(dtn):'Fullm\\u00e5ne om '+Math.round(dtf))+' dagar'};
}
function pressureSparkline(h){
  if(!h||h.length<2)return '';
  var W=170,H=26,mn=Math.min.apply(null,h)-.5,mx=Math.max.apply(null,h)+.5,rng=mx-mn||1;
  var pts=h.map(function(p,i){return ((i/(h.length-1))*W).toFixed(1)+','+(H-((p-mn)/rng)*H).toFixed(1);}).join(' ');
  var tr=h[h.length-1]-h[0],col=tr>.5?'#34d399':tr<-.5?'#f87171':'#94a3b8';
  var txt=tr>.5?'\\u2191 Stigande':tr<-.5?'\\u2193 Fallande':'\\u2192 Stabilt';
  return '<div class="prs-lbl">Lufttryck 12h</div>'
    +'<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" style="display:block;overflow:visible">'
    +'<polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    +'<div style="font-size:.58rem;color:'+col+';margin-top:2px;">'+txt+' \\u00b7 '+h[h.length-1]+' hPa</div>';
}
function pm25Color(v){return v<12?'#34d399':v<35?'#f59e0b':v<55?'#ea580c':'#ef4444';}
function pm25Label(v){return v<12?'Bra':v<35?'M\\u00e5ttlig':'D\\u00e5lig';}
function algColor(v){return v<=1?'#34d399':v<=2?'#65a30d':v<=3?'#f59e0b':v<=4?'#ea580c':'#ef4444';}
function algLabel(v){return['','Utm\\u00e4rkt','Bra','Till\\u00e5tlig','D\\u00e5lig','V\\u00e4ldigt d\\u00e5lig'][Math.min(Math.round(v),5)]||'';}
function humColor(v){return v>=40&&v<=60?'#34d399':v>=30&&v<=70?'#f59e0b':'#ef4444';}
function fanModeLabel(m){var MAP={auto:'Auto',allergen:'Allergen',sleep:'S\\u00f6mn',speed_1:'Hastighet 1',speed_2:'Hastighet 2',speed_3:'Hastighet 3',turbo:'Turbo'};return MAP[m]||m||'';}
function setWindyLayer(layer){
  var base='https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=7&level=surface&overlay='+layer+'&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1';
  var f=document.getElementById('windy-frame');
  if(f)f.src=base;
  ['rain','wind','waves','pm2p5'].forEach(function(l){
    var b=document.getElementById('wb-'+l);
    if(b)b.classList.toggle('active',l===layer);
  });
}
function fmtMin(min){
  if(!min||min<=0)return '0 min';
  if(min<60)return min+' min';
  var h=Math.floor(min/60),m=min%60;
  return m>0?h+'h '+m+'m':h+'h';
}
function fmtCount(n){
  if(!n||n<=0)return '0';
  if(n>=1000000)return (n/1000000).toFixed(1).replace('.',',')+' M';
  if(n>=1000)return (n/1000).toFixed(1).replace('.',',')+' k';
  return n.toString();
}
function parseISOtoDate(ts){
  if(!ts)return null;
  var s=ts.replace(' ','T');
  if(!/Z$/.test(s)&&!/[+-]\\d{2}:\\d{2}$/.test(s))s+='Z';
  var d=new Date(s);
  return isNaN(d)?null:d;
}
function toSthlm(d){return new Date(d.getTime()+3600000);}
function totalMinutes(d){return d.getHours()*60+d.getMinutes();}
function shortDay(ds){return new Date(ds+'T12:00:00Z').toLocaleDateString('sv-SE',{weekday:'short',timeZone:'UTC'});}

// ── Desk panel (top row) ───────────────────────────────────────────────
function buildDeskPanel(desk){
  if(!desk)return '<div class="pi"><div class="lbl">&#x1F4BB; Skrivbord</div><div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--t3);font-size:.72rem;">Ingen data</div></div>';
  var st=desk.stats_today||{};
  var isAway=st.currently_away;
  var statusTxt=isAway?'Rast':'Vid skrivbordet';
  var subTxt=isAway?'Borta sedan '+fmtMin(st.away_min):'I str\\u00e4ck: '+fmtMin(st.current_sitting_min);

  // Mini timeline SVG
  var tl=desk.day_timeline||[];
  var sessionStart=st.session_start?parseISOtoDate(st.session_start):null;
  if(tl.length===0&&sessionStart){
    tl=[{type:'at',start:sessionStart.toISOString(),end:new Date().toISOString(),open:true}];
  }
  var tlHtml='';
  if(tl.length>0){
    var W=244,barY=2,barH=18;
    var firstDt=parseISOtoDate(tl[0].start);
    var nowD=new Date();
    var startM=firstDt?Math.max(0,totalMinutes(firstDt)-10):6*60;
    var endM=Math.max(totalMinutes(nowD),startM+60);
    var spanM=endM-startM;
    function xp(dt){return Math.max(0,Math.min(W,((totalMinutes(dt)-startM)/spanM)*W));}
    var parts=['<svg width="'+W+'" height="'+(barY+barH+16)+'" style="display:block;width:100%;flex-shrink:0;">'];
    parts.push('<rect x="0" y="'+barY+'" width="'+W+'" height="'+barH+'" fill="#1a1a32" rx="3"/>');
    for(var i=0;i<tl.length;i++){
      var p=tl[i],s1=parseISOtoDate(p.start),e1=parseISOtoDate(p.end);
      if(!s1||!e1)continue;
      var x1=xp(s1),x2=xp(e1);
      if(x2>x1)parts.push('<rect x="'+x1+'" y="'+barY+'" width="'+(x2-x1)+'" height="'+barH+'" fill="'+(p.type==='at'?'#4fc3f7':'#ff8a65')+'"/>');
    }
    var step=[30,60,120,180].find(function(ss){return spanM/ss<=6;})||60;
    var firstMark=Math.ceil(startM/step)*step;
    for(var m=firstMark;m<=endM;m+=step){
      var xm=((m-startM)/spanM)*W;
      if(xm<14||xm>W-14)continue;
      var hh=Math.floor(m/60)%24,mm=m%60;
      var lbl=String(hh).padStart(2,'0')+':'+String(mm).padStart(2,'0');
      parts.push('<text x="'+xm+'" y="'+(barY+barH+12)+'" text-anchor="middle" font-size="9" fill="#555">'+lbl+'</text>');
    }
    var nx=((totalMinutes(nowD)-startM)/spanM)*W;
    if(nx>=0&&nx<=W)parts.push('<line x1="'+nx+'" x2="'+nx+'" y1="'+(barY-3)+'" y2="'+(barY+barH+2)+'" stroke="#fff" stroke-width="1.5" stroke-dasharray="3,3"/>');
    parts.push('</svg>');
    tlHtml=parts.join('');
  }

  return '<div class="pi">'
    +'<div class="lbl">&#x1F4BB; Skrivbord</div>'
    +'<div class="desk-status">'
    +'<div class="desk-dot '+(isAway?'away':'at')+'"></div>'
    +'<div class="desk-status-txt '+(isAway?'away':'at')+'">'+statusTxt+'</div>'
    +'</div>'
    +'<div class="desk-sub">'+subTxt+'</div>'
    +'<div class="desk-grid">'
    +'<div class="dk"><div class="dk-val">'+fmtMin(st.total_sitting_min)+'</div><div class="dk-lbl">Sitttid</div></div>'
    +'<div class="dk"><div class="dk-val">'+fmtMin(st.longest_sitting_min)+'</div><div class="dk-lbl">L\\u00e4ngsta pass</div></div>'
    +'<div class="dk"><div class="dk-val">'+(st.break_count||0)+'</div><div class="dk-lbl">Raster</div></div>'
    +'<div class="dk"><div class="dk-val">'+fmtCount(st.keypresses||0)+'</div><div class="dk-lbl">Tangenter</div></div>'
    +'<div class="dk"><div class="dk-val">'+fmtCount(st.clicks||0)+'</div><div class="dk-lbl">Klick</div></div>'
    +'<div class="dk"></div>'
    +'</div>'
    +(tlHtml?tlHtml:'')
    +'</div>';
}

// ── Desk week panel (bottom row) ───────────────────────────────────────
function buildDeskWeekPanel(desk){
  if(!desk)return '<div class="pi"><div class="lbl">7 dagar</div></div>';
  var wi=desk.week_input_stats||[];
  var totals=desk.total_input_stats||{};
  var today=new Date().toISOString().slice(0,10);
  var maxVal=Math.max.apply(null,wi.map(function(d){return d.keypresses||0;}));
  if(maxVal<1)maxVal=1;
  var maxH=75;
  var bars=wi.map(function(d){
    var isToday=d.date===today;
    var val=d.keypresses||0;
    var bh=Math.max(val>0?3:1,Math.round((val/maxVal)*maxH));
    return '<div class="dwrap">'
      +'<div class="dval">'+(val>0?fmtCount(val):'')+'</div>'
      +'<div class="dbar" style="height:'+bh+'px;background:'+(isToday?'#9c27b0':'#4a1070')+';"></div>'
      +'<div class="dlbl'+(isToday?' today':'')+'">'+shortDay(d.date)+'</div>'
      +'</div>';
  }).join('');
  var kTot=totals.keypresses||0;
  var cTot=totals.clicks||0;
  return '<div class="pi">'
    +'<div class="lbl">Tangenter / vecka</div>'
    +'<div class="dw-chart">'+bars+'</div>'
    +'<div class="dw-totals">'
    +'<div class="dt-item"><div class="dt-val">'+(kTot>=1000?(kTot/1000).toFixed(0)+'k':kTot)+'</div><div class="dt-lbl">Tot tangenter</div></div>'
    +'<div class="dt-item"><div class="dt-val">'+(cTot>=1000?(cTot/1000).toFixed(0)+'k':cTot)+'</div><div class="dt-lbl">Tot klick</div></div>'
    +'</div>'
    +'</div>';
}

// ── State ──────────────────────────────────────────────────────────────
var _lastWeather=null;
var _lastDesk=null;

// ── Full refresh (weather + desk) ──────────────────────────────────────
async function fetchAll(){
  var [w,wn,pol,water,indoor,desk]=await Promise.all([
    fetch('/weather/api').then(r=>r.json()).catch(()=>null),
    fetch('/weather/warnings').then(r=>r.json()).catch(()=>[]),
    fetch('/weather/pollen').then(r=>r.json()).catch(()=>({items:[],text:''})),
    fetch('/weather/water').then(r=>r.json()).catch(()=>null),
    fetch('/weather/indoor').then(r=>r.json()).catch(()=>null),
    fetch('/desk/api').then(r=>r.json()).catch(()=>null),
  ]);
  if(w&&!w.error){
    _lastWeather={w,wn:wn||[],pol:pol||{items:[],text:''},water:water||null,indoor:indoor||null};
    document.getElementById('hdr-updated').textContent='Uppdaterad '+w.updated;
  }
  if(desk)_lastDesk=desk;
  renderAll();
}

// ── Desk-only refresh (every 30s) ──────────────────────────────────────
async function fetchDeskOnly(){
  var desk=await fetch('/desk/api').then(r=>r.json()).catch(()=>null);
  if(!desk)return;
  _lastDesk=desk;
  var dp=document.getElementById('desk-panel');
  var dwp=document.getElementById('desk-week-panel');
  if(dp)dp.innerHTML=buildDeskPanel(desk);
  if(dwp)dwp.innerHTML=buildDeskWeekPanel(desk);
}

// ── Render all ─────────────────────────────────────────────────────────
function renderAll(){
  if(!_lastWeather)return;
  var cur=_lastWeather.w.current;
  var snowRow=cur.snow_depth>0?'<div class="stat"><span class="sk">\\u2744 Sn\\u00f6djup</span><span class="sv">'+cur.snow_depth+' cm</span></div>':'';

  document.getElementById('top-row').innerHTML=
    // Current weather
    '<div class="panel"><div class="pi">'
    +'<div class="lbl">Just nu \\u00b7 Bromma</div>'
    +'<div class="cur-hero"><div class="cur-icon">'+cur.icon+'</div>'
    +'<div><div class="cur-temp">'+cur.temp+'<sup>\\u00b0</sup></div>'
    +'<div class="cur-feels">K\\u00e4nns som '+cur.feels_like+'\\u00b0</div></div></div>'
    +'<div class="cur-desc">'+cur.desc+'</div>'
    +'<div class="stats">'
    +'<div class="stat"><span class="sk"><span style="display:inline-block;transform:rotate('+cur.wind_dir_deg+'deg);margin-right:3px">\\u2191</span>Vind</span><span class="sv">'+cur.wind_speed+' m/s '+cur.wind_dir+'</span></div>'
    +'<div class="stat"><span class="sk">Byar</span><span class="sv">'+cur.wind_gust+' m/s</span></div>'
    +'<div class="stat"><span class="sk">Fuktighet</span><span class="sv">'+cur.humidity+'%</span></div>'
    +'<div class="stat"><span class="sk">Regnchans</span><span class="sv">'+cur.precip_prob+'%</span></div>'
    +(cur.uv>0?'<div class="stat"><span class="sk">UV</span><span class="sv">'+cur.uv+'</span></div>':'')
    +snowRow+'</div>'
    +'<div class="sun-grid">'
    +'<div class="sun-cell"><span class="ico">&#x1F305;</span><div><div class="sg">Soluppg\\u00e5ng</div><div class="st">'+cur.sunrise+'</div></div></div>'
    +'<div class="sun-cell"><span class="ico">&#x1F307;</span><div><div class="sg">Solnedg\\u00e5ng</div><div class="st">'+cur.sunset+'</div></div></div>'
    +'</div><div class="prs-wrap">'+pressureSparkline(_lastWeather.w.pressure_history)+'</div>'
    +'</div></div>'
    // Windy map
    +'<div class="panel" style="display:flex;flex-direction:column;">'
    +'<div style="padding:6px 10px 4px;display:flex;align-items:center;gap:5px;flex-shrink:0;">'
    +'<span style="font-size:.54rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:#475569;flex:1;">V\\u00e4derkarta</span>'
    +'<button class="wb active" id="wb-rain" data-layer="rain" onclick="setWindyLayer(this.dataset.layer)">Regn</button>'
    +'<button class="wb" id="wb-wind" data-layer="wind" onclick="setWindyLayer(this.dataset.layer)">Vind</button>'
    +'<button class="wb" id="wb-waves" data-layer="waves" onclick="setWindyLayer(this.dataset.layer)">V\\u00e5gor</button>'
    +'<button class="wb" id="wb-pm2p5" data-layer="pm2p5" onclick="setWindyLayer(this.dataset.layer)">PM2.5</button>'
    +'</div>'
    +'<div class="map-frame" style="flex:1;min-height:0;">'
    +'<iframe id="windy-frame" src="https://embed.windy.com/embed2.html?lat=59.35&lon=17.94&detailLat=59.35&detailLon=17.94&zoom=7&level=surface&overlay=rain&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1" allowfullscreen style="width:100%;height:100%;border:none;display:block;"></iframe>'
    +'</div></div>'
    // Desk panel (was pollen map)
    +'<div class="panel" id="desk-panel">'+buildDeskPanel(_lastDesk)+'</div>'
    // Hourly
    +'<div class="panel"><div class="pi"><div class="lbl">Timsvis \\u00b7 12h</div><div class="hour-list">'
    +_lastWeather.w.hourly.slice(0,12).map(function(h,i){
      return '<div class="hour-row'+(i===0?' now':'')+'"><div class="ht">'+(i===0?'Nu':h.time)+'</div><div class="hi">'+h.icon+'</div><div class="hte">'+h.temp+'\\u00b0</div><div class="hr">'+(h.precip_prob>0?h.precip_prob+'%':'')+'</div></div>';
    }).join('')+'</div></div></div>';

  // Bottom row
  var pol=_lastWeather.pol,water=_lastWeather.water,indoor=_lastWeather.indoor,wn=_lastWeather.wn;
  var warnHtml=wn.length?'<div class="warn-list">'+wn.map(function(w){
    var cls={orange:'orange',red:'red',yellow:'yellow'}[w.severity]||'default';
    return '<div class="warn-strip '+cls+'"><span>\\u26a0</span><span class="wt">'+w.title+'</span>'+(w.text?'<span style="color:var(--t3);margin-left:3px;">\\u2014 '+w.text.substring(0,80)+'</span>':'')+' </div>';
  }).join('')+'</div>':'';

  var polItems=(pol&&pol.items)||[];
  var polHtml=polItems.length===0
    ?'<div class="pollen-empty">'+(pol&&pol.text?pol.text:'Inga f\\u00f6rh\\u00f6jda pollenniv\\u00e5er')+'</div>'
    :'<div class="pollen-rows">'+polItems.map(function(p){
      var pct=Math.round((p.level/7)*100);
      return '<div class="pollen-row2">'
        +'<div class="pollen-nm">'+p.name+'</div>'
        +'<div class="pollen-bar-track"><div class="pollen-bar-fill" style="width:'+pct+'%;background:'+p.color+';"></div></div>'
        +'<div class="pollen-lbl2" style="color:'+p.color+';">'+p.label+'</div>'
        +'</div>';
    }).join('')+'</div>'+(pol&&pol.text?'<div style="font-size:.54rem;color:var(--t3);line-height:1.5;flex-shrink:0;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">'+pol.text+'</div>':'');

  var indHtml;
  if(indoor&&Object.keys(indoor).length>0){
    var hC=indoor.humidity!=null?humColor(indoor.humidity):'#94a3b8';
    var pC=indoor.pm25!=null?pm25Color(indoor.pm25):'#94a3b8';
    var aC=indoor.allergen!=null?algColor(indoor.allergen):'#94a3b8';
    var wW=indoor.water_level!=null&&indoor.water_level<15;
    var fL=fanModeLabel(indoor.fan_mode||'');
    var hT=indoor.humidity_target!=null?' / '+indoor.humidity_target+'%':'';
    var hS=indoor.humidity!=null?(indoor.humidity>=40&&indoor.humidity<=60?'Bra niv\\u00e5':indoor.humidity<40?'F\\u00f6r torr':'F\\u00f6r fuktig'):'';
    indHtml='<div class="aq-rows">'
      +'<div class="aq-row" style="background:rgba(96,165,250,.06);border:1px solid rgba(96,165,250,.1);"><div class="aq-ico">&#x1F321;</div><div class="aq-info"><div class="aq-key">Temperatur</div>'
      +(indoor.temp!=null?'<div class="aq-val2" style="color:#60a5fa;">'+indoor.temp.toFixed(1)+'\\u00b0C</div>':'<div class="aq-val2" style="color:#475569;">\\u2013</div>')
      +'<div class="aq-sub2" style="color:var(--t3);">Sovrum</div></div></div>'
      +'<div class="aq-row" style="background:rgba(34,211,238,.06);border:1px solid rgba(34,211,238,.1);"><div class="aq-ico">&#x1F4A7;</div><div class="aq-info"><div class="aq-key">Luftfuktighet</div>'
      +(indoor.humidity!=null?'<div class="aq-val2" style="color:'+hC+';">'+Math.round(indoor.humidity)+'%<span style="font-size:.65rem;font-weight:500;color:var(--t3);">'+hT+'</span></div><div class="aq-sub2" style="color:'+hC+';">'+hS+(indoor.humidifier_action?' \\u00b7 '+indoor.humidifier_action:'')+'</div>':'<div class="aq-val2">\\u2013</div>')
      +'</div></div>'
      +'<div class="aq-row" style="background:rgba(52,211,153,.06);border:1px solid rgba(52,211,153,.1);"><div class="aq-ico">&#x1F32B;</div><div class="aq-info"><div class="aq-key">PM2.5</div>'
      +(indoor.pm25!=null?'<div class="aq-val2" style="color:'+pC+';">'+indoor.pm25.toFixed(0)+' \\u03bcg/m\\u00b3</div><div class="aq-sub2" style="color:'+pC+';">'+pm25Label(indoor.pm25)+'</div>':'<div class="aq-val2">\\u2013</div>')
      +'</div></div>'
      +'<div class="aq-row" style="background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.1);"><div class="aq-ico">&#x1F33F;</div><div class="aq-info"><div class="aq-key">Allergenindex</div>'
      +(indoor.allergen!=null?'<div class="aq-val2" style="color:'+aC+';">'+indoor.allergen.toFixed(0)+'/5</div><div class="aq-sub2" style="color:'+aC+';">'+algLabel(indoor.allergen)+'</div>':'<div class="aq-val2">\\u2013</div>')
      +'</div></div>'
      +'<div class="aq-row" style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);"><div class="aq-ico">'+(indoor.fan_on?'&#x1F300;':'&#x23F9;')+'</div>'
      +'<div class="aq-info"><div class="aq-key">L\\u00e4ge</div><div class="aq-val2" style="color:var(--t2);font-size:.8rem;">'+fL+'</div></div>'
      +(indoor.water_level!=null?'<div class="aq-badge" style="color:'+(wW?'#f87171':'#94a3b8')+';background:'+(wW?'rgba(239,68,68,.12)':'rgba(255,255,255,.05)')+';border:1px solid '+(wW?'rgba(239,68,68,.3)':'rgba(255,255,255,.1)')+';">'+(wW?'\\u26a0\\ufe0f ':'\\uD83D\\uDCA7 ')+Math.round(indoor.water_level)+'%</div>':'')
      +'</div></div>';
  } else {
    indHtml='<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--t3);font-size:.72rem;">Ingen data fr\\u00e5n luftrenaren</div>';
  }

  var moon=getMoonPhase();
  var wc=water&&water.temp!=null?(water.temp>=20?'#f59e0b':water.temp>=15?'#34d399':water.temp>=5?'#22d3ee':'#60a5fa'):'#60a5fa';
  var waterHtml=water&&water.temp!=null
    ?'<div class="water-big" style="color:'+wc+';">'+water.temp.toFixed(1)+'<sup>\\u00b0C</sup></div><div class="water-sub">'+(water.station||'')+'</div><div class="water-sub">'+(water.updated||'')+'</div>'
    :'<div class="water-big" style="color:#475569;font-size:1.3rem;">\\u2013</div><div class="water-sub">Ej tillg\\u00e4nglig</div>';

  document.getElementById('bot-row').innerHTML=
    '<div class="panel"><div class="pi"><div class="lbl">5-Dagars prognos</div><div class="daily-wrap">'
    +_lastWeather.w.daily.map(function(d){
      return '<div class="day-row"><div class="dn">'+d.day+'</div><div class="di">'+d.icon+'</div>'
        +'<div class="day-temps"><span class="hi2">'+d.max+'\\u00b0</span><span class="lo2">'+d.min+'\\u00b0</span></div></div>';
    }).join('')+'</div>'+warnHtml+'</div></div>'
    +'<div class="panel"><div class="pi"><div class="lbl">&#x1F338; Pollen \\u00b7 Stockholm</div>'+polHtml+'</div></div>'
    +'<div class="panel"><div class="pi"><div class="lbl">&#x1F3E0; Inomhus \\u00b7 Sovrum</div>'+indHtml+'</div></div>'
    +'<div class="panel"><div class="pi"><div class="lbl">Vatten &amp; M\\u00e5ne</div>'
    +'<div class="extra-wrap">'
    +'<div class="water-card"><div class="lbl">&#x1F30A; Vattentemp</div>'+waterHtml+'</div>'
    +'<div class="moon-card"><div class="lbl">&#x1F319; M\\u00e5nfas</div>'
    +'<div class="moon-ico">'+moon.emoji+'</div><div class="moon-name">'+moon.name+'</div><div class="moon-next">'+moon.nextTxt+'</div>'
    +'</div></div></div></div>'
    +'<div class="panel" id="desk-week-panel">'+buildDeskWeekPanel(_lastDesk)+'</div>';
}

// ── Clock & date ───────────────────────────────────────────────────────
var DAYS=['\\u00d6n','M\\u00e5n','Tis','Ons','Tor','Fre','L\\u00f6r'];
var MONTHS=['jan','feb','mar','apr','maj','jun','jul','aug','sep','okt','nov','dec'];
function tick(){var d=new Date();document.getElementById('clock').textContent=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
function setDate(){var d=new Date();document.getElementById('hdr-date').textContent=DAYS[d.getDay()]+' '+d.getDate()+' '+MONTHS[d.getMonth()];}

async function castToTV() {
  const btn = document.getElementById('cast-btn');
  btn.textContent = 'Castar...';
  btn.style.color = '#f59e0b';
  try {
    const r = await fetch('/castboard/cast', {method:'POST'});
    const d = await r.json();
    if (d.status === 'ok') {
      btn.style.color = '#34d399';
      btn.innerHTML = '&#10003; Castad';
      setTimeout(() => {
        btn.style.color = '';
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 8.5A12.5 12.5 0 0 1 14.5 21"/><path d="M2 12.5A8.5 8.5 0 0 1 10.5 21"/><path d="M2 16.5A4.5 4.5 0 0 1 6.5 21"/><circle cx="2" cy="21" r="1" fill="currentColor"/><rect x="14" y="3" width="8" height="6" rx="1"/><path d="M14 6h8"/></svg> Casta';
      }, 3000);
    } else {
      btn.style.color = '#f87171';
      btn.textContent = 'Fel: ' + (d.detail || 'okänt');
      setTimeout(() => { btn.style.color = ''; btn.textContent = 'Casta'; }, 4000);
    }
  } catch(e) {
    btn.style.color = '#f87171';
    btn.textContent = 'Nätverksfel';
    setTimeout(() => { btn.style.color = ''; btn.textContent = 'Casta'; }, 4000);
  }
}

fetchAll();
tick(); setDate();
setInterval(tick, 1000);
setInterval(fetchAll, 5*60*1000);   // weather + full refresh every 5 min
setInterval(fetchDeskOnly, 30*1000); // desk panel refresh every 30s
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def castboard() -> HTMLResponse:
    return HTMLResponse(content=_HTML)


@router.post("/cast")
def castboard_cast() -> JSONResponse:
    """Cast the castboard to the Chromecast TV."""
    from .departures import CHROMECAST_HOST, cast_departure_board  # reuse cast logic
    import time as _time
    try:
        import pychromecast  # type: ignore
        from pychromecast.controllers.dashcast import DashCastController  # type: ignore
        cast = pychromecast.get_chromecast_from_host(
            (CHROMECAST_HOST, 8009, None, None, "Badrum")
        )
        cast.wait(timeout=10)
        cast.quit_app()
        _time.sleep(2)
        d = DashCastController()
        cast.register_handler(d)
        url = CASTBOARD_CAST_URL
        d.load_url(url, force=True, reload_seconds=0)
        return JSONResponse({"status": "ok", "url": CASTBOARD_CAST_URL, "host": CHROMECAST_HOST})
    except Exception as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)
