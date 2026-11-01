"""KDD Drive handoff: existing FolderSync outbound, FolderSync inbound.
No remote API, Kraken order, automatic approval, or background synchronization.
"""
from __future__ import annotations
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from scripts import kdd_bridge_g2 as bridge

EXCHANGE_ROOT = Path("/storage/emulated/0/KDD_TEST_SAMSUNG")
INCOMING_NAME = "proposta_portafoglio.json"
EXPORT_NAME = re.compile(r"kdd_handoff_[0-9a-f]{64}\.json\Z")


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


def prepare_export():
    original = bridge.prepare()
    outgoing = bridge.private_directory(bridge.OUTBOX, create=True)
    name = bridge.digest(original) + ".json"
    status = bridge.exclusive_json(outgoing, name, original)
    if status not in ("INSERITO", "GIA_PRESENTE"):
        raise bridge.BridgeError("Fotografia originale non confermata")
    bridge.verify_local_origin(original)
    return export_bundle(original)


def find_origin(proposal):
    snapshot = proposal.get("snapshot_id") if isinstance(proposal, dict) else None
    if not isinstance(snapshot, str) or not bridge.HEX.fullmatch(snapshot):
        raise bridge.BridgeError("Identita della fotografia non valida")
    outgoing = bridge.private_directory(bridge.OUTBOX)
    matches = []
    for path in outgoing.iterdir():
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


