"""POC 1: grafico locale SUI/EUR 4H con candele e volumi reali chiusi.
Niente ordini, chiavi o indicatori fittizi. Dati dal dossier Kraken esistente.
"""
from __future__ import annotations

# CANARY DEPLOY 2026-10-20: sola verifica aggiornamento GitHub → Termux.
# Nessun cambiamento al grafico, ai dati di mercato o al comportamento di KDD.

import datetime as dt
import html
import json
import math
import statistics
from pathlib import Path

TOKEN = "SUI"
TF = "4H"
CANDLES_MAX = 200

def data_from_dossier(path: Path):
    src = json.loads(path.read_text(encoding="utf-8"))
    market = src.get("grafici_4h", {}).get(TOKEN)
    if not market or market.get("stato") != "OK":
        raise ValueError("Serie SUI 4H non disponibile o con lacune")
    if market.get("coppia") != "SUI/EUR":
        raise ValueError("La coppia SUI/EUR non corrisponde ai dati richiesti")
    records = market.get("serie_ohlcv_chiuse")
    if not isinstance(records, list) or not 30 <= len(records) <= CANDLES_MAX:
        raise ValueError("Numero di candele chiuse 4H insufficiente o inatteso")

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    ordered = []
    previous = None
    for record in records:
        ts = record.get("apertura_ts_utc")
        if type(ts) is not int or (previous is not None and ts-previous != 14400):
            raise ValueError("Timestamp delle candele non consecutivi")
        previous = ts
        if ts+14400 > now + 2:  # esclude la candela ancora in formazione
            raise ValueError("Candela 4H non conclusa")
        prices = {k: float(record[k]) for k in ("open", "high", "low", "close")}
        volume = float(record["volume_base"])
        o,h,l,c = (prices[k] for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(v) for v in (o,h,l,c,volume)) or not (
            0 < l <= min(o,c) <= max(o,c) <= h and volume >= 0
        ):
            raise ValueError("OHLCV non valido")
        ordered.append({"time":ts, **prices, "volume":volume})
    return {
        "observed_utc": src["creato_utc"],
        "pair":market["coppia"],
        "token":TOKEN,
        "timeframe":TF,
        "closed_at_utc": dt.datetime.fromtimestamp(
            ordered[-1]["time"]+14400, dt.timezone.utc
        ).isoformat(timespec="seconds"),
        "candles":ordered,
    }


def ema_points(candles, period):
    """EMA sull'ultimo campione di candele chiuse; SMA iniziale di 'period' chiusure.

    I primi period-1 punti sono assenti, mai riempiti artificialmente.
    """
    if not isinstance(period, int) or period < 2 or len(candles) < period:
        return []
    alpha = 2.0 / (period + 1)
    values = [row["close"] for row in candles]
    ema = sum(values[:period]) / period
    points = [{"time": candles[period - 1]["time"], "value": round(ema, 8)}]
    for i in range(period, len(candles)):
        ema += alpha * (values[i] - ema)
        points.append({"time": candles[i]["time"], "value": round(ema, 8)})
    return points


def daily_pivots(candles):
    """Pivot CLASSICI del giorno UTC precedente, esclusivamente da 6 barre 4H chiuse.

    Il riferimento è il giorno UTC nel quale cade la chiusura più recente:
    non si usano candele in formazione né dati del giorno corrente.
    """
    if not candles:
        return None
    last_close = dt.datetime.fromtimestamp(
        candles[-1]["time"] + 14400, dt.timezone.utc)
    prev_day = last_close.date() - dt.timedelta(days=1)
    start = int(dt.datetime.combine(prev_day, dt.time.min,
                                     dt.timezone.utc).timestamp())
    day = [row for row in candles if start <= row["time"] < start + 86400]
    if len(day) != 6 or [row["time"] for row in day] != [
            start + 14400 * i for i in range(6)]:
        return None
    high = max(row["high"] for row in day)
    low = min(row["low"] for row in day)
    close = day[-1]["close"]
    p = (high + low + close) / 3.0
    spread = high - low
    return {"reference_day_utc": prev_day.isoformat(),
            "P": round(p, 8),
            "R1": round(2 * p - low, 8),
            "S1": round(2 * p - high, 8),
            "R2": round(p + spread, 8),
            "S2": round(p - spread, 8),
            "R3": round(high + 2 * (p - low), 8),
            "S3": round(low - 2 * (high - p), 8)}


