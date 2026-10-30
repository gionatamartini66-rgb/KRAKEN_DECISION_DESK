#!/usr/bin/env python3
"""KDD G2: private-only bridge and explicit human-authorised portfolio return.

No Android/shared-storage writer, Drive, FolderSync, Kraken call, trade, or GPT API.
Digest comparisons prove local byte consistency, NOT remote origin authentication.
"""
from __future__ import annotations
import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat

from scripts import kdd_wallet_packet_g0 as wallet
import piano_gpt

UTC = dt.timezone.utc
SCHEMA_BUNDLE = "kdd_private_handoff_v001"
SCHEMA_PROPOSAL = "kdd_portfolio_proposal_v001"
PRIVATE_ROOT = Path.home() / ".local" / "state" / "kraken-decision-desk" / "bridge"
OUTBOX = "outgoing"
INBOX = "incoming"
ARCHIVE = "approvals"
MAX_BYTES = 8_000_000
HEX = re.compile(r"[0-9a-f]{64}\Z")
CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}\Z")
ALLOWED = frozenset(("MANTENERE", "INCREMENTARE", "ALLEGGERIRE", "USCIRE", "RUOTARE", "RINVIARE"))
FRAMES = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}


class BridgeError(ValueError):
    """Fixed, nonsensitive rejection reasons."""


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BridgeError("JSON non canonico") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def instant(value):
    try:
        return wallet.when(value, "ponte")
    except (wallet.PacketError, TypeError, AttributeError) as exc:
        raise BridgeError("Timestamp non verificabile") from exc


def checked_now(now):
    now = now or dt.datetime.now(UTC)
    if not isinstance(now, dt.datetime) or not now.tzinfo or now.utcoffset() is None:
        raise BridgeError("Orologio senza fuso")
    return now.astimezone(UTC)


def numeric(value):
    if value is None:
        return None
    if type(value) not in (float, int, str):
        raise BridgeError("Valore numerico non valido")
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("nonfinite")
        return result
    except (InvalidOperation, ValueError):
        raise BridgeError("Valore numerico non valido") from None


def strict_json(raw):
    if not 2 <= len(raw) <= MAX_BYTES:
        raise BridgeError("Dimensione documento non valida")
    def unique(pairs):
        obj = {}
        for key, val in pairs:
            if key in obj:
                raise BridgeError("Chiave JSON duplicata")
            obj[key] = val
        return obj
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(BridgeError("Numero JSON non standard")))
    except (UnicodeError, ValueError) as exc:
        raise BridgeError("Documento JSON non leggibile") from exc
    if not isinstance(parsed, dict):
        raise BridgeError("Documento non oggetto")
    return parsed


def ensure_dir(path):
    """App-private only. Does not grant safety against a hostile same-UID process."""
    path = Path(path)
    if path.is_symlink():
        raise BridgeError("Directory symlink")
    if path.exists():
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise BridgeError("Permessi directory non privati")
    else:
        path.mkdir(mode=0o700, parents=False)
    return path


def private_directory(name, *, create=False):
    root = PRIVATE_ROOT
    if root.is_symlink():
        raise BridgeError("Root privata symlink")
    parent = root.parent
    if create:
        # Avoid touching arbitrary shared paths. HOME/.local/state belongs to app.
        for path in (Path.home() / ".local", Path.home() / ".local" / "state", parent, root):
            if path.is_symlink():
                raise BridgeError("Percorso privato symlink")
            if not path.exists():
                path.mkdir(mode=0o700)
            mode = path.stat().st_mode
            if not path.is_dir() or (mode & 0o022):
                raise BridgeError("Directory privata non protetta")
            # Shared read permission on pre-existing ~/.local or ~/.local/state
            # is normal. The actual KDD state and bridge must be owner-only.
            if path in (parent, root) and mode & 0o077:
                raise BridgeError("Directory KDD non privata")
        return ensure_dir(root / name)
    if not root.is_dir() or root.is_symlink():
        raise BridgeError("Root privata assente")
    child = root / name
    if not child.is_dir() or child.is_symlink() or child.stat().st_mode & 0o077:
        raise BridgeError("Directory privata assente o non protetta")
    return child