def receive(raw):
    """The browser file picker gives JSON bytes; save only after validation."""
    proposal, _ = validate_raw(raw)
    folder = bridge.private_directory(bridge.INBOX, create=True)
    final = folder / INCOMING_NAME
    stage = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".kdd-proposal-", suffix=".tmp",
                                         dir=folder, delete=False) as f:
            stage = Path(f.name)
            f.write(bridge.canonical(proposal) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(stage, 0o600)
        os.replace(stage, final)  # replaces ONLY a previously unapproved inbox copy
        stage = None
        bridge._sync_dir(folder)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return bridge.digest(proposal)


def receive_synced():
    """Read FolderSync's inbound local file; never claim remote sync succeeded.

    Invalid files remain untouched for diagnosis. A validated proposal is
    copied into the existing private inbox, without granting consent.
    """
    source = EXCHANGE_ROOT / INCOMING_NAME
    if not EXCHANGE_ROOT.is_dir() or EXCHANGE_ROOT.is_symlink():
        return None
    if not source.exists() and not source.is_symlink():
        return None
    import stat
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > bridge.MAX_BYTES:
        raise bridge.BridgeError("Proposta FolderSync non regolare")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
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
    proposal, _ = validate_raw(raw)
    current = pending()
    if current is not None and bridge.digest(current[0]) == bridge.digest(proposal):
        return bridge.digest(proposal)
    if bridge.digest(proposal) in bridge.load_archive():
        return bridge.digest(proposal)
    return receive(raw)


def pending():
    try:
        folder = bridge.private_directory(bridge.INBOX)
        raw = bridge.read_regular(folder / INCOMING_NAME, expected_parent=folder)
    except bridge.BridgeError:
        return None
    return validate_raw(raw)


def confirm(sha):
    item = pending()
    if item is None:
        raise bridge.BridgeError("Nessuna proposta in attesa")
    proposal, bundle = item
    if not isinstance(sha, str) or bridge.digest(proposal) != sha:
        raise bridge.BridgeError("Versione diversa: rivedere la proposta")
    if any(row["versione_sha256"] == sha and row["stato"] in ("RIFIUTATA", "RINVIATA") for row in decision_history()):
        raise bridge.BridgeError("Versione gia rifiutata o rinviata: occorre nuova proposta")
    return bridge.approved_import(proposal, bundle, sha, "APPROVO_VERSIONE")


def latest_export():
    if EXCHANGE_ROOT.is_symlink() or not EXCHANGE_ROOT.is_dir():
        return "Cartella di FolderSync non accessibile."
    files = [p for p in EXCHANGE_ROOT.iterdir()
             if EXPORT_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    if not files:
        return "Nessun dossier pronto per FolderSync."
    return "Ultimo dossier pronto: " + max(files, key=lambda p: p.stat().st_mtime).name


DECISION_EVENTS = "decision_events"
DECISION_STATES = {"RIFIUTATA", "RINVIATA", "ESECUZIONE_DICHIARATA", "RIESAME", "RISULTATO_VERIFICATO"}


def decision_history():
    """Read append-only human statements; not evidence of Kraken execution."""
    try:
        folder = bridge.private_directory(bridge.INBOX) / DECISION_EVENTS
        bridge._check_dir(folder)
    except bridge.BridgeError:
        if not (bridge.PRIVATE_ROOT / bridge.INBOX / DECISION_EVENTS).exists():
            return []
        raise
    rows = []
    for path in sorted(folder.iterdir()):
        if not re.fullmatch(r"[0-9a-f]{64}\\.json", path.name):
            raise bridge.BridgeError("Archivio decisionale non regolare")
        record = bridge.strict_json(bridge.read_regular(path, expected_parent=folder))
        if bridge.digest(record) != path.stem or set(record) != {"versione_sha256", "stato", "nota", "creato_utc"}:
            raise bridge.BridgeError("Archivio decisionale alterato")
        rows.append(record)
    return sorted(rows, key=lambda row: (row["creato_utc"], bridge.digest(row)))


def record_decision(raw):
    """Record explicit dated choices without modifying existing approved archive."""
    obj = bridge.strict_json(raw)
    if not isinstance(obj, dict) or set(obj) != {"sha256", "stato", "nota"}:
        raise bridge.BridgeError("Decisione non valida")
    sha, state, note = obj["sha256"], obj["stato"], obj["nota"]
    if not isinstance(sha, str) or not bridge.HEX.fullmatch(sha) or state not in DECISION_STATES:
        raise bridge.BridgeError("Versione o stato non valido")
    if not isinstance(note, str) or not note.strip() or len(note) > 1500:
        raise bridge.BridgeError("Motivazione o evidenza obbligatoria (massimo 1500 caratteri)")
    current = pending()
    approved = bridge.load_archive()
    if state in ("RIFIUTATA", "RINVIATA"):
        if current is None or bridge.digest(current[0]) != sha or sha in approved:
            raise bridge.BridgeError("Rifiuto/rinvio ammesso solo per proposta in attesa")
    elif sha not in approved:
        raise bridge.BridgeError("Dichiarazioni successive richiedono versione approvata")
    if state == "RISULTATO_VERIFICATO" and not any(
            row["versione_sha256"] == sha and row["stato"] == "RIESAME"
            for row in decision_history()):
        raise bridge.BridgeError("Risultato senza riesame precedente")
    entry = {"versione_sha256": sha, "stato": state, "nota": note.strip(),
             "creato_utc": bridge.checked_now(None).isoformat(timespec="seconds")}
    folder = bridge.ensure_dir(bridge.private_directory(bridge.INBOX, create=True) / DECISION_EVENTS)
    status = bridge.exclusive_json(folder, bridge.digest(entry) + ".json", entry)
    return status


def render_page(token):
    esc = lambda s: html.escape(str(s), quote=True)
    try:
        receive_synced()
        item = pending()
        error = None
    except bridge.BridgeError as exc:
        item, error = None, str(exc)
    if error:
        preview = "<p class='warn'>STOP: " + esc(error) + "</p>"
    elif item is None:
        preview = "<p>Nessuna proposta importata da Drive.</p>"
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
    if item is not None and not error and (already_approved or declined):
        preview = preview.split("<button onclick=", 1)[0]
    try:
        events = decision_history()
        history = "".join("<p>" + esc(x["creato_utc"]) + " · " + esc(x["stato"]) + " · " + esc(x["versione_sha256"][:12]) + " · " + esc(x["nota"]) + "</p>" for x in events)
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
  if(r.ok) setTimeout(()=>location.reload(),1200);
 } catch(e) { status.textContent='KDD locale non raggiungibile.'; }
}
function kddDecision(sha){\n const stato=document.getElementById("kdd-decision-state").value;\n const nota=document.getElementById("kdd-decision-note").value;\n if(!nota.trim())return;\n kddSend("/gpt/decisione",JSON.stringify({sha256:sha,stato:stato,nota:nota}),"application/json");\n}\nasync function kddFile(){
 const f=document.getElementById('gpt-json').files[0];
 if(!f){document.getElementById('feedback').textContent='Scegli il JSON da Drive.';return;}
 if(f.size>8000000){document.getElementById('feedback').textContent='File troppo grande.';return;}
 await kddSend('/gpt/ricevi',await f.arrayBuffer(),'application/json');
}
</script>""".replace("__TOKEN__", json.dumps(token))
    decision_form = ""
    if item is not None and not error:
        sha = bridge.digest(item[0])
        states = (("ESECUZIONE_DICHIARATA", "RIESAME", "RISULTATO_VERIFICATO")
                  if sha in bridge.load_archive() else ("RIFIUTATA", "RINVIATA"))
        if states and not (sha not in bridge.load_archive() and any(
                x["versione_sha256"] == sha and x["stato"] in ("RIFIUTATA", "RINVIATA")
                for x in decision_history())):
            decision_form = ("<h3>Registra scelta o evento dell'autore</h3>"
                "<select id='kdd-decision-state'>" +
                "".join("<option value='" + x + "'>" + x + "</option>" for x in states) +
                "</select><input id='kdd-decision-note' maxlength='1500' placeholder='Motivo, prova o riscontro' required>"
                "<button onclick='kddDecision(" + json.dumps(sha) + ")'>Registra evento datato</button>"
                "<p>Dichiarazione manuale non significa ordine verificato. Risultato verificato richiede riesame e prova esplicita.</p>")
    return ("""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KDD · GPT e Drive</title><style>
