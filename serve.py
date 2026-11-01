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


def _decision_origin(token, displayed, records, observed_at):
    """Attribute a displayed decision only if its source record reproduces it."""
    unknown = "Stato decisionale del report KDD (origine non accertata)"
    if not isinstance(token, str) or not isinstance(displayed, str) or observed_at is None:
        return unknown
    matches = [r for r in records if isinstance(r, dict) and isinstance(r.get("token"), str)
               and r["token"].strip().upper() in (token.upper(), "PORTAFOGLIO")]
    if not matches:
        return unknown
    try:
        if desk.decision_state(token.upper(), records, observed_at) != displayed:
            return unknown
        chosen = max(matches, key=lambda r: r.get("creata_utc", ""))
        if chosen["token"].strip().upper() == "PORTAFOGLIO":
            return "Criterio generale PORTAFOGLIO applicato alla posizione (non decisione individuale)"
        return "Decisione specifica del token da decisioni.jsonl"
    except (KeyError, TypeError, ValueError):
        return unknown


def _decision_age(value, *, now=None, minutes=30):
    """Recheck each clock on page read, never inherit another source's freshness."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        observed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("Missing UTC offset")
        delta = (now - observed).total_seconds() / 60
        return "RECENTE" if -2 <= delta <= minutes else "DA AGGIORNARE"
    except (TypeError, AttributeError, ValueError, OverflowError):
        return "ORA NON VERIFICABILE"


def _decision_pair_links(key, *, frames=None):
    """Direct links only after an actual catalogued pair identity is documented."""
    esc = lambda v: html.escape(str(v), quote=True)
    links = ["<a href='/analisi/spot?pair=" + esc(key) +
             "'>Confronta 15m / 1H / 4H / 1D</a>"]
    for label, tf in (("15m", "15m"), ("1H", "1h"), ("4H", "4h"), ("1D", "1d")):
        state = (frames.get(label, {}).get("stato") if isinstance(frames, dict)
                 and isinstance(frames.get(label), dict) else "NON DOCUMENTATO")
        links.append("<a href='/grafico/spot?pair=" + esc(key) + "&amp;tf=" +
                     tf + "'>" + label + "</a> " + esc(state))
    return " · ".join(links)


def _decision_pair_identity(token, pair, key, base):
    """Validate source labels; the chart route rechecks current Kraken AssetPairs."""
    if (not isinstance(pair, str) or not SPOT_NAME_RE.fullmatch(pair)
            or not isinstance(key, str) or not SPOT_KEY_RE.fullmatch(key)
            or not isinstance(token, str)):
        return False
    actual, quote = pair.split("/", 1)
    canonical = lambda v: {"XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE",
                           "XXDG": "DOGE"}.get(v, v)
    return (canonical(actual) == canonical(token)
            and canonical(base) == canonical(actual)
            and quote in ("EUR", "USD", "USDC"))


def decision_home():
    """Decision-first composition of the existing KDD report and GPT archive."""
    esc = lambda value: html.escape(str(value), quote=True)
    now = dt.datetime.now(dt.timezone.utc)
    blocks = ["<section id='kdd-decisioni' aria-label='Quadro decisionale integrato'>"
              "<h2>Quadro decisionale · patrimonio e Spot</h2>"]
    try:
        report = desk.load("ultimo_report.json", {})
    except (OSError, ValueError, UnicodeError):
        report = None
    if not isinstance(report, dict) or not isinstance(report.get("posizioni"), list):
        blocks.append("<p role='status'>Quadro aggiunto non disponibile: report mancante "
                      "o non verificabile (report assente, incompleto o non leggibile). "
                      "Il cruscotto originale resta consultabile.</p>")
        report = None

    # Read historical proposals without equating reception, approval and execution.
    proposal, proposal_state, proposal_sha, events = None, "ASSENTE", None, []
    try:
        from scripts import kdd_drive_exchange as exchange
        exchange.receive_synced()
        item = exchange.pending()
        approved = exchange.bridge.load_archive()
        events = exchange.decision_history()
        if item:
            candidate, _bundle = item
            proposal_sha = exchange.bridge.digest(candidate)
            dismissed = [e["stato"] for e in events
                         if e["versione_sha256"] == proposal_sha
                         and e["stato"] in ("RIFIUTATA", "RINVIATA")]
            proposal_state = ("APPROVATA · ARCHIVIO" if proposal_sha in approved else
                              dismissed[-1] if dismissed else "NON APPROVATA · IN ATTESA DI DECISIONE")
            proposal = candidate
    except Exception:
        proposal, proposal_state = None, "ARCHIVIO NON VERIFICABILE · STOP"

    if report is None:
        blocks.append("<p>Proposta GPT: " + esc(proposal_state) +
                      ". <a href='/gpt'>Apri il ponte e l'archivio</a>.</p>")
        if proposal is not None:
            blocks.append("<p>Versione " + esc(proposal_sha) + " · fotografia GPT " +
                          esc(proposal.get("snapshot_utc", "n.d.")) +
                          ". Nessun giudizio attribuito a un portafoglio non leggibile.</p>")
            if isinstance(proposal.get("posizioni"), list):
                blocks.append("<details><summary>Posizioni della proposta storica "
                              "(non riconciliate col report corrente)</summary>" +
                              "".join("<p>" + esc(row.get("token", "?")) + " · GPT: " +
                                      esc(row.get("azione", "n.d.")) + "</p>"
                                      for row in proposal["posizioni"] if isinstance(row, dict)) +
                              "</details>")
            related = [e for e in events if e["versione_sha256"] == proposal_sha]
            latest, unordered = exchange.latest_events(related)
            if unordered:
                blocks.append("<p>Eventi più recenti nel medesimo secondo: "
                              "ordine reciproco non documentato.</p>")
            for e in latest:
                blocks.append("<p>Evento autore · " +
                              esc(exchange.event_label(e["stato"])) + " · " +
                              esc(e["nota"]) + "</p>")
        return "".join(blocks) + "</section>"

    try:
        decisions = desk.load_decisions()
        observed = dt.datetime.fromisoformat(report["rilevazione_utc"])
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        decisions, observed = [], None
    positions = report["posizioni"]
    complete = report.get("posizioni_valorizzate")
    incomplete = report.get("posizioni_incomplete")
    state = report.get("stato_totale", "NON VERIFICATO")
    numeric_total = report.get("totale_stimato_eur")
    valued = (isinstance(numeric_total, (int, float)) and not isinstance(numeric_total, bool)
              and math.isfinite(numeric_total) and state in ("PARZIALE", "COMPLETO")
              and isinstance(complete, int) and complete > 0)
    total = desk.fmt(numeric_total) + " €" if valued else "non disponibile"
    market_time = report.get("rilevazione_utc")
    market_fresh = _decision_age(market_time, now=now)
    balance = report.get("saldo_stato")
    balance = balance if isinstance(balance, dict) else {}
    balance_time = balance.get("acquisizione_saldo_utc")
    balance_fresh = _decision_age(balance_time, now=now)
    blocks.append("<p>Patrimonio: " + esc(state) + " · " +
                  str(len(positions)) + " posizioni" +
                  " · valorizzate " + esc(complete if isinstance(complete, int) else "n.d.") +
                  " · incomplete " + esc(incomplete if isinstance(incomplete, int) else "n.d.") +
                  " · totale indicativo EUR " + esc(total) +
                  (" (parziale, NON intero patrimonio)" if state == "PARZIALE" else "") +
                  "</p>")
    blocks.append("<p><b>Mercato pubblico:</b> fotografia " + esc(market_time or "assente") +
                  " · " + esc(market_fresh) + ".</p><p><b>Saldo privato:</b> fonte " +
                  esc(balance.get("origine", "non documentata")) + " · acquisizione " +
                  esc(balance_time or "assente") + " · " + esc(balance_fresh) +
                  ". La freschezza del mercato non aggiorna i saldi.</p>")
    dossier_state = report.get("dossier_stato")
    if isinstance(dossier_state, dict):
        blocks.append("<p><b>Copertura dossier GPT:</b> " +
                      esc(dossier_state.get("stato", "NON VERIFICABILE")) +
                      " · idoneità " +
                      esc(dossier_state.get("idoneita_analisi_patrimoniale", "NON ACCERTATA")) +
                      ".</p>")

    if proposal is None:
        blocks.append("<article><h3>Proposta GPT · " + esc(proposal_state) +
                      "</h3><p>Nessuna valutazione patrimoniale attribuibile per questa home. "
                      "KDD presenta osservazioni, non decisioni GPT.</p>"
                      "<p><a href='/gpt'>Consulta o importa la proposta</a></p></article>")
    elif (not isinstance(proposal, dict) or
          not isinstance(proposal.get("posizioni"), list) or
          len(proposal["posizioni"]) != len(positions) or
          any(not isinstance(row, dict) or not isinstance(pos, dict) or
              row.get("indice") != i or row.get("token") != pos.get("token")
              for i, (row, pos) in enumerate(zip(proposal["posizioni"], positions)))):
        # Version still exists, but its wallet identity cannot be assumed current.
        blocks.append("<article><h3>Proposta GPT · " + esc(proposal_state) +
                      "</h3><p>Versione " + esc((proposal_sha or "")[:16]) +
                      ": identità/numero posizioni non riconciliabile con il report. "
                      "Non attribuire giudizi ai token correnti.</p>"
                      "<p><a href='/gpt'>Apri proposta originale</a></p></article>")
        proposal = None
    else:
        blocks.append("<article><h3>Proposta GPT · " + esc(proposal_state) +
                      "</h3><p>Versione SHA256 " + esc(proposal_sha) +
                      " · fotografia GPT " + esc(proposal.get("snapshot_utc", "n.d.")) +
                      " · " + esc(_decision_age(proposal.get("snapshot_utc"), now=now)) +
                      ". Storico: un refresh del KDD non ricalcola il ragionamento GPT.</p>"
                      "<p><b>Scenario:</b> " + esc(proposal.get("scenario", "")) +
                      "</p><p><b>Alternativa:</b> " +
                      esc(proposal.get("scenario_alternativo", "")) +
                      "</p><p><b>Rischi:</b> " + esc(proposal.get("rischi_comuni", "")) +
                      "</p><p><b>Liquidità/limiti:</b> " +
                      esc(proposal.get("liquidita", "")) +
                      "</p><p><b>Riesame:</b> " + esc(proposal.get("revisione", "")) +
                      "</p><p><a href='/gpt'>Apri fonte, storico e scelta dell'autore</a>. "
                      "La proposta non dimostra un ordine eseguito.</p></article>")

    # Pair provenance belongs to the same completed snapshot and wallet digest.
    dossier = None
    if market_fresh == "RECENTE":
        try:
            candidate = desk.load("dossier_multifonte.json", {})
            state_doc = report.get("dossier_stato")
            if (isinstance(candidate, dict) and isinstance(state_doc, dict)
                    and candidate.get("kraken_istantanea_utc") == market_time
                    and candidate.get("fotografia_portafoglio_sha256")
                    and candidate.get("fotografia_portafoglio_sha256") ==
                        state_doc.get("fotografia_portafoglio_sha256")
                    and isinstance(candidate.get("patrimonio_4tf"), dict)
                    and len(candidate["patrimonio_4tf"].get("posizioni", [])) == len(positions)):
                dossier = candidate["patrimonio_4tf"]["posizioni"]
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            dossier = None

    blocks.append("<h3>Patrimonio strategico a gestione attiva</h3>"
                  "<p>Ogni asset resta riesaminabile: mantenere, incrementare, alleggerire, "
                  "uscire, ruotare oppure rinviare richiede ragioni e condizioni. "
                  "La valutazione KDD è distinta dal giudizio GPT e dalla scelta dell'autore.</p>")
    priorities = []
    rows = []
    for i, holding in enumerate(positions):
        if not isinstance(holding, dict):
            rows.append("<article>Posizione " + str(i+1) +
                        ": struttura non valida; quantità e giudizio non attribuibili.</article>")
            continue
        token = str(holding.get("token", "?"))
        quantity = holding.get("quantita")
        qtext = "Quantità non nota" if quantity is None else "Quantità: " + str(quantity)
        value = holding.get("valore_eur")
        vtext = (desk.fmt(value) + " €" if isinstance(value, (int, float))
                 and not isinstance(value, bool) and math.isfinite(value)
                 else "valore indicativo non disponibile")
        technical = holding.get("note")
        technical = "; ".join(str(x) for x in technical) if isinstance(technical, list) and technical else holding.get("errore", "Nessuna conclusione tecnica documentata")
        source = _decision_origin(token, holding.get("decisione"), decisions, observed)
        gpt = proposal["posizioni"][i] if proposal else None
        important = bool(holding.get("errore")) or (gpt is not None and
                    gpt.get("azione") not in ("MANTENERE", "RINVIARE"))
        if important:
            priorities.append(token + ": " + ("dati incompleti" if holding.get("errore")
                                               else "ipotesi GPT " + str(gpt.get("azione"))))
        body = ("<article><h4><b>" + esc(token) + "</b></h4><p>" + esc(qtext) +
                " · " + esc(vtext) + "</p><p><b>KDD (osservazione):</b> " +
                esc(technical) + "</p><p><b>Scelta registrata:</b> " +
                esc(holding.get("decisione", "nessuna")) + " · " + esc(source) + "</p>")
        if gpt:
            body += ("<p><b>GPT · " + esc(proposal_state) + ":</b> " +
                     esc(gpt.get("azione")) + " — " + esc(gpt.get("tesi")) +
                     "</p><p><b>Alternativa:</b> " + esc(gpt.get("alternativa")) +
                     " · <b>Rischi:</b> " + esc(gpt.get("rischi")) +
                     "</p><p><b>Invalidazione:</b> " + esc(gpt.get("invalidazione")) +
                     " · <b>Riesame:</b> " + esc(gpt.get("riesame")) +
                     "</p><p><b>Evidenze dichiarate GPT:</b> " +
                     esc(gpt.get("evidenze")) + " · <b>Costi dichiarati GPT:</b> " +
                     esc(gpt.get("costi")) + "</p>")
        else:
            body += "<p>GPT: nessuna valutazione collegabile a questa posizione.</p>"
        entry = dossier[i] if dossier else None
        if (isinstance(entry, dict) and entry.get("indice") == i and
                entry.get("token") == token and
                _decision_pair_identity(token, entry.get("coppia"),
                                        entry.get("pair_key"), entry.get("asset_base"))):
            body += ("<p><b>Coppia documentata da dossier KDD:</b> " +
                     esc(entry["coppia"]) + ". Elegibilità sul conto non verificata. " +
                     _decision_pair_links(entry["pair_key"], frames=entry.get("timeframe")) +
                     "</p>")
        else:
            body += "<p>Coppia e grafici diretti: identità non riconciliata con il dossier corrente.</p>"
        rows.append(body + "</article>")
    if priorities:
        blocks.append("<p><b>Attenzioni da esaminare (non ordini):</b> " +
                      esc("; ".join(priorities[:3])) +
                      (" · altre nel patrimonio completo" if len(priorities) > 3 else "") +
                      ".</p>")
    else:
        blocks.append("<p>Nessuna priorità deducibile da questi dati: "
                      "non equivale a una decisione di mantenere tutto il patrimonio.</p>")
    blocks.append("<details id='kdd-all-positions'><summary>Visualizza tutte le posizioni (" +
                  str(len(positions)) + ") e le alternative</summary>" +
                  "".join(rows) + "</details>")

    blocks.append("<h3>Opportunità operative Spot · segnalazioni KDD</h3>")
    candidates = report.get("schede_v02")
    if not isinstance(candidates, list) or not candidates:
        blocks.append("<p>Nessuna opportunità tecnica documentata in questo report. "
                      "Occorre confrontare mercato e alternative; non è una decisione automatica di attesa.</p>")
    else:
        shown = 0
        old_plan = report.get("piano_gpt")
        for item in candidates:
            if shown >= 3:
                break
            if not isinstance(item, dict):
                continue
            shown += 1
            token = str(item.get("token", "?"))
            body = ("<article><h4>" + esc(token) + " · KDD: " +
                    esc(item.get("esito", "NON VALUTATO")) + "</h4><p>" +
                    esc(item.get("perche_selezionato", "Selezione non motivata")) +
                    " · " + esc(item.get("sintesi", "")) +
                    "</p><p>Alternativa tecnica e criticità: " +
                    esc("; ".join(str(x) for x in (item.get("criticita") or [])) or
                        "Confronto da verificare nel dossier") + ".</p>")
            pair = item.get("coppia_analisi")
            options = item.get("alternative")
            chosen = None
            if market_fresh == "RECENTE" and isinstance(options, list):
                matching = [alt for alt in options if isinstance(alt, dict)
                            and alt.get("pair") == pair
                            and _decision_pair_identity(token, pair, alt.get("pair_key"),
                                                        pair.split("/", 1)[0] if isinstance(pair, str) else None)]
                if len(matching) == 1:
                    chosen = matching[0]["pair_key"]
            if chosen:
                body += ("<p><b>Coppia Kraken esaminata:</b> " + esc(pair) +
                         " · " + _decision_pair_links(chosen) + "</p>")
            else:
                body += "<p>Coppia di approfondimento non verificabile su questo snapshot: apri il catalogo.</p>"
            alternatives = [alt.get("pair") for alt in (options or [])
                            if isinstance(alt, dict) and alt.get("pair") != pair] if isinstance(options, list) else []
            body += ("<p>Altre coppie da confrontare: " +
                     esc(", ".join(str(x) for x in alternatives) or "non documentate") +
                     ". La negoziabilità del conto non è attestata.</p>")
            costs = item.get("costi_roundtrip")
            body += ("<p>Costi: " +
                     ("simulazioni KDD nel dettaglio originale; non provano fill"
                      if isinstance(costs, list) and costs else "nessun costo utilizzabile documentato") +
                     ".</p>")
            if (isinstance(old_plan, dict) and "errore" not in old_plan
                    and old_plan.get("mercato") == "SPOT"
                    and old_plan.get("token") == token and old_plan.get("coppia") == pair):
                body += ("<p><b>GPT · vecchio piano Spot singolo-token:</b> " +
                         esc(old_plan.get("azione")) + " · " +
                         esc(old_plan.get("tesi")) + "</p><p>Ingresso: " +
                         esc(old_plan.get("condizione_ingresso")) +
                         " · invalidazione: " + esc(old_plan.get("condizione_invalidazione")) +
                         " · uscita: " + esc(old_plan.get("condizione_uscita")) +
                         " · capitale: " + esc(old_plan.get("capitale")) +
                         " · riesame: " + esc(old_plan.get("revisione")) +
                         ". Fotografia GPT " + esc(old_plan.get("snapshot_kraken_utc")) +
                         " · " + esc(_decision_age(old_plan.get("snapshot_kraken_utc"), now=now)) +
                         ".</p>")
            else:
                body += ("<p><b>GPT:</b> nessuna proposta operativa validata e collegata "
                         "a questa coppia. Lo scanner non indica un acquisto, "
                         "un ingresso, un importo o un ordine.</p>")
            blocks.append(body + "</article>")
    blocks.append("<p><a href='/mercati/spot'>Esplora il catalogo completo Kraken Spot</a>"
                  " · <a href='/gpt'>Discuti le ipotesi in ChatGPT e consulta decisioni/storico</a>.</p>")
    return "".join(blocks) + "</section>"

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
        "<p><a href='/gpt'>📄 Proposte GPT su Drive</a></p>" 
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
    # The bridge is nonessential to the home: an unreadable archive must never
    # take Spot navigation, wallet report or refresh controls offline.
    try:
        # Delay optional bridge import: malformed or unavailable G2 code cannot
        # prevent localhost Spot dashboard from starting.
        from scripts import kdd_bridge_g2 as bridge_g2
        portfolio_proposals = bridge_g2.approved_html()
    except Exception:
        portfolio_proposals = ("<section id='kdd-gpt-patrimonio' role='status'>"
                               "<h2>Proposte patrimoniali GPT</h2>"
                               "<p>Archivio GPT temporaneamente non verificabile: STOP. "
                               "Nessuna proposta è stata certificata.</p></section>")
    try:
        decision_panel = decision_home()
    except Exception:
        # Never let this optional overlay prevent the intact original home from loading.
        decision_panel = ("<section id='kdd-decisioni' role='status'><h2>Quadro decisionale</h2>"
                          "<p>Riepilogo aggiunto non disponibile. "
                          "Patrimonio originale, Spot, grafici e aggiornamento restano accessibili.</p></section>")
    if target not in page:
        # Unexpected legacy markup: do not discard the original HTML/navigation.
        return page.replace("</body>", toolbar + js + decision_panel + portfolio_proposals + "</body>", 1)
    before, after = page.split(target, 1)
    if "</header>" not in before:
        return before + toolbar + js + decision_panel + portfolio_proposals + target + after
    header, legacy = before.split("</header>", 1)
    # Keep existing Spot plan and archives intact but secondary. Their script
    # freshness callbacks continue running; no archive or contract is rewritten.
    old_spot = ("<details id='kdd-legacy-spot'><summary>Apri precedenti piani Spot "
                "singolo-token e verifiche storiche</summary>" + legacy +
                "</details>")
    portfolio = portfolio_proposals
    archive = ("<details id='kdd-approved-archive'><summary>Apri archivio proposte "
               "patrimoniali approvate</summary>" + portfolio + "</details>")
    part2 = "<h2>2 · Candidati da valutare</h2>"
    part3 = "<h2>3 · Macroeconomia e geopolitica</h2>"
    if part2 in after and part3 in after:
        old_wallet, remaining = after.split(part2, 1)
        old_scan, last = remaining.split(part3, 1)
        diagnostics = (
            "<details id='kdd-wallet-diagnostics'><summary>Apri patrimonio originale "
            "e diagnostica dettagliata</summary>" + target + old_wallet + "</details>"
            "<details id='kdd-spot-diagnostics'><summary>Apri schede scanner, "
            "costi e dati tecnici completi</summary>" + part2 + old_scan + "</details>" +
            part3 + last)
    else:
        # Source markup changed: retain it verbatim rather than moving sections
        # by unverified text boundaries.
        diagnostics = target + after
    return (header + "</header>" + toolbar + js + decision_panel +
            old_spot + archive + diagnostics)


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


def render_sui_comparison(report, *, pair_key=None, home_url="/"):
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
    pair_label = spot_friendly_label(pair) if pair_key is not None else pair
    volume_base = {"XBT": "BTC", "XDG": "DOGE"}.get(base, base)
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
            f'<p>Volume ultima candela: {esc(volume_text)} {esc(volume_base)}; '
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
    if home_url not in ("/", "http://127.0.0.1:8765/"):
        raise ValueError("Destinazione non valida")
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
<p><a href="__HOME_URL__">← Cruscotto</a> · <a href="/mercati/spot">Seleziona coppia</a> · <a href="__GRAPH_URL__">Grafico 4H</a></p>
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
<p><a href="__HOME_URL__">← Torna al cruscotto</a></p>
</body></html>"""
        .replace("__HOME_URL__", esc(home_url))
        .replace("__STATE__", esc(report["stato"]))
        .replace("__PICTURE__", esc(picture))
        .replace("__WARNING__", esc(report["avvertenza"]))
        .replace("__OBSERVED__", esc(report["rilevazione_confronto_utc"]))
        .replace("__PAIR__", esc(pair_label))
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
    # A REST response alias must resolve to exactly one market in the
    # *whole* catalog, including non-online REST keys. A synthetic collision
    # must never let candles of B be labelled with A's selected pair.
    owner = {}
    for key, meta in out.items():
        for symbol in (key, meta["altname"]):
            if symbol is None:
                continue
            if symbol in raw and symbol != key:
                raise KrakenMarketDataUnavailable("Identità Kraken REST/alias ambigua")
            previous = owner.setdefault(symbol, key)
            if previous != key:
                raise KrakenMarketDataUnavailable("Identità Kraken alias ambigua")
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