def read_regular(path, *, expected_parent=None):
    path = Path(path)
    if expected_parent is not None and path.parent != expected_parent:
        raise BridgeError("Percorso fuori dal perimetro privato")
    if path.is_symlink():
        raise BridgeError("Input symlink")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_size < 2:
            raise BridgeError("Input non regolare")
        # O_NOFOLLOW rejects last-component replacement with a symlink.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as src:
            data = src.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise BridgeError("Input fuori misura")
        return data
    except OSError as exc:
        raise BridgeError("Input non leggibile") from exc


def exclusive_json(directory, filename, obj):
    """Immutable, exclusive, app-private file. No overwrite or shared storage."""
    if not filename.endswith(".json") or not (HEX.fullmatch(filename[:-5]) or CODE.fullmatch(filename[:-5])):
        raise BridgeError("Nome documento non valido")
    dest = directory / filename
    raw = canonical(obj) + b"\n"
    if len(raw) > MAX_BYTES:
        raise BridgeError("Documento troppo grande")
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if read_regular(dest, expected_parent=directory) == raw:
            return "GIA_PRESENTE"
        raise BridgeError("Collisione archivio, STOP") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return "INSERITO"


def prepare(root, *, now=None):
    """Uses the original four-file D1/4TF consumer; no duplicate valuation engine."""
    moment = checked_now(now)
    pkt = wallet.build(Path(root), now=moment)
    result = {"schema": SCHEMA_BUNDLE, "packet": pkt,
              "packet_sha256": digest(pkt), "preparato_utc": moment.isoformat(timespec="seconds"),
              "provenienza": "KDD_LOCALE_DICHIARATA_NON_AUTENTICATA",
              "trasporto": "MANUALE_NON_ESEGUITO"}
    read_context(result, now=moment)
    return result


