#!/usr/bin/env python3
"""Cruscotto Kraken locale: HTTP soltanto 127.0.0.1, dati pubblici, nessun ordine."""
import datetime as dt
import hmac
import html
import json
import math
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import decision_desk as desk
import grafico_4h

HOST, PORT = "127.0.0.1", 8765
TOKEN = secrets.token_urlsafe(28)
REFRESH_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
JOB_STATE = {"stato": "mai_avviato", "avvio_utc": None,
             "fine_utc": None, "durata_secondi": 0}


def job_snapshot():
    with STATE_LOCK:
        return dict(JOB_STATE)


def _refresh_worker():
    started = time.monotonic()
    outcome = "riuscito"
    try:
        desk.refresh()
    except Exception as exc:
        outcome = "errore"
        print("Aggiornamento fallito:", type(exc).__name__, str(exc), flush=True)
    finally:
        with STATE_LOCK:
            JOB_STATE.update(stato=outcome,
                             fine_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                             durata_secondi=round(time.monotonic() - started, 1))
        REFRESH_LOCK.release()


def start_refresh():
    """Non accoda doppie richieste; segue la singola operazione fino a conclusione."""
    if not REFRESH_LOCK.acquire(blocking=False):
        return False
    with STATE_LOCK:
        JOB_STATE.update(stato="in_corso",
                         avvio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                         fine_utc=None, durata_secondi=0)
    try:
        threading.Thread(target=_refresh_worker, daemon=True,
                         name="kdd-aggiornamento-kraken").start()
    except Exception:
        with STATE_LOCK:
            JOB_STATE["stato"] = "errore"
        REFRESH_LOCK.release()
        raise
    return True


def with_controls(page: str, result: str = "") -> str:
    """Aggiornamento senza bloccare Chrome; quando pronto aggiorna da solo la pagina."""
    running = job_snapshot()["stato"] == "in_corso"
    labels = {
        "ok": "Dati aggiornati: rilevazione caricata.",
        "errore": "Aggiornamento fallito: i prezzi precedenti restano visibili con la loro data.",
        "avviato": "Aggiornamento avviato: attendi, questa pagina si ricaricherà da sola.",
        "occupato": "Un aggiornamento è già in corso: attendi, non occorre ripremere.",
    }
    message = labels.get(result, "Aggiornamento in corso: attendi..." if running else "")
    disabled = " disabled" if running else ""
    toolbar = (
        "<section style='margin:18px 0;padding:16px;background:#22334e;border-radius:12px'>"
        "<form method='post' action='/aggiorna' id='kdd-refresh-form'>"
        f"<input type='hidden' name='token' value='{html.escape(TOKEN, quote=True)}'>"
        "<button id='kdd-refresh-button' style='font:inherit;padding:12px 18px;border:0;"
        "border-radius:9px;background:#80cbff;color:#06162b;font-weight:700' "
        f"type='submit'{disabled}>↻ Aggiorna dati ora</button>"
        "</form><p><a style='font-weight:700;color:#8aceff' href='/mercati/spot'>"
        "🌐 Seleziona coppia Kraken Spot · grafici 15m / 1H / 4H / 1D</a></p>"
        "<p>Server solo su questo Samsung · prezzi pubblici · nessun ordine.</p>"
        f"<p id='kdd-refresh-status' role='status'>{html.escape(message)}</p>"
        "</section>"
    )
    js = """<script>
(function () {
  const status = document.getElementById('kdd-refresh-status');
  const button = document.getElementById('kdd-refresh-button');
  const outcome = new URLSearchParams(window.location.search).get('esito');
  let checks = 0;
  const pending = outcome === 'avviato' || outcome === 'occupato' || __RUNNING__;
  if (!pending) return;
  button.disabled = true;
  async function poll() {
    try {
      const response = await fetch('/stato', {cache:'no-store'});
      if (!response.ok) throw new Error('Stato HTTP ' + response.status);
      const job = await response.json();
      if (job.stato === 'riuscito') {
        window.location.replace('/?esito=ok');
        return;
      }
      if (job.stato === 'errore') {
        window.location.replace('/?esito=errore');
        return;
      }
      if (job.stato !== 'in_corso') {
        status.textContent = 'Nessun aggiornamento attivo. Puoi riprovare.';
        button.disabled = false;
        return;
      }
      checks++;
      status.textContent = 'Kraken: raccolta dati in corso (' + Math.round(checks * 2.5) +
        ' secondi circa). La pagina si aggiorna da sola, non premere ancora.';
      window.setTimeout(poll, 2500);
    } catch (e) {
      status.textContent = 'Stato temporaneamente non disponibile: riprovo automaticamente.';
      window.setTimeout(poll, 5000);
    }
  }
  poll();
})();
</script>""".replace("__RUNNING__", "true" if running else "false")
    target = "<h2>1 · Decisioni e posizioni</h2>"
    # La descrizione del file statico non deve apparire nel cruscotto servito.
    static_notice = ("<p class='muted'>Questa copia HTML è una fotografia: per ricevere nuovi prezzi apri il "
                     "<a href='http://127.0.0.1:8765/'>cruscotto locale aggiornabile</a> "
                     "(richiede Termux attivo).</p>")
    page = page.replace(static_notice, "", 1)
    return page.replace(target, toolbar + js + target, 1)