def structural_levels(candles, tolerance=0.009):
    """Livelli *descrittivi* da swing 4H confermati: almeno due test.

    Richiede due candele chiuse prima e dopo ciascuno swing (raggio 2).
    Raggruppa prezzi simili entro una tolleranza relativa dello 0,9%.
    Nessun livello quando mancano due estremi indipendenti. Non è un ordine.
    """
    if len(candles) < 7:
        return {"supports": [], "resistances": []}
    last = candles[-1]["close"]
    def pivots(side):
        col = "low" if side == "low" else "high"
        result = []
        for i in range(2, len(candles) - 2):
            here = candles[i][col]
            nearby = [candles[j][col] for j in range(i - 2, i + 3) if j != i]
            if ((here < min(nearby)) if side == "low" else
                    (here > max(nearby))):
                result.append((i, here))
        return result
    def group(items, support):
        clusters = []
        for index, price in sorted(items, key=lambda entry: entry[1]):
            found = next((
                cl for cl in clusters
                if abs(price - statistics.median(x[1] for x in cl)) /
                   statistics.median(x[1] for x in cl) <= tolerance
            ), None)
            if found is None:
                clusters.append([(index, price)])
            else:
                found.append((index, price))
        candidates = []
        for cl in clusters:
            if len(cl) < 2:
                continue
            level = statistics.median(x[1] for x in cl)
            if (support and level >= last) or (not support and level <= last):
                continue
            candidates.append((level, len(cl), max(x[0] for x in cl)))
        # Prossimità al prezzo corrente, a parità tocchi/recenza.
        candidates.sort(key=lambda z: (abs(z[0] - last), -z[1], -z[2]))
        return [{"price": round(p, 8), "touches": n,
                 "last_swing_time": candles[i]["time"]}
                for p, n, i in candidates[:3]]
    return {"supports": group(pivots("low"), True),
            "resistances": group(pivots("high"), False)}


def technical_from_candles(candles):
    return {
        "ema20": ema_points(candles, 20),
        "ema50": ema_points(candles, 50),
        "pivots": daily_pivots(candles),
        "structure": structural_levels(candles),
    }