def read_context(bundle, *, now=None, expected_sha256=None):
    """GPT read-time contract: recalculate age/status and coverage, never authorise action."""
    moment = checked_now(now)
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA_BUNDLE:
        raise BridgeError("Schema trasporto sconosciuto")
    pkt = bundle.get("packet")
    if not isinstance(pkt, dict) or pkt.get("schema") != wallet.SCHEMA:
        raise BridgeError("Schema pacchetto sconosciuto")
    if not HEX.fullmatch(str(bundle.get("packet_sha256", ""))) or digest(pkt) != bundle["packet_sha256"]:
        raise BridgeError("Integrita locale pacchetto discordante")
    if expected_sha256 is not None and digest(bundle) != expected_sha256:
        raise BridgeError("Impronta esterna discordante")
    prepared, generated = instant(bundle.get("preparato_utc")), instant(pkt.get("generato_utc"))
    snap = instant(pkt.get("rilevazione_kdd_utc"))
    if abs((prepared-generated).total_seconds()) > 2 or snap > prepared + dt.timedelta(seconds=2):
        raise BridgeError("Fotografie temporali incompatibili")
    if prepared > moment + dt.timedelta(minutes=2):
        raise BridgeError("Orologio futuro")
    section = pkt.get("patrimonio")
    if not isinstance(section, dict) or not isinstance(section.get("posizioni"), list):
        raise BridgeError("Patrimonio non strutturato")
    rows = section["posizioni"]
    if pkt.get("nessun_ordine") is not True:
        raise BridgeError("Pacchetto non di sola analisi")
    if len(rows) != section.get("n_posizioni") or not rows:
        raise BridgeError("Cardinalita portafoglio incongruente")
    have_prices = []
    canon_tokens = []
    complete = 0
    observations = []
    sum_eur = Decimal(0)
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get("indice")) is not int or row["indice"] != i:
            raise BridgeError("Identita o indice posizione incongruente")
        price, val, qty = (numeric(row.get(field)) for field in ("prezzo_eur", "valore_eur", "quantita_spot"))
        pnl = numeric(row.get("pl_indicativo_eur"))
        if (price is not None and price <= 0) or (val is not None and val < 0) or (qty is not None and qty < 0):
            raise BridgeError("Prezzo o quantita non valida")
        if pnl is not None and val is None:
            raise BridgeError("P/L senza valutazione")
        token = row.get("token")
        if row.get("stato_identita") == "VALIDA":
            if not isinstance(token, str) or not wallet.SYMBOL.fullmatch(token):
                raise BridgeError("Identita valida ma token non verificabile")
            identity = wallet.canonical_wallet_alias(token)
            if identity in canon_tokens:
                raise BridgeError("Collisione asset nel pacchetto")
            canon_tokens.append(identity)
        if (price is None) != (val is None):
            raise BridgeError("Prezzo o controvalore assente")
        if val is not None:
            provenance = row.get("fonte_prezzo_eur")
            token = row.get("token")
            if not isinstance(provenance, dict) or provenance.get("token") != token:
                raise BridgeError("Provenienza quotazione EUR non verificabile")
            if provenance.get("rilevazione_utc") != pkt["rilevazione_kdd_utc"]:
                raise BridgeError("Fotografia quotazione EUR incoerente")
            if provenance.get("valuta") != "EUR" or not isinstance(provenance.get("pair"), str):
                raise BridgeError("Valuta quotazione non EUR")
            parts = provenance["pair"].split("/")
            if len(parts) != 2 or parts[1] != "EUR" or wallet.canonical_wallet_alias(parts[0]) != wallet.canonical_wallet_alias(token):
                raise BridgeError("Base quotazione incompatibile")
            if not isinstance(provenance.get("pair_key"), str) or not wallet.KRAKEN_PAIR_KEY.fullmatch(provenance["pair_key"]):
                raise BridgeError("Identificativo mercato non verificabile")
            if qty is None or float(qty) * float(price) != float(val):
                raise BridgeError("Controvalore incoerente")
            sum_eur += val
        have_prices.append(val is not None and qty is not None)
        tf = row.get("analisi_4tf")
        states = {}
        if tf and tf.get("stato") == "COMPLETO":
            original_frames = tf.get("timeframe")
            if (not isinstance(original_frames, dict)
                    or any(not isinstance(original_frames.get(k), dict) for k in FRAMES)
                    or any(original_frames[k].get("stato") not in ("AGGIORNATO", "SCADUTO") for k in FRAMES)):
                raise BridgeError("Quattro timeframe dichiarati ma incompleti")
        if isinstance(tf, dict):
            frames = tf.get("timeframe")
            if isinstance(frames, dict):
                for label, seconds in FRAMES.items():
                    f = frames.get(label)
                    if not isinstance(f, dict):
                        states[label] = "NON_DISPONIBILE"
                        continue
                    state = f.get("stato")
                    if state not in ("AGGIORNATO", "SCADUTO", "NON_DISPONIBILE",
                                     "NON_VALIDO", "RINVIATO_BUDGET", "STORICO_INSUFFICIENTE"):
                        raise BridgeError("Stato timeframe non verificabile")
                    if state == "AGGIORNATO":
                        closed = instant(f.get("chiusura_utc"))
                        sequence = f.get("serie_ohlcv_chiuse")
                        if (not isinstance(sequence, list) or not 50 <= len(sequence) <= 200
                                or not isinstance(sequence[-1], dict)
                                or type(sequence[-1].get("time")) is not int
                                or closed.timestamp() != sequence[-1]["time"] + seconds
                                or closed > moment + dt.timedelta(minutes=2)):
                            raise BridgeError("Serie 4TF o ultima chiusura incoerente")
                        last = int((moment.timestamp()-120)//seconds)*seconds
                        state = "AGGIORNATO" if closed.timestamp() >= last else "SCADUTO"
                    states[label] = state
        if len(states) != 4:
            states = {k: states.get(k, "NON_DISPONIBILE") for k in FRAMES}
        all_tf = all(value == "AGGIORNATO" for value in states.values())
        complete += bool(all_tf)
        observations.append({"indice": i, "token": row.get("token"),
                             "stato_identita": row.get("stato_identita"),
                             "timeframe_ricalcolati": states,
                             "quattro_tf_aggiornati": all_tf, "prezzo_eur_attestato_localmente": val is not None})
    declared = numeric(section.get("totale_stimato_eur_senza_cash"))
    if declared is None and sum_eur != 0:
        raise BridgeError("Totale mancante con valori numerici")
    if declared is not None and abs(declared - sum_eur) > Decimal("0.01"):
        raise BridgeError("Totale patrimoniale incoerente")
    partial = any(not x for x in have_prices)
    if partial and (section.get("stato_totale") == "COMPLETO" or not section.get("totale_parziale")):
        raise BridgeError("Totale incompleto dichiarato completo")
    saldo = pkt.get("saldo")
    if not isinstance(saldo, dict):
        raise BridgeError("Stato saldo assente")
    bal_ts = saldo.get("ultima_acquisizione_utc")
    bal_status = (wallet.source_status(instant(bal_ts), moment) if bal_ts else
                  {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None})
    if (not isinstance(saldo.get("stato"), dict) or
            saldo["stato"].get("stato") in ("ORIGINE_SCONOSCIUTA", "OROLOGIO_INCOERENTE")):
        bal_status = {"stato": "ORIGINE_SCONOSCIUTA", "eta_minuti": None}
    market_status = wallet.source_status(snap, moment)
    return {"schema": "kdd_gpt_read_context_v001", "snapshot_id": digest(pkt),
            "snapshot_utc": pkt["rilevazione_kdd_utc"],
            "letto_utc": moment.isoformat(timespec="seconds"),
            "mercato": market_status, "saldo": bal_status,
            "n_posizioni": len(rows), "quattro_tf_aggiornati": complete,
            "copertura": observations,
            "totale_parziale": bool(section.get("totale_parziale")) or partial,
            "origine": "COERENZA_INTERNA_SOLTANTO" if expected_sha256 is None else "DIGEST_ESTERNAMENTE_CONFRONTATO_NON_AUTENTICATO",
            "lacune_da_verificare": ["fondamentali", "on-chain", "notizie", "costi", "autenticita_upstream"],
            "nessun_ordine": True, "istruzioni_nei_file": "DATI_NON_AUTORIZZAZIONI"}


def read_bundle(path, *, now=None, expected_sha256=None):
    raw = read_regular(path)
    if (not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise BridgeError("Digest dei byte ricevuti non confermato")
    # A matching digest must have been obtained through an independent channel.
    # Without that external trust, this remains local byte integrity only.
    return read_context(strict_json(raw), now=now)


def text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1600 or any(
            ord(c) < 32 and c not in "\t\n" for c in value):
        raise BridgeError("Testo proposta non valido")
    return value


def validate_proposal(proposal, bundle, *, now=None):
    context = read_context(bundle, now=now)
    if not isinstance(proposal, dict) or proposal.get("schema") != SCHEMA_PROPOSAL:
        raise BridgeError("Schema proposta sconosciuto")
    if any(key in proposal for key in ("approvato", "eseguito", "ordine", "trading", "api_key")):
        raise BridgeError("Il documento non puo approvare o eseguire ordini")
    if proposal.get("snapshot_id") != context["snapshot_id"]:
        raise BridgeError("Fotografia proposta non attribuibile")
    if proposal.get("snapshot_utc") != context["snapshot_utc"]:
        raise BridgeError("Fotografia temporale proposta incoerente")
    created = instant(proposal.get("creato_utc"))
    snap = instant(context["snapshot_utc"])
    if created < snap or created > checked_now(now) + dt.timedelta(minutes=2):
        raise BridgeError("Data proposta incoerente")
    if not CODE.fullmatch(str(proposal.get("proposta_id", ""))):
        raise BridgeError("Identificativo proposta non valido")
    rows = proposal.get("posizioni")
    originals = bundle["packet"]["patrimonio"]["posizioni"]
    if not isinstance(rows, list) or len(rows) != len(originals):
        raise BridgeError("Proposta non copre tutto il patrimonio")
    for i, (row, original) in enumerate(zip(rows, originals)):
        if not isinstance(row, dict) or row.get("indice") != i or row.get("token") != original.get("token"):
            raise BridgeError("Identita proposta e portafoglio discordanti")
        if row.get("azione") not in ALLOWED or (original.get("stato_identita") != "VALIDA" and row.get("azione") != "RINVIARE"):
            raise BridgeError("Azione posizione non autorizzata")
        for field in ("tesi", "rischi", "alternativa", "invalidazione", "riesame", "costi", "evidenze"):
            text(row.get(field))
    for key in ("scenario", "scenario_alternativo", "rischi_comuni", "liquidita", "revisione"):
        text(proposal.get(key))
    refs = proposal.get("fonti_esterne")
    if not isinstance(refs, list) or len(refs) > 30:
        raise BridgeError("Fonti non strutturate")
    for s in refs:
        if (not isinstance(s, dict) or not isinstance(s.get("url"), str)
                or not piano_gpt.safe_url(s["url"])):
            raise BridgeError("Fonte esterna non valida")
        text(s.get("nome"))
    parent = proposal.get("sostituisce_sha256")
    if parent is not None and (not isinstance(parent, str) or not HEX.fullmatch(parent)):
        raise BridgeError("Riferimento revisione non valido")
    return proposal


def load_archive(*, create=False):
    try:
        folder = private_directory(ARCHIVE, create=create)
    except BridgeError:
        if not create and not (PRIVATE_ROOT / ARCHIVE).exists():
            return {}
        raise
    out = {}
    for file in sorted(folder.iterdir()):
        if file.is_symlink() or not file.is_file() or not re.fullmatch(r"[0-9a-f]{64}\.json", file.name):
            raise BridgeError("Archivio non regolare")
        entry = strict_json(read_regular(file, expected_parent=folder))
        proposal = entry.get("proposta")
        if not isinstance(proposal, dict) or digest(proposal) != file.stem:
            raise BridgeError("Archivio alterato")
        if entry.get("versione_sha256") != file.stem or entry.get("consenso") != "CONFERMATO_DA_COMANDO_UTENTE":
            raise BridgeError("Approvazione archiviata incoerente")
        out[file.stem] = entry
    return out


def approved_import(proposal, bundle, approved_sha, consent, *, now=None):
    """Human enters exact digest into an explicit local command. Not GPT self-approval."""
    validate_proposal(proposal, bundle, now=now)
    version = digest(proposal)
    if not isinstance(approved_sha, str) or approved_sha != version or consent != "APPROVO_VERSIONE":
        raise BridgeError("Consenso umano esplicito assente o versione diversa")
    existing = load_archive()
    if version in existing:
        if existing[version]["proposta"] != proposal:
            raise BridgeError("Versione gia archiviata ma differente")
        return {"stato": "GIA_PRESENTE", "versione_sha256": version}
    parent = proposal.get("sostituisce_sha256")
    # Sequential chain, preserve every earlier version; no destructive overwrite.
    heads = set(existing) - {e["proposta"].get("sostituisce_sha256") for e in existing.values()}
    if existing and (len(heads) != 1 or parent not in heads):
        raise BridgeError("Revisione non collegata alla versione corrente")
    if not existing and parent is not None:
        raise BridgeError("Versione precedente inesistente")
    entry = {"versione_sha256": version, "consenso": "CONFERMATO_DA_COMANDO_UTENTE",
             "approvato_utc": checked_now(now).isoformat(timespec="seconds"),
             "snapshot_id": proposal["snapshot_id"], "proposta": proposal,
             "nessun_ordine": True, "esecuzione": "NON_ATTESTATA"}
    status = exclusive_json(private_directory(ARCHIVE, create=True), version+".json", entry)
    return {"stato": status, "versione_sha256": version}


def approved_html():
    """Read-only escaped view to reuse existing KDD dashboard without new POST routes."""
    esc = lambda v: html.escape(str(v), quote=True)
    try:
        records = load_archive()
    except BridgeError:
        return "<section><h2>Proposte patrimoniali GPT</h2><p>Archivio non verificabile: STOP.</p></section>"
    if not records:
        return "<section id='kdd-gpt-patrimonio'><h2>Proposte patrimoniali GPT</h2><p>Nessuna versione approvata importata.</p></section>"
    heads = set(records) - {e["proposta"].get("sostituisce_sha256") for e in records.values()}
    if len(heads) != 1:
        return "<section><h2>Proposte patrimoniali GPT</h2><p>Revisione ambigua: STOP.</p></section>"
    latest = records[next(iter(heads))]
    p = latest["proposta"]
    items = "".join(
        "<li><b>"+esc(r["token"])+" — "+esc(r["azione"])+
        "</b><p>"+esc(r["tesi"])+"</p><details><summary>Rischi, condizioni e riesame</summary>"+
        "<p>Rischi: "+esc(r["rischi"])+"</p><p>Alternativa: "+esc(r["alternativa"])+
        "</p><p>Invalidazione: "+esc(r["invalidazione"])+
        "</p><p>Costi: "+esc(r["costi"])+
        "</p><p>Evidenze: "+esc(r["evidenze"])+
        "</p><p>Riesame: "+esc(r["riesame"])+"</p></details></li>"
        for r in p["posizioni"])
    return ("<section id='kdd-gpt-patrimonio'><h2>Proposta patrimoniale GPT approvata</h2>"
            "<p>Versione "+esc(latest["versione_sha256"][:16])+" · snapshot "+esc(p["snapshot_utc"])+
            " · esecuzione NON ATTESTATA. Valutazione storica: riesaminare al nuovo mercato.</p>"
            "<p>Scenario: "+esc(p["scenario"])+"</p><p>Alternativa generale: "+
            esc(p["scenario_alternativo"])+"</p><p>Liquidità: "+esc(p["liquidita"])+
            "</p><p>Rischi comuni: "+esc(p["rischi_comuni"])+
            "</p><p>Riesame: "+esc(p["revisione"])+"</p>"
            "<ul>"+items+"</ul><p>Versioni conservate: "+str(len(records))+
            ". Nessun ordine finanziario deducibile dall'approvazione.</p></section>")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ponte KDD privato G2: nessuna sincronizzazione")
    sub = ap.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-dir", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("--file", type=Path, required=True)
    review.add_argument("--expected-sha256", required=True)
    sub.add_parser("preview-proposal", help="valida e mostra solo il digest della proposta privata")
    imp = sub.add_parser("import-approved")
    imp.add_argument("--approved-sha256", required=True)
    imp.add_argument("--consent", required=True)
    args = ap.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.source_dir)
            out = private_directory(OUTBOX, create=True)
            status = exclusive_json(out, digest(result)+".json", result)
            # Exact bytes as written, including the final LF; used as transport manifest.
            raw = canonical(result) + b"\n"
            print("PREPARATO SOLO PRIVATO:", status, "| sha256_file:", hashlib.sha256(raw).hexdigest())
        elif args.action == "review":
            # Review of a local copy only; expected digest must arrive on a separate trusted channel.
            result = read_bundle(args.file, expected_sha256=args.expected_sha256)
            print("LETTURA:", result["mercato"]["stato"], result["saldo"]["stato"],
                  "posizioni:", result["n_posizioni"], "4TF attuali:", result["quattro_tf_aggiornati"])
        else:
            inbox = private_directory(INBOX)
            raw = read_regular(inbox / "proposta_portafoglio.json", expected_parent=inbox)
            prop = strict_json(raw)
            envelope = strict_json(read_regular(inbox / "pacchetto_riferimento.json", expected_parent=inbox))
            validate_proposal(prop, envelope)
            if args.action == "preview-proposal":
                print("ANTEPRIMA NON APPROVATA | versione:", digest(prop),
                      "| posizioni:", len(prop["posizioni"]),
                      "| fotografia:", prop["snapshot_id"])
            else:
                result = approved_import(prop, envelope, args.approved_sha256, args.consent)
                print("APPROVAZIONE:", result["stato"], "sha256:", result["versione_sha256"])
        return 0
    except (BridgeError, wallet.PacketError) as exc:
        print("STOP G2:", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