def spot_friendly_label(pair):
    """Show common token name while preserving Kraken's actual market symbol."""
    base, quote = pair.split("/", 1)
    aliases = {"XBT": "BTC", "XDG": "DOGE"}
    if base in aliases:
        return aliases[base] + "/" + quote + " (Kraken " + pair + ")"
    return pair


def spot_observed_candidates(catalog, snapshot):
    """Use KDD's EXISTING ranked public scan, never rank by alphabet or invent setups.

    Link only an exact catalogued Kraken pair. Do not read portfolio or balances.
    """
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("schede_v02")
    if not isinstance(raw, list):
        return []
    found = []
    used = set()
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        name = item.get("coppia_analisi")
        options = item.get("alternative")
        if not isinstance(name, str) or not isinstance(options, list):
            continue
        key = None
        for candidate in options:
            if not isinstance(candidate, dict) or candidate.get("pair") != name:
                continue
            possible = candidate.get("pair_key")
            if (isinstance(possible, str) and possible in catalog
                    and catalog[possible]["pair"] == name):
                key = possible
                break
        if key is None or key in used:
            continue
        base = catalog[key]["base"].upper()
        normalized = {"XBT": "BTC", "XDG": "DOGE"}.get(base, base)
        if str(item.get("token") or "").upper() != normalized:
            continue
        used.add(key)
        found.append({
            "pair_key": key, "pair": name,
            "categoria": str(item.get("categoria") or "Caso da esaminare")[:90],
            "esito": str(item.get("esito") or "Analisi da verificare")[:90],
            "perche": str(item.get("perche_selezionato") or "")[:300],
            "sintesi": str(item.get("sintesi") or "")[:300],
            "evidenze": [str(x)[:180] for x in item.get("evidenze", [])[:5]
                          if isinstance(x, str)] if isinstance(item.get("evidenze"), list) else [],
            "criticita": [str(x)[:180] for x in item.get("criticita", [])[:5]
                          if isinstance(x, str)] if isinstance(item.get("criticita"), list) else [],
        })
        if len(found) == 6:
            break
    return found


