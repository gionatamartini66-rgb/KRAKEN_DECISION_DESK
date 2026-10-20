"""POC 1: grafico locale SUI/EUR 4H con candele e volumi reali chiusi.
Niente ordini, chiavi o indicatori fittizi. Dati dal dossier Kraken esistente.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
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


def page_from_dossier(path: Path):
    x = data_from_dossier(path)
    candle_json = json.dumps(x["candles"], separators=(",",":"), allow_nan=False)
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
<div class="stats" id="candle-stats" aria-live="polite">Seleziona una candela per i valori OHLCV.</div>
<div id="price-plot" aria-label="Grafico candlestick SUI/EUR 4H"></div>
<h2 style="font-size:1rem">Volumi scambiati (SUI)</h2>
<div id="volume-plot" aria-label="Istogramma dei volumi SUI/EUR 4H"></div>
<p class="muted">Dati raccolti: __OBSERVED__. Ultima candela chiusa: __CLOSED__.
Il grafico usa 200 candele 4H al massimo. L'ultimo prezzo non è live:
per aggiornare torna al cruscotto e premi «Aggiorna dati ora».</p>
<p class="muted"><b>FASE 1 / PROTOTIPO.</b> Solo candele e volumi.
EMA, pivot, supporti, resistenze, pattern e altri timeframe NON sono ancora
implementati nel grafico; non attribuirgli segnali BUY/SELL.</p>
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
const msg=document.getElementById('graph-status');
const stats=document.getElementById('candle-stats');
try {
  if (!window.LightweightCharts ||
      !LightweightCharts.createChart ||
      !LightweightCharts.CandlestickSeries ||
      !LightweightCharts.HistogramSeries) {
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
            .replace("__OBSERVED__", observed).replace("__CLOSED__", closed)
            .replace("__NOTICE__", html.escape(notice)))