body{max-width:900px;margin:auto;padding:18px;background:#0b1120;color:#e5edf9;
font:16px/1.5 system-ui}article,section{background:#15223a;padding:15px;margin:12px 0;
border-radius:10px}button,input{font:inherit;padding:10px;margin:6px}button{cursor:pointer}
.warn{color:#fbbf24}a{color:#7dd3fc}details{margin:10px 0}
</style></head><body><p><a href="/">Torna al KDD</a></p>
<h1>Proposte GPT su Drive</h1>
<section><h2>1 · Prepara dossier per GPT</h2><p>Il KDD prepara il documento,
lo conserva come origine e lo copia nella cartella KDD_TEST_SAMSUNG utilizzata da FolderSync.
FolderSync deve sincronizzare questa cartella verso Drive (configurazione Android dopo GO).</p><p>""" +
        esc(latest_export()) +
        """</p><button onclick='kddSend("/gpt/prepara","","text/plain")'>
Prepara per Drive</button></section>
<section><h2>2 · Apri la proposta da Drive</h2><p>Dopo aver discusso con GPT,
FolderSync deve scaricare proposta_portafoglio.json nella cartella KDD_TEST_SAMSUNG del telefono. Il KDD la legge automaticamente quando apri questa pagina.
Aprirlo NON lo approva.</p>
<input id="gpt-json" type="file" accept=".json,application/json">
<button onclick="kddFile()">Apri proposta</button>
<p id="feedback" role="status"></p></section>
<section><h2>3 · Esamina e decidi</h2>""" + preview +
        decision_form + "</section><section><h2>4 · Archivio KDD</h2>" +
        archive + "</section>" + script + "</body></html>")


def handle(action, raw):
    if action == "prepara":
        if raw:
            raise bridge.BridgeError("Preparazione: dati inattesi")
        return "Dossier pronto per FolderSync: " + prepare_export()
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