def spot_priority_panel(catalog, snapshot, *, now=None, preview=False):
    """Shortlist from last completed KDD scan, with observation date and direct links."""
    esc = lambda value: html.escape(str(value), quote=True)
    rows = spot_observed_candidates(catalog, snapshot)
    home = "http://127.0.0.1:8765/" if preview else "/"
    date = snapshot.get("rilevazione_utc") if isinstance(snapshot, dict) else None
    now = now or dt.datetime.now(dt.timezone.utc)
    stale = True
    if isinstance(date, str):
        try:
            observed = dt.datetime.fromisoformat(date.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("UTC offset absent")
            age = (now - observed).total_seconds() / 60
            stale = age > 30 or age < -2
            status = ("RILEVAZIONE DA AGGIORNARE" if stale
                      else "Rilevazione recente")
            date_info = esc(date[:40]) + " · " + status
        except ValueError:
            date_info = "Orario della rilevazione non verificabile"
    else:
        date_info = "Rilevazione KDD non disponibile"
    if not rows:
        return ('<section class="priority"><h2>Segnalazioni già individuate da KDD</h2>'
                '<p>Nessun caso nell’ultima selezione KDD disponibile qui. '
                'Posizioni, segnalazioni e piani restano nel cruscotto originale; '
                'il catalogo sotto resta esplorabile.</p></section>')
    cards = []
    for c in rows:
        key = urllib.parse.quote(c["pair_key"], safe="")
        graph = "/grafico/spot?pair=" + key + "&amp;tf=4h"
        compare = "/analisi/spot?pair=" + key
        cards.append(
            '<article class="candidate"><h3>' + esc(spot_friendly_label(c["pair"])) + '</h3>'
            '<p><strong>' + esc(c["esito"]) + '</strong> · ' + esc(c["categoria"]) + '</p>'
            + ('<p><strong>Motivo della selezione:</strong> ' + esc(c["perche"]) + '</p>' if c["perche"] else "")
            + ('<p>' + esc(c["sintesi"]) + '</p>' if c["sintesi"] else "")
            + ('<p><strong>Elementi osservati:</strong> ' + esc("; ".join(c["evidenze"])) + '</p>' if c["evidenze"] else "")
            + ('<p><strong>Criticità:</strong> ' + esc("; ".join(c["criticita"])) + '</p>' if c["criticita"] else "")
            + '<p class="actions"><a href="' + graph + '">Grafico 4H</a>'
            '<a href="' + compare + '">Confronta 15m · 1H · 4H · 1D</a></p>'
            '</article>')
    heading = ("Segnalazioni precedenti: dati da aggiornare" if stale
               else "Da esaminare: selezione KDD")
    link = ('<p class="warning">Queste segnalazioni sono vecchie. '
            '<a href="' + html.escape(home, quote=True) + '">Apri KDD completo e aggiorna</a>. '
            'I grafici si aggiornano quando li apri, ma non aggiornano lo scanner.</p>'
            if stale else "")
    return ('<section class="priority"><h2>' + heading + '</h2>'
            '<p class="source">Ultimo scanner KDD · ' + date_info +
            '. Questi casi non sono ordini né segnali di acquisto; '
            'la negoziabilità del conto non è verificata.</p>'
            + link + "".join(cards) + '</section>')


def spot_selector(catalog, snapshot=None, *, now=None, preview=None):
    """Casi già selezionati da KDD, poi ricerca completa di qualunque coppia."""
    if snapshot is None:
        try:
            snapshot = desk.load("ultima_rilevazione.json", {})
        except (OSError, ValueError, TypeError):
            snapshot = {}
    if preview is None:
        preview = PORT != 8765
    priority = spot_priority_panel(catalog, snapshot, now=now, preview=preview)
    home = "http://127.0.0.1:8765/" if preview else "/"
    intro = ("Questa è una preview pubblica isolata, senza posizioni, piani o aggiornamento."
             if preview else "Questa sezione appartiene al KDD patrimoniale originale.")
    options = "".join(
        '<option value="' + html.escape(p["pair_key"], quote=True) + '">' +
        html.escape(spot_friendly_label(p["pair"])) + ' · ' + html.escape(p["pair_key"]) + '</option>'
        for p in sorted(catalog.values(), key=lambda p: (p["pair"], p["pair_key"]))
    )
    return ("""<!doctype html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KDD · Coppie Kraken Spot</title>
<style>:root{color-scheme:dark;font-family:system-ui;background:#0b1221;color:#eaf0fa}
body{max-width:760px;margin:auto;padding:16px}a{color:#8aceff}
.priority{background:#111c30;border:1px solid #34415d;border-radius:12px;padding:16px;margin:20px 0}
.priority h2{margin-top:0}.candidate{background:#192a43;border-radius:10px;padding:12px;margin:12px 0}
.candidate h3{margin:0}.candidate p{margin:8px 0}.actions{display:flex;flex-wrap:wrap;gap:12px}
.actions a{display:inline-block;padding:8px 10px;background:#244967;border-radius:8px}
.source{font-size:.92rem;color:#d2dae8}.warning{color:#ffdc92;font-weight:600}
.context{background:#203652;border-left:4px solid #8aceff;padding:12px 16px;border-radius:8px}
form{background:#18263c;padding:16px;border-radius:12px}
select,input,button{font:inherit;padding:10px;margin:10px 0;width:100%}
button{background:#80cbff;border:0;border-radius:9px;color:#06162b;font-weight:bold}
p{line-height:1.5}</style></head><body>
<p><a href="__HOME_URL__">← Torna al cruscotto KDD</a></p>
<h1>Mercati Kraken Spot</h1>
<p class="context"><b>__INTRO__</b>
Per aggiornare prezzi, posizioni e segnalazioni, usa
<a href="__HOME_URL__">il cruscotto KDD e il pulsante Aggiorna</a>.
Qui i grafici interrogano Kraken quando li apri; il catalogo non rinnova lo scanner.</p>
<p>BTC è chiamato XBT da Kraken: BTC/USDC e XBT/USDC sono la stessa coppia.
Catalogo pubblico AssetPairs online; la negoziabilità per il conto italiano
non è verificata. Nessuna coppia preselezionata e nessun ordine.</p>
__PRIORITY__
<h2>Esplora qualsiasi altra coppia Kraken Spot</h2>
<p>Scrivi un token o una valuta per cercare in tutto il catalogo, non soltanto tra le prime lettere.</p>
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
    }) : [];
    // Empty until search: never flood the user with A-to-Z entries.
    // Cap options shown simultaneously on mobile, NOT the underlying catalog.
    const maxVisible = 90;
    const choices = found.slice(0,maxVisible).map(([k,t]) => new Option(t,k));
    const placeholder = new Option('— Seleziona una coppia —', '');
    select.replaceChildren(placeholder,...choices);
    select.value = '';
    counter.textContent = needle ?
      found.length + ' coppie trovate su ' + all.length +
        (found.length > maxVisible ? '. Visualizzate le prime 90; affina la ricerca.' : '.') :
      'Catalogo: ' + all.length + ' coppie. Scrivi un token per vedere i risultati.';
  }
  search.addEventListener('input',rebuild);
  rebuild();
})();
</script>
</body></html>""".replace("__OPTIONS__", options).replace("__PRIORITY__", priority)
            .replace("__HOME_URL__", html.escape(home, quote=True))
            .replace("__INTRO__", html.escape(intro, quote=True)))


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
        if meta["base"] in ("XBT", "XDG"):
            shown = {"XBT": "BTC", "XDG": "DOGE"}[meta["base"]]
            series["display_pair"] = shown + "/" + meta["quote"]
            series["display_token"] = shown
            series["source"] += " · Kraken usa " + meta["base"] + " per " + shown
        home = "http://127.0.0.1:8765/" if PORT != 8765 else "/"
        return grafico_4h.page_from_data(series, now=now, home_url=home)
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
        if url.path == "/gpt":
            try:
                from scripts import kdd_drive_exchange as exchange
                self.send_html(200, exchange.render_page(TOKEN))
            except Exception:
                self.send_html(503, "<h1>Ponte Drive non disponibile</h1>"
                                   "<p>Il KDD Spot resta accessibile.</p>")
            return
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
                    home = "http://127.0.0.1:8765/" if PORT != 8765 else "/"
                    page = render_sui_comparison(summary, pair_key=pair_key,
                                                 home_url=home)
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
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/gpt/prepara", "/gpt/ricevi", "/gpt/conferma", "/gpt/decisione"):
            if not hmac.compare_digest(self.headers.get("X-KDD-Token", ""), TOKEN):
                self.send_error(403, "Verifica richiesta non riuscita")
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
                if not 0 <= n <= 8_000_000:
                    raise ValueError("Dimensione non valida")
                raw = self.rfile.read(n)
                if len(raw) != n:
                    raise ValueError("Lettura incompleta")
                from scripts import kdd_drive_exchange as exchange
                reply = exchange.handle(path.rsplit("/", 1)[-1], raw)
                self.send_body(200, reply, "text/plain; charset=utf-8")
            except (ValueError, OSError) as exc:
                self.send_body(422, str(exc)[:180], "text/plain; charset=utf-8")
            return
        if path != "/aggiorna":
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
