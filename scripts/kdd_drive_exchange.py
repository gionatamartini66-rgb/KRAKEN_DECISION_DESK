"""KDD Drive handoff: existing FolderSync outbound, FolderSync inbound.
No remote API, Kraken order, automatic approval, or background synchronization.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from scripts import kdd_bridge_g2 as bridge

EXCHANGE_ROOT = Path("/storage/emulated/0/KDD_TEST_SAMSUNG")
INCOMING_NAME = "proposta_portafoglio.json"
EXPORT_NAME = re.compile(r"kdd_handoff_[0-9a-f]{64}\.json\Z")
_DECISION_LOCK = threading.RLock()  # coordinates threads; flock coordinates processes


@contextlib.contextmanager
def _decision_writer():
    """One read/decide/commit gate shared by HTTP, CLI and FolderSync workers.

    Lock order: process-local RLock -> inbox flock -> (if needed) bridge
    approvals flock. Reuse the private, owner-only bridge lock primitive.
    Every writer of the current proposal or its decision must use this gate.
    """
    with _DECISION_LOCK:
        inbox = bridge.private_directory(bridge.INBOX, create=True)
        with bridge._archive_write_lock(inbox):
            yield


def export_bundle(bundle):
    """Only write the finished KDD-origin envelope to the existing sync source."""
    root = EXCHANGE_ROOT
    if root.is_symlink() or not root.is_dir():
        raise bridge.BridgeError("Cartella Kraken condivisa non disponibile")
    name = "kdd_handoff_" + bridge.digest(bundle) + ".json"
    final = root / name
    raw = bridge.canonical(bundle) + b"\n"
    if final.is_symlink():
        raise bridge.BridgeError("Percorso condiviso non regolare")
    if final.exists():
        if final.is_file() and final.read_bytes() == raw:
            return name
        raise bridge.BridgeError("Esportazione gia presente ma differente")
    stage = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".kdd-handoff-", suffix=".tmp",
                                         dir=root, delete=False) as f:
            stage = Path(f.name)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if final.exists() or final.is_symlink():
            raise bridge.BridgeError("Collisione prima della pubblicazione")
        os.rename(stage, final)
        stage = None
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return name


def _prepare_private_origin():
    """One canonical producer/validator for either direct chat or legacy Drive."""
    original = bridge.prepare()
    outgoing = bridge.private_directory(bridge.OUTBOX, create=True)
    name = bridge.digest(original) + ".json"
    status = bridge.exclusive_json(outgoing, name, original)
    if status not in ("INSERITO", "GIA_PRESENTE"):
        raise bridge.BridgeError("Fotografia originale non confermata")
    bridge.verify_local_origin(original)
    return original, outgoing / name


def prepare_chat():
    """KDD -> chat: owner-only retained source, NEVER shared to FolderSync."""
    original, path = _prepare_private_origin()
    return path, bridge.digest(original), original["packet_sha256"]


def prepare_export():
    original, _ = _prepare_private_origin()
    return export_bundle(original)


def find_origin(proposal):
    snapshot = proposal.get("snapshot_id") if isinstance(proposal, dict) else None
    if not isinstance(snapshot, str) or not bridge.HEX.fullmatch(snapshot):
        raise bridge.BridgeError("Identita della fotografia non valida")
    outgoing = bridge.private_directory(bridge.OUTBOX)
    matches = []
    for path in outgoing.iterdir():
        if path.name.startswith(".kdd-event-") and path.name.endswith(".tmp"):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            continue
        bundle = bridge.strict_json(bridge.read_regular(path, expected_parent=outgoing))
        if bundle.get("packet_sha256") == snapshot:
            bridge.verify_local_origin(bundle)
            matches.append(bundle)
    if len(matches) != 1:
        raise bridge.BridgeError("Fotografia KDD originaria assente o ambigua")
    return matches[0]


def validate_raw(raw):
    proposal = bridge.strict_json(raw)
    bundle = find_origin(proposal)
    bridge.validate_proposal(proposal, bundle)
    return proposal, bundle



def _approved_head(approved):
    """Use the bridge's approved version chain, never just a syntactically valid SHA."""
    if not approved:
        return None
    heads = set(approved) - {
        entry["proposta"].get("sostituisce_sha256") for entry in approved.values()
    }
    if len(heads) != 1:
        raise bridge.BridgeError("Successione approvazioni ambigua: STOP")
    return next(iter(heads))