def load_sui_chart(timeframe, public_kraken=None):
    """4H remains sourced from the verified dossier; other frames are Kraken OHLC.
    
    No account lookup or private API is involved in switching timeframes.
    """
    if timeframe not in grafico_4h.TIMEFRAMES:
        raise ValueError("Timeframe non consentito")
    if timeframe == "4h":
        return grafico_4h.page_from_dossier(desk.DIR / "dossier_multifonte.json")
    interval = grafico_4h.TIMEFRAMES[timeframe][0]
    fetch = public_kraken or desk.kraken
    result = fetch("OHLC", pair="SUIEUR", interval=interval)
    candles = grafico_4h.data_from_kraken_ohlc(result, timeframe)
    return grafico_4h.page_from_data(candles)


def load_sui_comparison(public_kraken=None, now=None):
    """Read four independent closed Kraken Spot intervals on demand.

    An out-of-date local 4H chart dossier must never block or bias the
    comparison. If Kraken 4H is missing, report it missing instead of
    substituting an older dossier or silently interpolating candles.
    """
    fetch = public_kraken or desk.kraken
    now = now or dt.datetime.now(dt.timezone.utc)
    keys = {"15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
    frames = {}
    for name, key in keys.items():
        try:
            interval = grafico_4h.TIMEFRAMES[key][0]
            result = fetch("OHLC", pair="SUIEUR", interval=interval)
            frames[name] = grafico_4h.data_from_kraken_ohlc(
                result, key, now=now)
        except (ValueError, OSError, RuntimeError, TypeError, KeyError, IndexError) as exc:
            frames[name] = {"errore": "Acquisizione o validazione: " + type(exc).__name__}
    return grafico_4h.compare_timeframes(frames, now=now)


def render_sui_comparison(report, *, pair_key=None):
    """Escaped server-side HTML. No JavaScript or private assets."""
    def esc(value):
        return html.escape(str(value), quote=True)
    def price(value):
        # A fixed five decimal places could print a genuine, very small price
        # as 0.00000. Use significant figures for arbitrary Kraken pairs.
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            return "—"
        return f"{value:.10g}"
    pair = report["coppia"]
    base, quote = pair.split("/", 1)
    if pair_key is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{2,48}", pair_key):
        raise ValueError("Chiave Kraken non valida")
    graph_root = ("/grafico/spot?pair=" + urllib.parse.quote(pair_key, safe="") +
                  "&tf=" if pair_key else "/grafico/sui-4h?tf=")
    labels = {
        "PREZZO_SOPRA_EMA20_SOPRA_EMA50": "Close > EMA20 > EMA50",
        "PREZZO_SOTTO_EMA20_SOTTO_EMA50": "Close < EMA20 < EMA50",
        "CONFIGURAZIONE_MISTA": "Assetto misto",
        "NON_VALUTABILE": "Non valutabile",
    }
    rows = []
    for item in report["timeframe"]:
        name = esc(item["timeframe"])
        link = {"15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}[item["timeframe"]]
        title = ('<a href="' + esc(graph_root + link) + '">' +
                 name + ' → grafico</a>')
        if item["stato"] != "AGGIORNATO":
            reason = esc(item.get("motivo", "Candela chiusa non recente"))
            state = esc(item["stato"])
            rows.append(f'<article class="frame"><h2>{title}</h2><p class="warning">'
                        f'{state}: {reason}</p>'
                        f'<p>{esc(item.get("chiusura_utc", "Orario non disponibile"))}</p></article>')
            continue
        vol = item["volume_vs_media20"]
        vol_text = "non calcolabile" if vol is None else f'{vol:.2f} × media delle 20 barre precedenti'
        # Non trasformare volumi base piccoli ma positivi in uno zero apparente.
        volume_text = f"{item['volume']:.10g}"
        rows.append(
            f'<article class="frame"><h2>{title}</h2>'
            f'<p class="status">AGGIORNATO · {esc(item["candele"])} barre chiuse</p>'
            f'<p><strong>{esc(labels[item["orientamento"]])}</strong></p>'
            f'<p>Close: <b>{price(item["close"])} {esc(quote)}</b> · '
            f'EMA20: {price(item["ema20"])} {esc(quote)} · EMA50: {price(item["ema50"])} {esc(quote)}</p>'
            f'<p>Volume ultima candela: {esc(volume_text)} {esc(base)}; '
            f'rapporto: {esc(vol_text)}</p>'
            f'<p>S/R euristici più vicini: supporto {price(item["supporto_vicino"])} {esc(quote)}; '
            f'resistenza {price(item["resistenza_vicina"])} {esc(quote)}</p>'
            f'<p class="time">Candela chiusa: {esc(item["chiusura_utc"])} UTC<br>'
            f'Rilevazione: {esc(item["rilevazione_utc"])} UTC<br>'
            f'Fonte: {esc(item["fonte"])}</p></article>'
        )
    quadro_labels = {
        "ALLINEAMENTO_RIALZISTA_DESCRITTIVO":
            "Tutti i quattro timeframe hanno Close > EMA20 > EMA50.",
        "ALLINEAMENTO_RIBASSISTA_DESCRITTIVO":
            "Tutti i quattro timeframe hanno Close < EMA20 < EMA50.",
        "CONFIGURAZIONE_MISTA":
            "I timeframe non hanno tutti la stessa disposizione rispetto alle EMA.",
        "CONFRONTO_INCOMPLETO":
            "Uno o più timeframe non sono verificabili: nessuna conclusione complessiva.",
    }
    picture = quadro_labels[report["quadro"]]
    # Static read-only HTML; values are local market observations, not trades.
    return ("""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KDD | Confronto __PAIR__ multitimeframe</title>
<style>:root{color-scheme:dark;font-family:system-ui;background:#0b1221;color:#eaf0fa}
body{margin:auto;padding:14px;max-width:860px;line-height:1.5}
h1{font-size:1.28rem}h2{font-size:1.06rem;margin:0 0 10px}
a{color:#8aceff}.frame,.top{border:1px solid #34415d;background:#151f32;
border-radius:12px;margin:12px 0;padding:14px}
.frame p{margin:6px 0}.time{font-size:.82rem;color:#b3c1d8;overflow-wrap:anywhere}
.status{color:#85e6bc}.warning{color:#ffd48a}
.note{color:#b3c1d8;font-size:.92rem}
strong{color:#dce9ff}</style></head><body>
<p><a href="/">← Cruscotto</a> · <a href="/mercati/spot">Seleziona coppia</a> · <a href="__GRAPH_URL__">Grafico 4H</a></p>
<h1>🔎 KDD · Confronto __PAIR__</h1>
<p>15m · 1H · 4H · 1D — candele Kraken Spot CHIUSE</p>
<section class="top"><h2>Quadro descrittivo: __STATE__</h2>
<p>__PICTURE__</p><p class="note">__WARNING__</p>
<p class="time">Confronto elaborato: __OBSERVED__ UTC</p></section>
__CARDS__
<p class="note">La lettura vale soltanto per le rilevazioni mostrate. Il volume
è confrontato con le 20 barre chiuse precedenti dello stesso timeframe.
S/R sono livelli euristici calcolati dalla cronologia disponibile.
La classificazione rispetto alle EMA non misura la probabilità di guadagno.
Nessuna operazione, nessun segnale BUY/SELL.</p>
<p class="note">Il confronto interroga Kraken Spot pubblico per tutti e quattro
gli intervalli a ogni apertura. Il grafico è una vista separata: controlla
la fonte e l'ora riportate sulla sua pagina, che possono differire.</p>
<p><a href="/">← Torna al cruscotto</a></p>
</body></html>"""
        .replace("__STATE__", esc(report["stato"]))
        .replace("__PICTURE__", esc(picture))
        .replace("__WARNING__", esc(report["avvertenza"]))
        .replace("__OBSERVED__", esc(report["rilevazione_confronto_utc"]))
        .replace("__PAIR__", esc(pair))
        .replace("__GRAPH_URL__", esc(graph_root + "4h"))
        .replace("__CARDS__", "".join(rows)))



# Identita scelta dal catalogo Kraken; nessun token privilegiato.
SPOT_KEY_RE = re.compile(r"[A-Za-z0-9_.-]{2,48}\Z")
SPOT_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,40}/[A-Za-z0-9._-]{1,40}\Z")


class KrakenMarketDataUnavailable(RuntimeError):
    """Data/source failure is not a user-invalid pair or timeframe."""


def spot_catalog(public_kraken=None):
    """Coppie AssetPairs attualmente online: non prova accessibilita sul conto."""
    fetch = public_kraken or desk.kraken
    raw = fetch("AssetPairs")
    if not isinstance(raw, dict):
        raise KrakenMarketDataUnavailable("Catalogo Kraken non verificabile")
    out = {}
    for key, row in raw.items():
        if not isinstance(key, str) or not SPOT_KEY_RE.fullmatch(key):
            continue
        if key.lower().endswith(".d") or not isinstance(row, dict):
            continue
        name = row.get("wsname")
        if row.get("status") != "online" or not isinstance(name, str):
            continue
        if not SPOT_NAME_RE.fullmatch(name):
            continue
        base, quote = name.split("/", 1)
        altname = row.get("altname")
        if not isinstance(altname, str) or not SPOT_KEY_RE.fullmatch(altname):
            altname = None
        out[key] = {"pair_key": key, "pair": name, "base": base, "quote": quote,
                    "altname": altname, "eligibilita_conto": "NON_VERIFICATA"}
    if not out:
        raise KrakenMarketDataUnavailable("Nessuna coppia online verificabile")
    return out


def spot_lookup(pair_key, catalog):
    if (not isinstance(pair_key, str) or not SPOT_KEY_RE.fullmatch(pair_key)
            or pair_key not in catalog):
        raise ValueError("Coppia assente o non online nel catalogo Kraken")
    return catalog[pair_key]


class KrakenPairMismatch(RuntimeError):
    """Kraken OHLC supplied candles under an unrelated market identifier."""


def checked_spot_ohlc(raw, meta):
    """Bind a single response market to the exact AssetPairs pair/altname.

    REST OHLC response symbols need not equal wsname; never trust the first
    non-'last' array and then label it with the requested pair.
    """
    if not isinstance(raw, dict):
        raise KrakenPairMismatch("Risposta OHLC non valida")
    symbols = [name for name in raw if name != "last"]
    accepted = {meta["pair_key"]}
    if meta.get("altname"):
        accepted.add(meta["altname"])
    if len(symbols) != 1 or symbols[0] not in accepted:
        raise KrakenPairMismatch("Identita mercato OHLC differente dalla coppia richiesta")
    return raw


def spot_request_pair(path, query):
    """Return None only for the selector route; reject missing/duplicate pairs."""
    if path == "/mercati/spot":
        return None
    values = urllib.parse.parse_qs(query, keep_blank_values=True).get("pair", [])
    if (path not in ("/grafico/spot", "/analisi/spot") or len(values) != 1
            or not SPOT_KEY_RE.fullmatch(values[0])):
        raise ValueError("Coppia non specificata o identificativo non valido")
    return values[0]


def spot_selector(catalog):
    """Lista navigabile delle coppie senza default e senza lettura portafoglio."""
    options = "".join(
        '<option value="' + html.escape(p["pair_key"], quote=True) + '">' +
        html.escape(p["pair"]) + ' · ' + html.escape(p["pair_key"]) + '</option>'
        for p in sorted(catalog.values(), key=lambda p: (p["pair"], p["pair_key"]))
    )
    return ("""<!doctype html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KDD · Coppie Kraken Spot</title>
<style>:root{color-scheme:dark;font-family:system-ui;background:#0b1221;color:#eaf0fa}
body{max-width:760px;margin:auto;padding:16px}a{color:#8aceff}
form{background:#18263c;padding:16px;border-radius:12px}
select,input,button{font:inherit;padding:10px;margin:10px 0;width:100%}
button{background:#80cbff;border:0;border-radius:9px;color:#06162b;font-weight:bold}
p{line-height:1.5}</style></head><body>
<p><a href="/">← Cruscotto</a></p><h1>Mercati Kraken Spot · scegli la coppia</h1>
<p>Catalogo pubblico AssetPairs online. La negoziabilita per il conto italiano
non e verificata. Nessuna coppia preselezionata; nessun ordine.</p>
<form method="get" action="/analisi/spot">
<label for="filtro">Cerca coppia per token, valuta o codice Kraken</label>
<input type="search" id="filtro" aria-controls="pair" autocomplete="off"
placeholder="Es. BTC, ADA, USDT, GBP">
<p id="risultati" role="status" aria-live="polite"></p>
<label for="pair">Coppia Kraken (base/quote)</label>
<select name="pair" id="pair" required><option value="">— Seleziona una coppia —</option>
__OPTIONS__</select>
<input type="hidden" name="tf" value="4h">
<button type="submit">Confronta 15m · 1H · 4H · 1D</button>
<button type="submit" formaction="/grafico/spot">Apri grafico della coppia</button>
</form><p>Confronto: quattro richieste OHLC pubbliche; grafico: una.
Solo candele chiuse, niente valori inventati.</p>
<script>
(() => {
  const search = document.getElementById('filtro');
  const select = document.getElementById('pair');
  const counter = document.getElementById('risultati');
  const all = Array.from(select.options).slice(1).map(o => [o.value, o.textContent]);
  function rebuild() {
    const needle = search.value.trim().toLocaleUpperCase('it-IT');
    // Kraken chiama XBT il BTC e talvolta XDG il DOGE.
    const translated = needle.replaceAll('BTC','XBT').replaceAll('DOGE','XDG');
    const found = needle ? all.filter(([k,t]) => {
      const haystack = (k + ' ' + t).toLocaleUpperCase('it-IT');
      return haystack.includes(needle) || haystack.includes(translated);
    }) : all;
    // Cap options shown simultaneously on mobile, NOT the underlying catalog.
    const maxVisible = 90;
    const choices = found.slice(0,maxVisible).map(([k,t]) => new Option(t,k));
    const placeholder = new Option('— Seleziona una coppia —', '');
    select.replaceChildren(placeholder,...choices);
    select.value = '';
    counter.textContent = found.length + ' coppie trovate su ' + all.length +
      (found.length > maxVisible ? '. Visualizzate le prime 90; affina la ricerca.' : '.');
  }
  search.addEventListener('input',rebuild);
  rebuild();
})();
</script>
</body></html>""".replace("__OPTIONS__", options))


def load_spot_chart(pair_key, timeframe, *, public_kraken=None, now=None):
    if timeframe not in grafico_4h.TIMEFRAMES:
        raise ValueError("Timeframe non valido")
    fetch = public_kraken or desk.kraken
    meta = spot_lookup(pair_key, spot_catalog(fetch))
    raw = fetch("OHLC", pair=pair_key, interval=grafico_4h.TIMEFRAMES[timeframe][0])
    # Pair/timeframe input was already validated. From here, ValueError is
    # malformed/insufficient upstream OHLC, not a client-side 400.
    try:
        series = grafico_4h.data_from_kraken_ohlc(
            checked_spot_ohlc(raw, meta), timeframe, now=now,
            pair=meta["pair"], token=meta["base"], pair_key=pair_key)
        return grafico_4h.page_from_data(series)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise KrakenMarketDataUnavailable("OHLC o grafico pubblico non verificabile") from exc


def load_spot_comparison(pair_key, *, public_kraken=None, now=None):
    fetch = public_kraken or desk.kraken
    meta = spot_lookup(pair_key, spot_catalog(fetch))
    now = now or dt.datetime.now(dt.timezone.utc)
    frames = {}
    for label, frame in (("15m", "15m"), ("1H", "1h"), ("4H", "4h"), ("1D", "1d")):
        try:
            raw = fetch("OHLC", pair=pair_key, interval=grafico_4h.TIMEFRAMES[frame][0])
            frames[label] = grafico_4h.data_from_kraken_ohlc(
                checked_spot_ohlc(raw, meta), frame, now=now,
                pair=meta["pair"], token=meta["base"],
                pair_key=pair_key)
        except (OSError, RuntimeError, ValueError, KeyError, IndexError, TypeError) as exc:
            frames[label] = {"errore": type(exc).__name__}
    return grafico_4h.compare_timeframes(frames, now=now, pair=meta["pair"])


def host_valido(host):
    return host == f"{HOST}:{PORT}"


class Handler(BaseHTTPRequestHandler):
    def check_host(self):
        if not host_valido(self.headers.get("Host", "")):
            self.send_error(403, "Destinazione locale non valida")
            return False
        return True

    def send_body(self, status, body, content_type):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, status, body):
        self.send_body(status, body, "text/html; charset=utf-8")

    def send_bytes(self, status, raw, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.check_host():
            return
        url = urllib.parse.urlsplit(self.path)
        if url.path in ("/mercati/spot", "/grafico/spot", "/analisi/spot"):
            query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
            try:
                pair_key = spot_request_pair(url.path, url.query)
                if pair_key is None:
                    self.send_html(200, spot_selector(spot_catalog()))
                    return
                if url.path == "/grafico/spot":
                    tf = query.get("tf", ["4h"])
                    if len(tf) != 1 or tf[0] not in grafico_4h.TIMEFRAMES:
                        self.send_html(400, "<h1>Timeframe non valido</h1>")
                        return
                    page = load_spot_chart(pair_key, tf[0])
                else:
                    summary = load_spot_comparison(pair_key)
                    page = render_sui_comparison(summary, pair_key=pair_key)
                self.send_html(200, page)
            except ValueError:
                self.send_html(400, "<h1>Coppia Kraken non valida o non online</h1>")
            except (OSError, RuntimeError, KeyError, TypeError, IndexError):
                self.send_html(503, "<h1>Kraken pubblico non disponibile</h1>")
            return
        if url.path == "/stato":
            self.send_body(200, json.dumps(job_snapshot(), ensure_ascii=False),
                           "application/json; charset=utf-8")
            return
        if url.path == "/analisi/sui-mtf":
            report = load_sui_comparison()
            self.send_html(200, render_sui_comparison(report))
            return
        if url.path == "/grafico/sui-4h":
            query = urllib.parse.parse_qs(url.query)
            frames = query.get("tf", ["4h"])
            if len(frames) != 1 or frames[0] not in grafico_4h.TIMEFRAMES:
                self.send_html(400, "<h1>Timeframe non valido</h1>"
                    "<p><a href='/grafico/sui-4h?tf=4h'>Torna al 4H</a></p>")
                return
            try:
                graph = load_sui_chart(frames[0])
            except (ValueError, KeyError, OSError, RuntimeError, TypeError):
                self.send_html(503, "<h1>Serie di candele chiuse non disponibile</h1>"
                    "<p>Dati Kraken assenti, incompleti o temporaneamente irraggiungibili. "
                    "Nessun prezzo o volume è stato inventato.</p>"
                    "<p><a href='/grafico/sui-4h?tf=4h'>Torna al 4H</a></p>")
                return
            self.send_html(200, graph)
            return
        assets = {
            "/asset/lightweight-charts.js": (
                "lightweight-charts-5.2.1.js", "application/javascript; charset=utf-8"),
            "/asset/lightweight-license": (
                "LIGHTWEIGHT_CHARTS_LICENSE.txt", "text/plain; charset=utf-8"),
            "/asset/lightweight-notice": (
                "LIGHTWEIGHT_CHARTS_NOTICE.txt", "text/plain; charset=utf-8"),
        }
        if url.path in assets:
            filename, kind = assets[url.path]
            f = desk.DIR / "vendor" / filename
            if not f.is_file():
                self.send_error(503, "Asset grafico assente")
                return
            self.send_bytes(200, f.read_bytes(), kind)
            return
        if url.path != "/":
            self.send_error(404)
            return
        p = desk.DIR / "cruscotto.html"
        if not p.is_file():
            self.send_html(503, "<h1>Cruscotto assente</h1><p>Avvia un aggiornamento da Termux.</p>")
            return
        result = urllib.parse.parse_qs(url.query).get("esito", [""])[0]
        self.send_html(200, with_controls(p.read_text(encoding="utf-8"), result))

    def do_POST(self):
        if not self.check_host():
            return
        if urllib.parse.urlsplit(self.path).path != "/aggiorna":
            self.send_error(404)
            return
        # Chrome Traduttore può inviare Origin:null: restano obbligatori Host e token.
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if not 0 < n <= 1024:
            self.send_error(400, "Dimensione richiesta non valida")
            return
        params = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", errors="replace"))
        received = params.get("token", [""])[0]
        if not hmac.compare_digest(received, TOKEN):
            self.send_error(403, "Verifica richiesta non riuscita")
            return
        try:
            started = start_refresh()
        except Exception:
            self.send_error(503, "Impossibile avviare aggiornamento")
            return
        self.send_response(303)
        self.send_header("Location", "/?esito=" + ("avviato" if started else "occupato"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def log_message(self, fmt, *args):
        # Nessun contenuto POST o token in log.
        pass


def main():
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        print(f"Kraken Decision Desk pronto: http://{HOST}:{PORT}/", flush=True)
        print("Termux CTRL+C per fermare il servizio. Nessuna API privata.", flush=True)
        server.serve_forever(poll_interval=0.3)


if __name__ == "__main__":
    main()
