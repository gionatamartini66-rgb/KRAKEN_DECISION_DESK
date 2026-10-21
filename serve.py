#!/usr/bin/env python3
"""Cruscotto Kraken locale: HTTP soltanto 127.0.0.1, dati pubblici, nessun ordine."""
import datetime as dt
import hmac
import html
import json
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
        "</form><p><a style='font-weight:700;color:#8aceff' href='/grafico/sui-4h'>"
        "📈 Grafico SUI/EUR · 15m / 1H / 4H / 1D</a></p>"
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
        if url.path == "/stato":
            self.send_body(200, json.dumps(job_snapshot(), ensure_ascii=False),
                           "application/json; charset=utf-8")
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