def receive(raw):
    """Validate and import a new version without losing a still-pending choice."""
    with _decision_writer():
        return _receive_locked(raw)


def _receive_locked(raw):
    proposal, _ = validate_raw(raw)
    folder = bridge.private_directory(bridge.INBOX, create=True)
    final = folder / INCOMING_NAME
    sha = bridge.digest(proposal)
    approved = bridge.load_archive()
    events = decision_history()
    if sha in approved or any(e["versione_sha256"] == sha for e in events):
        raise bridge.BridgeError("Versione già deliberata: nessuna riattivazione")

    if final.exists() or final.is_symlink():
        existing = pending()
        if existing is not None:
            old = bridge.digest(existing[0])
        else:
            # Expired proposals remain identifiable from their private JSON.
            # Never treat an unreadable existing file as an empty inbox.
            old = bridge.digest(bridge.strict_json(
                bridge.read_regular(final, expected_parent=folder)))
        if old == sha:
            return sha
        if not (old in approved or any(
                e["versione_sha256"] == old and e["stato"] in ("RIFIUTATA", "RINVIATA")
                for e in events)):
            raise bridge.BridgeError("Proposta in attesa diversa: STOP, nessuna sovrascrittura")

    # A rejected/deferred draft is not an APPROVED predecessor. Only the
    # approved chain can be referenced here, since confirm() uses that bridge.
    if proposal["sostituisce_sha256"] != _approved_head(approved):
        raise bridge.BridgeError("Revisione non collegata all'ultima versione approvata")

    stage = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".kdd-proposal-", suffix=".tmp",
                                         dir=folder, delete=False) as f:
            stage = Path(f.name)
            f.write(bridge.canonical(proposal) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(stage, 0o600)
        os.replace(stage, final)
        stage = None
        bridge._sync_dir(folder)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return sha


def receive_synced():
    """Read the local FolderSync file. It may remain or return after decision."""
    source = EXCHANGE_ROOT / INCOMING_NAME
    # Only the external/shared-storage read is translated to a recoverable
    # FolderSync STOP. Errors in the private commit must never be hidden here.
    try:
        if not EXCHANGE_ROOT.is_dir() or EXCHANGE_ROOT.is_symlink():
            return None
        if not source.exists() and not source.is_symlink():
            return None
        import stat
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > bridge.MAX_BYTES:
            raise bridge.BridgeError("Proposta FolderSync non regolare")
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise bridge.BridgeError("Proposta FolderSync sostituita")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(bridge.MAX_BYTES + 1)
            if len(raw) > bridge.MAX_BYTES:
                raise bridge.BridgeError("Proposta FolderSync troppo grande")
        finally:
            os.close(fd)
    except OSError as exc:
        raise bridge.BridgeError("FolderSync: errore di lettura filesystem; STOP") from exc
    # A known, already decided version may be stale when FolderSync copies it
    # back. Recognize its exact content digest before freshness validation.
    proposal = bridge.strict_json(raw)
    sha = bridge.digest(proposal)
    with _decision_writer():
        approved = bridge.load_archive()
        events = decision_history()
        if sha in approved or any(e["versione_sha256"] == sha for e in events):
            return sha  # previous A must not replace current B
        current = pending()
        if current is not None and bridge.digest(current[0]) == sha:
            return sha
        return _receive_locked(raw)

_PRIVATE_STOP = "STOP PERSISTENZA PRIVATA: proposta non leggibile o non verificabile"


def _missing_private_inbox():
    """Identify only genuinely absent, otherwise securely verified, directory chains.

    The bridge's reader translates ENOENT and EIO to the same BridgeError.
    Check each *existing* ancestor using its own descriptor-based verifier;
    absence is legitimate only at a proven missing component. Broken,
    inaccessible, replaced or symlinked components must raise STOP.
    """
    root = bridge.PRIVATE_ROOT
    chain = (Path.home() / ".local", Path.home() / ".local" / "state",
             root.parent, root, root / bridge.INBOX)
    for path in chain:
        try:
            os.lstat(path)
        except FileNotFoundError:
            return True
        # Any other OSError, including EACCES and EIO, stays a STOP.
        bridge._check_dir(path, owner_only=path in
                          (root.parent, root, root / bridge.INBOX))
    return False


def pending():
    """None means VERIFIED ABSENCE, never an unreadable private proposal."""
    try:
        try:
            folder = bridge.private_directory(bridge.INBOX)
        except bridge.BridgeError:
            if _missing_private_inbox():
                return None
            raise

        path = folder / INCOMING_NAME
        verified_folder = bridge._check_dir(folder)
        # lstat confirms absence without following symlinks. A file that
        # disappears after lstat still produces STOP in read_regular().
        try:
            os.lstat(path)
        except FileNotFoundError:
            # ENOENT may instead mean the *parent* disappeared or changed.
            # Only an unchanged verified private directory permits ABSENT.
            if bridge._check_dir(folder) != verified_folder:
                raise bridge.BridgeError("Inbox privata cambiata durante la lettura")
            return None
        raw = bridge.read_regular(path, expected_parent=folder)
        return validate_raw(raw)
    except (bridge.BridgeError, OSError) as exc:
        raise bridge.BridgeError(_PRIVATE_STOP) from exc



def confirm(sha):
    with _decision_writer():
        item = pending()
        if item is None:
            raise bridge.BridgeError("Nessuna proposta in attesa")
        proposal, bundle = item
        if not isinstance(sha, str) or bridge.digest(proposal) != sha:
            raise bridge.BridgeError("Versione diversa: rivedere la proposta")
        if any(row["versione_sha256"] == sha and row["stato"] in ("RIFIUTATA", "RINVIATA")
               for row in decision_history()):
            raise bridge.BridgeError("Versione gia rifiutata o rinviata: occorre nuova proposta")
        return bridge.approved_import(proposal, bundle, sha, "APPROVO_VERSIONE")

def latest_export():
    try:
        if EXCHANGE_ROOT.is_symlink() or not EXCHANGE_ROOT.is_dir():
            return "Cartella di FolderSync non accessibile."
        files = [p for p in EXCHANGE_ROOT.iterdir()
                 if EXPORT_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
        if not files:
            return "Nessun dossier pronto per FolderSync."
        return "Ultimo dossier pronto: " + max(files, key=lambda p: p.stat().st_mtime).name
    except OSError:
        # Optional legacy status must not take the private proposal view down.
        return "STOP FolderSync: archivio condiviso non leggibile."


DECISION_EVENTS = "decision_events"
# Historical RISULTATO_VERIFICATO is only a past author's assertion. It is
# readable but must never be offered as a new independently verified result.
DECISION_STATES = {"RIFIUTATA", "RINVIATA", "ESECUZIONE_DICHIARATA", "RIESAME",
                   "RISCONTRO_DICHIARATO", "RISULTATO_VERIFICATO"}
DECISION_INPUT_STATES = DECISION_STATES - {"RISULTATO_VERIFICATO"}


def event_label(state):
    if state == "RISULTATO_VERIFICATO":
        return "RISCONTRO STORICO DICHIARATO (verifica su dati non attestata)"
    if state == "RISCONTRO_DICHIARATO":
        return "RISCONTRO DICHIARATO DALL'AUTORE (non verificato su dati)"
    return state


def _event_time(row):
    return bridge.instant(row["creato_utc"])


def _event_second(row):
    return _event_time(row).replace(microsecond=0)


def uncertain_event_seconds(rows):
    """Legacy whole-second timestamps give no order within their second."""
    groups = {}
    for row in rows:
        groups.setdefault(_event_second(row), []).append(row)
    return {second for second, group in groups.items()
            if len(group) > 1 and (
                any("." not in x["creato_utc"][19:] for x in group)
                or len({_event_time(x) for x in group}) != len(group))}


def latest_events(rows):
    """Return latest definite event, or the unordered latest-second group."""
    if not rows:
        return [], False
    ordered = sorted(rows, key=_event_time)
    latest = ordered[-1]
    second = _event_second(latest)
    if second in uncertain_event_seconds(ordered):
        return [x for x in ordered if _event_second(x) == second], True
    last_time = _event_time(latest)
    ties = [x for x in ordered if _event_time(x) == last_time]
    return ties, len(ties) > 1



def decision_history():
    """Read dated human events; an interrupted .tmp is not a committed event."""
    try:
        folder = bridge.private_directory(bridge.INBOX) / DECISION_EVENTS
        bridge._check_dir(folder)
    except bridge.BridgeError:
        if not (bridge.PRIVATE_ROOT / bridge.INBOX / DECISION_EVENTS).exists():
            return []
        raise
    rows = []
    basic = {"versione_sha256", "stato", "nota", "creato_utc"}
    for path in sorted(folder.iterdir()):
        if re.fullmatch(r"\.kdd-event-[A-Za-z0-9_-]+\.tmp", path.name):
            if path.is_symlink() or not path.is_file():
                raise bridge.BridgeError("Residuo decisionale non regolare")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            raise bridge.BridgeError("Archivio decisionale non regolare")
        record = bridge.strict_json(bridge.read_regular(path, expected_parent=folder))
        keys = set(record)
        if (bridge.digest(record) != path.stem
                or keys not in (basic, basic | {"proposta"})
                or record.get("stato") not in DECISION_STATES):
            raise bridge.BridgeError("Archivio decisionale alterato")
        if "proposta" in record:
            proposal = record["proposta"]
            if (record["stato"] not in ("RIFIUTATA", "RINVIATA")
                    or not isinstance(proposal, dict)
                    or bridge.digest(proposal) != record["versione_sha256"]):
                raise bridge.BridgeError("Collegamento proposta/evento alterato")
        rows.append(record)
    # Timestamps only: a SHA digest is not evidence of temporal order.
    # Whole-second historical ties are labelled as unordered in the UI.
    return sorted(rows, key=_event_time)


def record_decision(raw):
    """Persist one dated human statement, distinct from an actual Kraken trade."""
    with _decision_writer():
        obj = bridge.strict_json(raw)
        if not isinstance(obj, dict) or set(obj) != {"sha256", "stato", "nota"}:
            raise bridge.BridgeError("Decisione non valida")
        sha, state, note = obj["sha256"], obj["stato"], obj["nota"]
        if not isinstance(sha, str) or not bridge.HEX.fullmatch(sha) or state not in DECISION_INPUT_STATES:
            raise bridge.BridgeError("Versione o stato non valido")
        if not isinstance(note, str) or not note.strip() or len(note) > 1500:
            raise bridge.BridgeError("Motivazione o evidenza obbligatoria (massimo 1500 caratteri)")
        current = pending()
        approved = bridge.load_archive()
        events = decision_history()
        if state in ("RIFIUTATA", "RINVIATA"):
            if current is None or bridge.digest(current[0]) != sha or sha in approved:
                raise bridge.BridgeError("Rifiuto/rinvio ammesso solo per proposta in attesa")
            if any(row["versione_sha256"] == sha and row["stato"] in ("RIFIUTATA", "RINVIATA")
                   for row in events):
                raise bridge.BridgeError("Proposta già rifiutata o rinviata")
        elif sha not in approved:
            raise bridge.BridgeError("Dichiarazioni successive richiedono versione approvata")
        if state == "RISCONTRO_DICHIARATO" and not any(
                row["versione_sha256"] == sha and row["stato"] == "RIESAME"
                for row in events):
            raise bridge.BridgeError("Riscontro dichiarato senza riesame precedente")
        entry = {"versione_sha256": sha, "stato": state, "nota": note.strip(),
                 "creato_utc": bridge.checked_now(None).isoformat(timespec="microseconds")}
        if state in ("RIFIUTATA", "RINVIATA"):
            # Preserve the actual version/asset/snapshot context when B replaces A;
            # older four-field events remain readable without invented associations.
            entry["proposta"] = current[0]
        folder = bridge.ensure_dir(bridge.private_directory(bridge.INBOX, create=True) / DECISION_EVENTS)
        filename = bridge.digest(entry) + ".json"
        target = folder / filename
        if target.exists() or target.is_symlink():
            raise bridge.BridgeError("Evento gia registrato")
        stage = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".kdd-event-", suffix=".tmp",
                                             dir=folder, delete=False) as f:
                stage = Path(f.name)
                f.write(bridge.canonical(entry) + b"\n")
                f.flush()
                os.fsync(f.fileno())
            os.chmod(stage, 0o600)
            # Same-dir rename of a complete staged file works on Python Termux.
            # In-process lock + prior existence check prevent KDD HTTP races.
            os.rename(stage, target)
            stage = None
            bridge._sync_dir(folder)
            return "INSERITO"
        finally:
            if stage is not None:
                stage.unlink(missing_ok=True)

def render_page(token):
    esc = lambda s: html.escape(str(s), quote=True)
    sync_error = None
    try:
        receive_synced()
    except bridge.BridgeError as exc:
        # A private-read STOP can propagate through receive_synced() while
        # validating an otherwise readable shared input. It is NOT evidence
        # of FolderSync failure. pending() below reports it independently.
        if not str(exc).startswith(_PRIVATE_STOP):
            sync_error = str(exc)
    try:
        item = pending()
        error = None
    except bridge.BridgeError as exc:
        item, error = None, str(exc)
    if error:
        preview = "<p class='warn'>STOP: " + esc(error) + "</p>"
    elif item is None:
        preview = "<p>Nessuna proposta ricevuta dalla chat o da Drive.</p>"
    else:
        proposal, bundle = item
        state = bridge.read_context(bundle)
        sha = bridge.digest(proposal)
        already_approved = sha in bridge.load_archive()
        decisions = [x for x in decision_history() if x["versione_sha256"] == sha]
        declined = any(x["stato"] in ("RIFIUTATA", "RINVIATA") for x in decisions)
        rows = "".join(
            "<article><b>" + esc(r["token"]) + " · " + esc(r["azione"]) + "</b><p>" +
            esc(r["tesi"]) + "</p><details><summary>Rischi, alternative, costi, evidenze e riesame</summary>" +
            "".join("<p><b>" + label + ":</b> " + esc(r[key]) + "</p>"
                    for key, label in (("rischi", "Rischi"), ("alternativa", "Alternativa"),
                                       ("invalidazione", "Invalidazione"), ("costi", "Costi"),
                                       ("evidenze", "Evidenze"), ("riesame", "Riesame"))) +
            "</details></article>" for r in proposal["posizioni"])
        preview = ("<p><b>" + ("VERSIONE APPROVATA · STORICO" if already_approved else ("RIFIUTATA / RINVIATA" if declined else "NON APPROVATA")) + "</b> · SHA256 " + esc(sha) +
                   "</p><p>Fotografia " + esc(proposal["snapshot_utc"]) +
                   " · mercato " + esc(state["mercato"]["stato"]) +
                   " · saldo " + esc(state["saldo"]["stato"]) + "</p>" +
                   "<p>Scenario: " + esc(proposal["scenario"]) +
                   "</p><p>Alternativa: " + esc(proposal["scenario_alternativo"]) +
                   "</p><p>Rischi comuni: " + esc(proposal["rischi_comuni"]) +
                   "</p><p>Liquidità: " + esc(proposal["liquidita"]) +
                   "</p><p>Riesame: " + esc(proposal["revisione"]) + "</p>" + rows +
                   "<p>La conferma archivia una proposta, NON esegue operazioni finanziarie.</p>" +
                   "<button onclick='kddSend(\"/gpt/conferma\",JSON.stringify({sha256:" +
                   json.dumps(sha) +
                   "}),\"application/json\")'>Confermo questa versione nel KDD</button>")
    if sync_error:
        preview = ("<p class='warn'>STOP FolderSync legacy: "
                   + esc(sync_error) + "</p>" + preview)
    if item is not None and not error and (already_approved or declined):
        preview = preview.split("<button onclick=", 1)[0]
    try:
        events = decision_history()
        approvals = bridge.load_archive()
        ambiguous_seconds = uncertain_event_seconds(events)
        def event_line(x):
            source = x.get("proposta") or approvals.get(x["versione_sha256"], {}).get("proposta")
            attribution = ""
            if isinstance(source, dict):
                tokens = ", ".join(str(p["token"]) for p in source.get("posizioni", []) if isinstance(p, dict) and "token" in p)
                attribution = " · fotografia " + esc(source.get("snapshot_utc", "?")) + " · asset compresi nella proposta: " + esc(tokens)
            else:
                attribution = " · dettaglio asset non ricostruibile dal record storico"
            order_note = (" · ordine nel secondo non documentato"
                          if _event_second(x) in ambiguous_seconds else "")
            return ("<p>" + esc(x["creato_utc"]) + " · " + esc(event_label(x["stato"])) +
                    " · " + esc(x["versione_sha256"][:12]) + attribution +
                    order_note + " · " + esc(x["nota"]) + "</p>")
        history = "".join(event_line(x) for x in events)
        archive = bridge.approved_html() + "<h3>Decisioni e riesami datati</h3>" + (history or "<p>Nessun evento registrato.</p>")
    except Exception:
        archive = "<p>Archivio non verificabile: nessuna approvazione attestata.</p>"
    script = """<script>
const KDD_TOKEN=__TOKEN__;
async function kddSend(path,body,kind){
 const status=document.getElementById('feedback');status.textContent='Operazione in corso...';
 try {
  const r=await fetch(path,{method:'POST',headers:{'X-KDD-Token':KDD_TOKEN,
   'Content-Type':kind},body:body});
  status.textContent=await r.text();
  if(r.ok && path!=="/gpt/prepara-chat") setTimeout(()=>location.reload(),1200);
 } catch(e) { status.textContent='KDD locale non raggiungibile.'; }
}
function kddDecision(sha){
 const stato=document.getElementById("kdd-decision-state").value;
 const nota=document.getElementById("kdd-decision-note").value;
 if(!nota.trim())return;
 kddSend("/gpt/decisione",JSON.stringify({sha256:sha,stato:stato,nota:nota}),"application/json");
}
async function kddFile(){
 const f=document.getElementById('gpt-json').files[0];
 if(!f){document.getElementById('feedback').textContent='Scegli il JSON da Drive.';return;}
 if(f.size>8000000){document.getElementById('feedback').textContent='File troppo grande.';return;}
 await kddSend('/gpt/ricevi',await f.arrayBuffer(),'application/json');
}
</script>""".replace("__TOKEN__", json.dumps(token))
    decision_form = ""
    if item is not None and not error:
        sha = bridge.digest(item[0])
        states = (("ESECUZIONE_DICHIARATA", "RIESAME", "RISCONTRO_DICHIARATO")
                  if sha in bridge.load_archive() else ("RIFIUTATA", "RINVIATA"))
        if states and not (sha not in bridge.load_archive() and any(
                x["versione_sha256"] == sha and x["stato"] in ("RIFIUTATA", "RINVIATA")
                for x in decision_history())):
            decision_form = ("<h3>Registra scelta o evento dell'autore</h3>"
                "<select id='kdd-decision-state'>" +
                "".join("<option value='" + x + "'>" + esc(event_label(x)) + "</option>" for x in states) +
                "</select><input id='kdd-decision-note' maxlength='1500' placeholder='Motivo, prova o riscontro' required>"
                "<button onclick='kddDecision(" + json.dumps(sha) + ")'>Registra evento datato</button>"
                "<p>Il riscontro è una dichiarazione dell'autore dopo il riesame, non una verifica autonoma di prezzi, ordini o risultati.</p>")
    return ("""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KDD · GPT e archivio</title><style>
body{max-width:900px;margin:auto;padding:18px;background:#0b1120;color:#e5edf9;
font:16px/1.5 system-ui}article,section{background:#15223a;padding:15px;margin:12px 0;
border-radius:10px}button,input{font:inherit;padding:10px;margin:6px}button{cursor:pointer}
.warn{color:#fbbf24}a{color:#7dd3fc}details{margin:10px 0}
</style></head><body><p><a href="/">Torna al KDD</a></p>
<h1>Proposte GPT · Drive e FolderSync</h1>
<section><h2>1 · Prepara la fotografia KDD per Drive</h2><p>Il KDD conserva
l'origine privata verificabile ed esporta una copia nella cartella FolderSync.
Il trasporto previsto è KDD ↔ FolderSync ↔ Google Drive ↔ ChatGPT;
la disponibilità della sincronizzazione non è attestata da questo pulsante.</p><p>""" +
        esc(latest_export()) +
        """</p><button onclick='kddSend("/gpt/prepara","","text/plain")'>
Prepara per Drive / FolderSync</button>
<details><summary>Diagnostica locale (non trasporto operativo)</summary><p>
La preparazione privata senza Drive è destinata a sviluppo e controprove.
Desktop Commander non è un requisito di esercizio del KDD.</p>
<button onclick='kddSend("/gpt/prepara-chat","","text/plain")'>
Prepara fotografia privata di prova</button></details></section>
<section><h2>2 · Ricezione della proposta da Drive</h2><p>FolderSync
deposita proposta_portafoglio.json nella cartella KDD_TEST_SAMSUNG;
il KDD controlla origine, integrità e versione prima di presentarla.
La ricezione NON approva, NON invia ordini e NON esegue operazioni.</p>
<details><summary>Apri la proposta da Drive (legacy)</summary><p>La sincronizzazione
deve essere configurata e verificata separatamente. Se il file non è leggibile
il KDD segnala STOP e conserva visibile la proposta privata già valida.</p></details>
<details><summary>Recupero manuale straordinario</summary>
<input id="gpt-json" type="file" accept=".json,application/json">
<button onclick="kddFile()">Importa da file locale</button></details>
<p id="feedback" role="status"></p></section>
<section><h2>3 · Esamina e decidi</h2>""" + preview +
        decision_form + "</section><section><h2>4 · Archivio KDD</h2>" +
        archive + "</section>" + script + "</body></html>")


def handle(action, raw):
    if action == "prepara":
        if raw:
            raise bridge.BridgeError("Preparazione: dati inattesi")
        return "Dossier pronto per FolderSync: " + prepare_export()
    if action == "prepara-chat":
        if raw:
            raise bridge.BridgeError("Preparazione chat: dati inattesi")
        path, origin_sha, snapshot_sha = prepare_chat()
        return ("Fotografia KDD privata per chat; nessun invio automatico. "
                "Percorso: " + str(path) + " | origine: " + origin_sha
                + " | snapshot: " + snapshot_sha)
    if action == "ricevi":
        return "Proposta valida, NON approvata. Versione: " + receive(raw)
    if action == "decisione":
        return "Evento decisionale conservato: " + record_decision(raw)
    if action == "conferma":
        if len(raw) > 4096:
            raise bridge.BridgeError("Conferma troppo lunga")
        obj = bridge.strict_json(raw)
        if set(obj) != {"sha256"}:
            raise bridge.BridgeError("Conferma non valida")
        return "Decisione conservata nel KDD: " + confirm(obj["sha256"])["stato"]
    raise bridge.BridgeError("Azione non autorizzata")


def receive_chat(file_sha256, proposal_sha256, publication_consent):
    """Direct ChatGPT/Termux handoff through the EXISTING KDD receiver.

    The chat transports exact bytes to the app-private incoming directory
    through an explicitly authorised remote session, never through FolderSync.
    A file/JSON digest pair is a consistency check, NOT chat authentication.
    This imports a NON-APPROVED proposal; it does not call confirm().
    """
    if (not isinstance(file_sha256, str) or not bridge.HEX.fullmatch(file_sha256)
            or not isinstance(proposal_sha256, str)
            or not bridge.HEX.fullmatch(proposal_sha256)):
        raise bridge.BridgeError("Chat: impronte SHA256 non valide")
    if publication_consent != "PUBBLICA_VERSIONE_" + proposal_sha256:
        raise bridge.BridgeError("Chat: consenso esplicito alla pubblicazione assente")
    folder = bridge.private_directory(bridge.INBOX)
    source = folder / (".chat-" + file_sha256 + ".json")
    raw = bridge.read_regular(source, expected_parent=folder)
    if hashlib.sha256(raw).hexdigest() != file_sha256:
        raise bridge.BridgeError("Chat: digest dei byte non corrispondente")
    proposal = bridge.strict_json(raw)
    if bridge.digest(proposal) != proposal_sha256:
        raise bridge.BridgeError("Chat: versione JSON non corrispondente")
    # Single existing validator, replay/succession guard and private writer.
    return receive(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ingresso diretto chat -> KDD, senza FolderSync né approvazione")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepara-chat")
    incoming = sub.add_parser("ricevi-chat")
    incoming.add_argument("--file-sha256", required=True)
    incoming.add_argument("--proposta-sha256", required=True)
    incoming.add_argument("--consenso-pubblicazione", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepara-chat":
            path, origin_sha, snapshot_sha = prepare_chat()
            print("KDD -> CHAT: FOTOGRAFIA PRIVATA PRONTA | file:", path)
            print("ORIGINE_SHA256:", origin_sha, "| SNAPSHOT_SHA256:", snapshot_sha)
            print("TRASPORTO_CHAT: NON ATTESTATO | nessun invio automatico")
            return 0
        sha = receive_chat(args.file_sha256, args.proposta_sha256,
                           args.consenso_pubblicazione)
        print("CHAT -> KDD: PUBBLICATA NON APPROVATA | versione:", sha)
        return 0
    except (bridge.BridgeError, OSError) as exc:
        # Never echo proposal, timestamps, prices, balances or filesystem paths.
        print("STOP CHAT -> KDD:", str(exc) if isinstance(exc, bridge.BridgeError)
              else type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