def page_from_dossier(path: Path):
    x = data_from_dossier(path)
    candle_json = json.dumps(x["candles"], separators=(",",":"), allow_nan=False)
    technical_json = json.dumps(technical_from_candles(x["candles"]),
                                separators=(",",":"), allow_nan=False)
    pair = html.escape(x["pair"], quote=True)
    observed = html.escape(x["observed_utc"], quote=True)
    closed = html.escape(x["closed_at_utc"], quote=True)
    notice = ("TradingView Lightweight Charts™. "
              "Copyright (с) 2025 TradingView, Inc.")
    template = """<!doctype html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KDD | Prova SUI 4H</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif;background:#0b1221;color:#eaf0fa}
*{box-sizing:border-box}body{margin:0;padding:12px;max-width:1120px;margin-inline:auto}
a{color:#8aceff}h1{font-size:1.25rem;margin:8px 0}small,.muted{color:#b3c1d8}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.panel{background:#151f32;border:1px solid #34415d;border-radius:12px;padding:12px;margin-top:12px}
#price-plot{width:100%;height:420px}#volume-plot{width:100%;height:150px}
.buttons{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.legend{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 12px}
.legend label{display:flex;gap:6px;align-items:center;padding:8px;border:1px solid #536481;
 background:#1a2941;border-radius:8px;font-size:.92rem}
.legend input{width:17px;height:17px;accent-color:#8aceff}
#tech-summary{font-size:.9rem;line-height:1.45;margin-bottom:6px}
#nearby-summary{font-size:.9rem;line-height:1.5;padding:8px 10px;
 background:#1a2941;border-left:3px solid #8aceff;border-radius:5px;margin:8px 0 12px}
.level-details{margin:8px 0 14px;padding:10px;border:1px solid #41506c;border-radius:8px}
.level-details summary{cursor:pointer;color:#c7e8ff;font-weight:600}
.level-details section{margin:12px 0 8px}
.level-details h3{font-size:.95rem;margin:8px 0}
.level-details table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.9rem}
.level-details td,.level-details th{padding:7px 5px;border-bottom:1px solid #3a4b64;text-align:left}
.level-details td:nth-child(2){font-weight:600;text-align:right;white-space:nowrap}
.level-details td:last-child,.level-details th:last-child{font-size:.82rem;color:#b7c9dd;padding-left:8px}
.level-details .method{margin:9px 0;font-size:.85rem}
button{font:inherit;min-height:40px;padding:8px 14px;border-radius:8px;
 background:#253c5e;border:1px solid #5e8cbb;color:white}
button:focus-visible,a:focus-visible{outline:3px solid #a2e2ff}
.stats{font-variant-numeric:tabular-nums;min-height:42px}
#graph-status{font-weight:600;color:#85e6bc;min-height:24px}
#graph-status.error{color:#ff969d}
footer{font-size:.83rem;color:#b3c1d8;line-height:1.5;margin:14px 0 26px}
</style>
</head>
<body>
<header>
<div><h1>📈 KDD · Prova grafico SUI/EUR · 4H</h1>
<small>Kraken Spot · candele CHIUSE · orari UTC · nessun ordine</small></div>
<a href="/">← Torna al cruscotto</a>
</header>
<section class="panel">
<div id="graph-status" role="status">Preparazione grafico…</div>
<div class="buttons" aria-label="Zoom grafico">
<button type="button" data-range="40">Ultime 40</button>
<button type="button" data-range="100">Ultime 100</button>
<button type="button" data-range="all">Tutte</button>
</div>
<div class="legend" aria-label="Livelli e indicatori">
<label><input type="checkbox" id="show-ema20" checked> EMA20 (oro)</label>
<label><input type="checkbox" id="show-ema50" checked> EMA50 (azzurro)</label>
<label><input type="checkbox" id="show-structure" checked> S/R principali</label>
<label><input type="checkbox" id="show-pivots"> Pivot (3 linee)</label>
</div>
<div id="tech-summary" class="muted" aria-live="polite">Elaborazione livelli tecnici…</div>
<div id="nearby-summary" aria-live="polite">Ricerca di eventuali vicinanze fra livelli…</div>
<details class="level-details">
<summary>Tutti i livelli e i prezzi esatti (apri)</summary>
<p class="method">Le linee sul grafico mostrano soltanto i due S/R più vicini per lato
e, se selezionati, P più un pivot sopra e uno sotto l'ultima chiusura.
Nella tabella trovi tutti i livelli calcolati, anche quelli nascosti.
Le etichette sull'asse prezzi sono disattivate perché si sovrapponevano,
spostando visivamente i numeri rispetto alle linee.</p>
<div id="levels-list"></div>
</details>
<div class="stats" id="candle-stats" aria-live="polite">Seleziona una candela per i valori OHLCV.</div>
<div id="price-plot" aria-label="Grafico candlestick SUI/EUR 4H"></div>
<h2 style="font-size:1rem">Volumi scambiati (SUI)</h2>
<div id="volume-plot" aria-label="Istogramma dei volumi SUI/EUR 4H"></div>
<p class="muted">Dati raccolti: __OBSERVED__. Ultima candela chiusa: __CLOSED__.
Il grafico usa 200 candele 4H al massimo. L'ultimo prezzo non è live:
per aggiornare torna al cruscotto e premi «Aggiorna dati ora».</p>
<p class="muted"><b>FASE 2 / INDICATORI ESPLORATIVI 4H.</b>
EMA20/50 calcolate esclusivamente sulle candele CHIUSE presenti (massimo 200,
seme SMA iniziale). Supporti e resistenze: estremi locali confermati con
almeno due swing vicini; se mancano non viene inventata una linea.
Pivot P/S1–S3/R1–R3: formule classiche sul giorno UTC precedente, solo se
sono presenti tutte e sei le candele 4H necessarie. Il grafico limita il
numero delle linee per leggibilità, mentre la tabella conserva i valori
completi. Le vicinanze fra indicatori non costituiscono conferme indipendenti:
sono una descrizione geometrica e non un segnale BUY/SELL.
Pattern e altri timeframe NON sono ancora implementati.</p>
</section>
<footer><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
__NOTICE__</a> · Libreria gratuita Lightweight Charts 5.2.1, servita localmente.
<a href="/asset/lightweight-notice">NOTICE</a> ·
<a href="/asset/lightweight-license">Licenza Apache 2.0</a>.
Dati Kraken Spot pubblici, non grafico ufficiale TradingView.</footer>
<script src="/asset/lightweight-charts.js"></script>
<script>
(function(){
"use strict";
const rows = __BARS__;
const tech = __TECHNICAL__;
const msg=document.getElementById('graph-status');
const stats=document.getElementById('candle-stats');
try {
  if (!window.LightweightCharts ||
      !LightweightCharts.createChart ||
      !LightweightCharts.CandlestickSeries ||
      !LightweightCharts.HistogramSeries ||
      !LightweightCharts.LineSeries) {
     throw new Error('Libreria grafica non caricata completamente');
  }
  const grid={vertLines:{color:'#27354c'},horzLines:{color:'#27354c'}};
  const layout={background:{type:'solid',color:'#101a2c'},textColor:'#dbe5f3',
                attributionLogo:true,fontFamily:'system-ui, sans-serif'};
  const common={width:document.getElementById('price-plot').clientWidth,
    rightPriceScale:{borderColor:'#50617b'},timeScale:{borderColor:'#50617b',
    timeVisible:true,secondsVisible:false},layout:layout,grid:grid,
    localization:{locale:'it-IT'}};
  const chart=LightweightCharts.createChart(document.getElementById('price-plot'),
                {...common,height:420});
  const candleSeries=chart.addSeries(LightweightCharts.CandlestickSeries,{
    upColor:'#23bb91',downColor:'#ee6b77',borderVisible:false,
    wickUpColor:'#23bb91',wickDownColor:'#ee6b77',priceLineVisible:false,
    lastValueVisible:true});
  candleSeries.setData(rows.map(v=>({
    time:v.time,open:v.open,high:v.high,low:v.low,close:v.close})));
  // EMA calcolate in Python sul medesimo campione chiuso delle candele.
  // Non introdurre qui dati nuovi o stime che non siano tracciabili.
  function addEma(points,color,label,selector){
    const series=chart.addSeries(LightweightCharts.LineSeries,{
      color:color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,
      crosshairMarkerVisible:false,title:label});
    series.setData(points);
    document.querySelector(selector).addEventListener('change',evt=>{
      series.applyOptions({visible:evt.target.checked});
    });
    return series;
  }
  addEma(tech.ema20,'#ffc85a','EMA 20','#show-ema20');
  if(tech.ema50.length)
    addEma(tech.ema50,'#58c5ff','EMA 50','#show-ema50');
  else {
    const e=document.querySelector('#show-ema50');
    e.checked=false;e.disabled=true;e.parentElement.title='Meno di 50 barre chiuse';
  }

  function addLevel(price,title,color,group) {
    const line=candleSeries.createPriceLine({
      price:price,color:color,lineWidth:1,lineStyle:2,
      axisLabelVisible:false,title:title});
    group.push(line);
  }
  function levelToggle(selector,entries){
    const input=document.querySelector(selector);
    let active=[];
    function display(){
      for(const line of active)candleSeries.removePriceLine(line);
      active=[];
      if(input.checked)entries.forEach(e=>addLevel(e.price,e.title,e.color,active));
    }
    input.addEventListener('change',display);
    display();
  }
  const structural=[];
  tech.structure.supports.slice(0,2).forEach((e,i)=>structural.push({
    price:e.price,title:'Str S'+(i+1),color:'#32c7aa'}));
  tech.structure.resistances.slice(0,2).forEach((e,i)=>structural.push({
    price:e.price,title:'Str R'+(i+1),color:'#f3a078'}));
  levelToggle('#show-structure',structural);
  const lastClose=rows[rows.length-1].close;
  const pivotEntries=[];
  const pivotNames=['P','S1','S2','S3','R1','R2','R3'];
  if(tech.pivots){
    // Una sola linea P e le due coordinate pivot più vicine, sopra e sotto.
    const byDistance=pivotNames.filter(n=>n!=='P')
      .sort((a,b)=>Math.abs(tech.pivots[a]-lastClose)-
                    Math.abs(tech.pivots[b]-lastClose));
    const above=byDistance.find(n=>tech.pivots[n]>lastClose);
    const below=byDistance.find(n=>tech.pivots[n]<lastClose);
    for(const name of ['P',above,below].filter((n,i,all)=>n && all.indexOf(n)===i)){
      pivotEntries.push({price:tech.pivots[name],title:'Pivot '+name,
        color:name==='P'?'#e4d778':name.startsWith('S')?'#8bceaf':'#bd9fff'});
    }
  }
  levelToggle('#show-pivots',pivotEntries);
  const eur = new Intl.NumberFormat('it-IT',{maximumFractionDigits:6});
  const supports=tech.structure.supports.length;
  const resistances=tech.structure.resistances.length;
  document.querySelector('#tech-summary').textContent=
    'Ultima EMA20: '+eur.format(tech.ema20[tech.ema20.length-1].value)+
    (tech.ema50.length?' · EMA50: '+eur.format(tech.ema50[tech.ema50.length-1].value):
      ' · EMA50: storico insufficiente')+
    ' · S/R confermati: '+supports+' supporti, '+resistances+' resistenze'+
    ' (almeno due swing per livello).'+
    (tech.pivots?' Pivot del '+tech.pivots.reference_day_utc+
       ' UTC: P '+eur.format(tech.pivots.P)+'.':
       ' Pivot giornalieri: dati completi giorno precedente insufficienti.');

  const exact=new Intl.NumberFormat('it-IT',{maximumFractionDigits:8});
  const categories=[
    {name:'Medie esponenziali (chiusure 4H)',family:'EMA',items:[
      {label:'EMA20',price:tech.ema20[tech.ema20.length-1].value,note:'20 chiusure'},
      ...(tech.ema50.length ? [{label:'EMA50',
        price:tech.ema50[tech.ema50.length-1].value,note:'50 chiusure'}] : [])]},
    {name:'Supporti strutturali',family:'S/R',items:
      tech.structure.supports.map((v,i)=>({label:'S'+(i+1),
        price:v.price,note:v.touches+' swing 4H'}))},
    {name:'Resistenze strutturali',family:'S/R',items:
      tech.structure.resistances.map((v,i)=>({label:'R'+(i+1),
        price:v.price,note:v.touches+' swing 4H'}))},
    {name:'Pivot classici UTC',family:'Pivot',items:
      tech.pivots?pivotNames.map(n=>({label:n,price:tech.pivots[n],
        note:tech.pivots.reference_day_utc})) : []},
  ];
  const panel=document.getElementById('levels-list');
  for(const section of categories){
    const block=document.createElement('section');
    const title=document.createElement('h3');
    title.textContent=section.name;
    block.appendChild(title);
    if(!section.items.length){
      const empty=document.createElement('p');
      empty.textContent='Nessun livello disponibile con i dati chiusi.';
      block.appendChild(empty);
    }else{
      const table=document.createElement('table');
      const header=document.createElement('tr');
      ['Livello','Prezzo EUR','Origine'].forEach(name=>{
        const th=document.createElement('th');
        th.textContent=name;header.appendChild(th);
      });
      table.appendChild(header);
      for(const item of section.items){
        const tr=document.createElement('tr');
        [item.label,exact.format(item.price),item.note].forEach(value=>{
          const td=document.createElement('td');
          td.textContent=value;tr.appendChild(td);
        });
        table.appendChild(tr);
      }
      block.appendChild(table);
    }
    panel.appendChild(block);
  }
  // Confluenza = vicinanza numerica, NON maggior probabilità di rimbalzo.
  // Il gruppo deve stare per intero entro 0,5% del valore mediano.
  const near=categories.flatMap(cat=>cat.items.map(item=>({
    ...item,family:cat.family
  }))).sort((a,b)=>a.price-b.price);
  const groups=[];
  let group=[];
  for(const item of near){
    if(group.length===0 || (item.price-group[0].price)/
        (0.5*(item.price+group[0].price))<=0.005){
      group.push(item);
    }else{
      groups.push(group);group=[item];
    }
  }
  if(group.length)groups.push(group);
  const confluences=groups.filter(items=>items.length>=2 &&
    new Set(items.map(x=>x.family)).size>=2);
  confluences.sort((a,b)=>Math.abs(a[0].price-lastClose)-
                         Math.abs(b[0].price-lastClose));
  const strip=document.getElementById('nearby-summary');
  if(confluences.length){
    const shown=confluences.slice(0,2).map(items=>
      exact.format(Math.min(...items.map(x=>x.price)))+'–'+
      exact.format(Math.max(...items.map(x=>x.price)))+' € ('+
      items.map(x=>x.label+' '+x.family).join(', ')+')');
    strip.textContent='Vicinanze entro 0,5% (solo descrittive): '+
      shown.join(' · ')+'. Nessuna conferma di tenuta o breakout.';
  }else{
    strip.textContent='Nessuna vicinanza multi-fonte entro 0,5% '+
      'fra i livelli osservati. Non equivale a mancanza di opportunità.';
  }
  const volumeChart=LightweightCharts.createChart(
    document.getElementById('volume-plot'),{...common,height:150});
  const volumeSeries=volumeChart.addSeries(LightweightCharts.HistogramSeries,{
    priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false});
  volumeSeries.setData(rows.map(v=>({
    time:v.time,value:v.volume,
    color:v.close>=v.open?'rgba(35,187,145,0.75)':'rgba(238,107,119,0.75)'})));
  chart.timeScale().fitContent();
  volumeChart.timeScale().fitContent();
  let syncing=false;
  function sync(source,dest){
    source.timeScale().subscribeVisibleLogicalRangeChange(r=>{
      if(syncing || !r)return; syncing=true;
      try{dest.timeScale().setVisibleLogicalRange(r)}finally{syncing=false}
    });
  }
  sync(chart,volumeChart);sync(volumeChart,chart);
  document.querySelectorAll('button[data-range]').forEach(btn=>
    btn.addEventListener('click',()=>{
      const n=btn.dataset.range==='all'?rows.length:Number(btn.dataset.range);
      const from=Math.max(0,rows.length-n);
      chart.timeScale().setVisibleLogicalRange({from:from,to:rows.length-1});
    }));
  function show(row){
    const fmt=new Intl.NumberFormat('it-IT',{maximumFractionDigits:6});
    const time=new Date(row.time*1000).toLocaleString('it-IT',{timeZone:'UTC'});
    stats.textContent=time+' UTC · O '+fmt.format(row.open)+' · H '+fmt.format(row.high)+
     ' · L '+fmt.format(row.low)+' · C '+fmt.format(row.close)+
     ' · Vol '+fmt.format(row.volume)+' SUI';
  }
  show(rows[rows.length-1]);
  const byTime=new Map(rows.map(v=>[v.time,v]));
  chart.subscribeCrosshairMove(p=>{
    if(p.time && byTime.has(p.time))show(byTime.get(p.time));
  });
  const observer=new ResizeObserver(()=>{
    chart.applyOptions({width:document.getElementById('price-plot').clientWidth});
    volumeChart.applyOptions({width:document.getElementById('volume-plot').clientWidth});
  });
  observer.observe(document.getElementById('price-plot'));
  msg.textContent='Grafico generato: '+rows.length+' candele 4H reali + volumi. Scorri e ingrandisci.';
}catch(e){
  msg.classList.add('error');
  msg.textContent='Errore di visualizzazione: '+e.message+
    '. Dati preservati, nessun ordine eseguito.';
}
})();
</script>
</body>
</html>"""
    return (template.replace("__BARS__", candle_json)
            .replace("__TECHNICAL__", technical_json)
            .replace("__OBSERVED__", observed).replace("__CLOSED__", closed)
            .replace("__NOTICE__", html.escape(notice)))
