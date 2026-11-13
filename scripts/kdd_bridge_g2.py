#!/usr/bin/env python3
"""KDD G2: private-only bridge and explicit human-authorised portfolio return.

No Android/shared-storage writer, Drive, FolderSync, Kraken call, trade, or GPT API.
Digest comparisons prove local byte consistency, NOT remote origin authentication.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import tempfile
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import sys
import secrets

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
# In-memory origin is producer evidence within one process; CLI uses the private outbox.
_LOCAL_ORIGINS = set()
STAGING = re.compile(r"\.kdd-stage-[A-Za-z0-9_-]+\.tmp\Z")
PENDING = re.compile(r"\.pending-[0-9a-f]{64}\.json\Z")
PENDING_SCHEMA_R4 = "kdd_file_commit_v002"
PENDING_SCHEMA_R5 = "kdd_file_commit_v003"
PENDING_SCHEMA_ANDROID = "kdd_android_rename_commit_v001"
ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
RESOLVED = re.compile(r"\.(?:resolved|cancelled)-[0-9a-f]{64}(?:-[0-9a-f]{32})?\.json\Z")
SOURCE_FILES = tuple(wallet.SRC_MAX)
CANONICAL_KDD_SOURCE = wallet.DEFAULT_SOURCE
PROPOSAL_FIELDS = frozenset(("schema", "proposta_id", "snapshot_id", "snapshot_utc", "creato_utc", "posizioni", "scenario", "scenario_alternativo", "rischi_comuni", "liquidita", "revisione", "fonti_esterne", "sostituisce_sha256"))
POSITION_FIELDS = frozenset(("indice", "token", "azione", "tesi", "rischi", "alternativa", "invalidazione", "riesame", "costi", "evidenze"))
SOURCE_REF_FIELDS = frozenset(("nome", "url"))
APPROVAL_FIELDS = frozenset(("versione_sha256", "consenso", "approvato_utc",
                             "snapshot_id", "proposta", "nessun_ordine", "esecuzione"))
# Only Exchange installs this independent durability verifier at import.
# Without it, read-only approval HTML is deliberately STOP, not self-attesting.
_approval_view_reader = None


class BridgeError(ValueError):
    """Fixed, nonsensitive rejection reasons."""


class PublicationUncertain(OSError):
    """Final file may exist, but its directory entry is not yet durable."""
    state = "PUBBLICAZIONE_INCERTA"


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


def _check_dir(path, *, owner_only=True):
    """Check the opened directory descriptor, not merely a preceding stat."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            st = os.fstat(fd)
            if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
                    or (st.st_mode & (0o077 if owner_only else 0o022))):
                raise BridgeError("Directory privata non sicura")
            current = os.stat(path, follow_symlinks=False)
            if (st.st_ino, st.st_dev) != (current.st_ino, current.st_dev):
                raise BridgeError("Directory sostituita durante apertura")
            return st.st_dev, st.st_ino
        finally:
            os.close(fd)
    except OSError as exc:
        raise BridgeError("Directory non verificabile") from exc


def ensure_dir(path):
    """No symlink, even after an EEXIST due to concurrent creation."""
    path = Path(path)
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
    except OSError as exc:
        raise BridgeError("Creazione directory fallita") from exc
    _check_dir(path)
    return path


def private_directory(name, *, create=False):
    """Only named children under the existing owner-only Termux app state."""
    if name not in (OUTBOX, INBOX, ARCHIVE):
        raise BridgeError("Nome directory non autorizzato")
    root = PRIVATE_ROOT
    parent = root.parent
    if create:
        for path in (Path.home() / ".local", Path.home() / ".local" / "state", parent, root):
            try:
                path.mkdir(mode=0o700, exist_ok=True)
            except OSError as exc:
                raise BridgeError("Creazione percorso privato fallita") from exc
            _check_dir(path, owner_only=(path in (parent, root)))
        return ensure_dir(root / name)
    _check_dir(parent)
    _check_dir(root)
    child = root / name
    _check_dir(child)
    return child


def read_regular(path, *, expected_parent=None, expected_nlink=1):
    """Fail closed on the actual opened inode (owner, mode, link count, type)."""
    path = Path(path)
    if expected_parent is not None and path.parent != expected_parent:
        raise BridgeError("Percorso fuori dal perimetro privato")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            st = os.fstat(stream.fileno())
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_mode & 0o077 or st.st_nlink != expected_nlink
                    or not 2 <= st.st_size <= MAX_BYTES):
                raise BridgeError("Input non privato o non regolare")
            current = os.stat(path, follow_symlinks=False)
            if (current.st_ino, current.st_dev) != (st.st_ino, st.st_dev):
                raise BridgeError("Input sostituito durante apertura")
            raw = stream.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES or len(raw) != st.st_size:
                raise BridgeError("Input troncato o mutato")
            return raw
    except OSError as exc:
        raise BridgeError("Input non leggibile") from exc


def _sync_dir(directory):
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                 getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BridgeError("Directory di commit insicura")
        os.fsync(fd)
    finally:
        os.close(fd)


def _path_present(path):
    """lstat (no follow): a dangling symlink is present, NEVER 'no pending'."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BridgeError("Percorso transazione non verificabile") from exc
    return True


def _pending_file(directory, filename):
    """R4 uses the identical durable journal for approvals and private snapshots."""
    if directory.name not in (ARCHIVE, OUTBOX) or not HEX.fullmatch(filename[:-5]):
        return None
    return directory / (".pending-" + filename)


def _validate_transaction_document(directory, filename, raw):
    doc = strict_json(raw)
    if directory.name == ARCHIVE:
        validate_approval_record(doc, expected_sha=filename[:-5])
    elif directory.name == OUTBOX:
        if (not isinstance(doc, dict) or digest(doc) != filename[:-5]
                or doc.get("schema") != SCHEMA_BUNDLE):
            raise BridgeError("Fotografia outbox non verificabile")
        read_context(doc, now=instant(doc.get("preparato_utc")))
    return doc


def _verified_transaction_file(path, directory, marker, *, expected_raw=None):
    """Validate the *opened* regular file and its name against a durable journal."""
    raw = read_regular(path, expected_parent=directory)
    st = os.stat(path, follow_symlinks=False)
    if (st.st_dev != marker["device"] or st.st_ino != marker["inode"]
            or st.st_uid != marker["owner"]
            or stat.S_IMODE(st.st_mode) != marker["mode"]
            or hashlib.sha256(raw).hexdigest() != marker["sha256_bytes"]
            or expected_raw is not None and raw != expected_raw):
        raise BridgeError("Documento di transazione non corrispondente: STOP")
    return raw


def _finalize_pending(directory, filename, expected_raw=None, *, explicit=False, validator=None):
    """Android: explicit recovery of ONE verified journal. Legacy pending => STOP.

    No hardlinks, no completed-mark files. The pending name is the read gate:
    it is unlinked ONLY AFTER the final directory fsync has succeeded. Removing
    the pending name does not require another fsync for the document's safety:
    after power loss it may reappear and block reading, never promote a partial.
    """
    pending = _pending_file(directory, filename)
    if pending is None or not _path_present(pending):
        return "NESSUNA_PENDENZA"
    marker = strict_json(read_regular(pending, expected_parent=directory))
    if not isinstance(marker, dict) or marker.get("schema") != PENDING_SCHEMA_ANDROID:
        # R3-R5 were never deployed on Samsung. Never silently reinterpret
        # their hardlink-specific journals or erase evidence on a new backend.
        raise BridgeError("Journal storico o sconosciuto: STOP assistito")
    if set(marker) != {"schema", "filename", "stage", "attempt_id",
                       "sha256_bytes", "inode", "device", "owner", "mode"}:
        raise BridgeError("Journal non canonico: STOP")
    attempt = marker.get("attempt_id")
    stage_name = marker.get("stage")
    if (marker.get("filename") != filename
            or not isinstance(attempt, str) or not ATTEMPT.fullmatch(attempt)
            or not isinstance(stage_name, str) or not STAGING.fullmatch(stage_name)
            or not stage_name.startswith(".kdd-stage-" + attempt + "-")
            or not isinstance(marker.get("inode"), int)
            or not isinstance(marker.get("device"), int)
            or marker.get("owner") != os.getuid()
            or marker.get("mode") != 0o600
            or not isinstance(marker.get("sha256_bytes"), str)
            or not HEX.fullmatch(marker["sha256_bytes"])):
        raise BridgeError("Identita journal non verificabile: STOP")
    stage = directory / stage_name
    dest = directory / filename
    has_final, has_stage = _path_present(dest), _path_present(stage)
    if has_final and has_stage:
        raise BridgeError("Finale e staging concorrenti: STOP")
    if has_final:
        if not explicit:
            raise BridgeError("PUBBLICAZIONE_INCERTA: riconciliare")
        raw = _verified_transaction_file(dest, directory, marker, expected_raw=expected_raw)
        if validator is not None:
            validator(raw)
        # Mandatory final-name durability boundary: an error leaves pending
        # in place and the normal reader will NOT accept this document.
        _sync_dir(directory)
        pending.unlink()
        return "PUBBLICATO_CONFERMATO"
    if has_stage:
        if not explicit:
            raise BridgeError("NON_PUBBLICATO: riconciliazione richiesta")
        _verified_transaction_file(stage, directory, marker, expected_raw=expected_raw)
        # A verified pre-rename stage is NEVER promoted to a final document.
        # SIGKILL after stage unlink, before journal unlink => STOP assisted;
        # no evidence is silently erased or guessed in that ambiguous state.
        stage.unlink()
        _sync_dir(directory)
        pending.unlink()
        return "NON_PUBBLICATO"
    raise BridgeError("Transazione senza finale o staging: STOP assistito")


def _directory_write_lock(folder):
    """Exclusive flock for *all* private producers and recovery operations."""
    name = ".approval.lock" if folder.name == ARCHIVE else ".publish.lock"
    lock = folder / name
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise BridgeError("Lock privato non sicuro") from exc
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or st.st_nlink != 1 or st.st_mode & 0o077):
            raise BridgeError("Lock privato non regolare")
        return fd
    except BaseException:
        os.close(fd)
        raise


def reconcile_directory(name):
    """A separate, explicit CLI operation. Never trusts an unlogged stage."""
    if name not in (ARCHIVE, OUTBOX):
        raise BridgeError("Directory non riconciliabile")
    folder = private_directory(name)
    with _archive_write_lock(folder):
        pending = sorted(p for p in folder.iterdir() if PENDING.fullmatch(p.name))
        statuses = []
        for p in pending:
            statuses.append(_finalize_pending(
                folder, p.name[len(".pending-"):], explicit=True,
            validator=lambda raw, fn=p.name[len(".pending-"):]:
                _validate_transaction_document(folder, fn, raw)))
        return statuses


def reconcile_archive():
    return reconcile_directory(ARCHIVE)


def reconcile_outbox():
    return reconcile_directory(OUTBOX)


def exclusive_json(directory, filename, obj):
    """Public writer ALWAYS takes the directory lock; no bypass boolean."""
    directory = Path(directory)
    if directory not in (PRIVATE_ROOT / OUTBOX, PRIVATE_ROOT / ARCHIVE):
        raise BridgeError("Destinazione pubblicazione fuori dalle directory KDD")
    _check_dir(directory)
    with _archive_write_lock(directory):
        return _exclusive_json_locked(directory, filename, obj)


def _exclusive_json_locked(directory, filename, obj):
    """Internal-only path for holders of the matching private-directory flock.

    Cooperative writers are the explicit trust boundary. Never claims to
    resist a process that writes the final name without taking this lock.
    """
    directory = Path(directory)
    if directory not in (PRIVATE_ROOT / OUTBOX, PRIVATE_ROOT / ARCHIVE):
        raise BridgeError("Destinazione pubblicazione fuori dalle directory KDD")
    if (not filename.endswith(".json") or not HEX.fullmatch(filename[:-5])):
        raise BridgeError("Documento non identificato da SHA256")
    _check_dir(directory)
    dest = directory / filename
    raw = canonical(obj) + b"\n"
    if len(raw) > MAX_BYTES:
        raise BridgeError("Documento troppo grande")
    pending = _pending_file(directory, filename)
    if pending is not None and _path_present(pending):
        raise BridgeError("PUBBLICAZIONE_INCERTA: riconciliazione esplicita")
    if _path_present(dest):
        if read_regular(dest, expected_parent=directory) == raw:
            return "GIA_PRESENTE"
        raise BridgeError("Collisione finale: STOP")
    # Unknown orphan staging is an explicit operator STOP; do not delete by glob.
    if any(STAGING.fullmatch(p.name) for p in directory.iterdir()):
        raise BridgeError("Staging senza transazione: STOP assistito")
    attempt_id = secrets.token_hex(16)
    fd, stage_name = tempfile.mkstemp(
        prefix=".kdd-stage-" + attempt_id + "-", suffix=".tmp", dir=directory)
    stage = Path(stage_name)
    recorded = False
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        st = os.stat(stage, follow_symlinks=False)
        if pending is not None:
            marker = canonical({
                "schema": PENDING_SCHEMA_ANDROID, "filename": filename,
                "stage": stage.name, "attempt_id": attempt_id,
                "sha256_bytes": hashlib.sha256(raw).hexdigest(),
                "inode": st.st_ino, "device": st.st_dev,
                "owner": st.st_uid, "mode": stat.S_IMODE(st.st_mode),
            }) + b"\n"
            journal_fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(journal_fd, "wb") as out:
                out.write(marker)
                out.flush()
                os.fsync(out.fileno())
            _sync_dir(directory)
            recorded = True
        # Under the mandatory lock, no OTHER COOPERATIVE writer can create
        # this name. Plain rename CAN overwrite a noncooperative insertion.
        # This is deliberately not a no-replace guarantee against same-UID
        # noncooperative writers; the independent red team must test that limit.
        if _path_present(dest):
            raise BridgeError("Collisione durante pubblicazione: STOP")
        os.rename(stage, dest)
        _sync_dir(directory)         # REQUIRED before any success or pending release
        if pending is not None:
            # The journal's removal is a visibility gate. We DO NOT claim
            # its removal is power-loss durable: reappearance => safe STOP.
            pending.unlink()
        return "INSERITO"
    except (OSError, BridgeError) as exc:
        if recorded or _path_present(dest):
            # Post-rename errors are uncertain even when rename itself raised.
            # Never unlink a transaction stage or journal here.
            raise PublicationUncertain(
                "PUBBLICAZIONE_INCERTA: verifica esplicita obbligatoria") from exc
        # No durable journal, no possible confirmed commit in a compliant
        # execution. Cleanup only our exact stage; preserve original error.
        if _path_present(stage):
            try:
                stage.unlink()
            except OSError:
                pass
        raise


@contextlib.contextmanager
def _archive_write_lock(folder):
    fd = _directory_write_lock(folder)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _source_evidence(root, *, fixture=False):
    """Bracket wallet.build with exact dir+four-file inode and content evidence.

    Fixture injection is a Python test-only seam. The CLI does not expose it.
    Same-UID concurrent writers remain outside this local guarantee.
    """
    canonical_root = Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001"
    root = Path(root)
    if not fixture and (root != canonical_root or root.is_symlink()):
        raise BridgeError("Sorgente non canonica KDD")
    if root.is_symlink() or not root.is_dir():
        raise BridgeError("Directory sorgente non regolare")
    try:
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                               getattr(os, "O_NOFOLLOW", 0))
        try:
            dir_st = os.fstat(directory_fd)
            if not stat.S_ISDIR(dir_st.st_mode) or dir_st.st_uid != os.getuid():
                raise BridgeError("Sorgente di proprietario diverso")
            listed = os.stat(root, follow_symlinks=False)
            if (dir_st.st_dev, dir_st.st_ino) != (listed.st_dev, listed.st_ino):
                raise BridgeError("Directory sorgente sostituita")
            files = []
            for name in SOURCE_FILES:
                fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                             getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as stream:
                    st = os.fstat(stream.fileno())
                    on_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                            or st.st_nlink != 1 or not 2 <= st.st_size <= wallet.SRC_MAX[name]
                            or (st.st_dev, st.st_ino) != (on_path.st_dev, on_path.st_ino)):
                        raise BridgeError("Fonte KDD irregolare o sostituita")
                    contents = stream.read(wallet.SRC_MAX[name]+1)
                    if len(contents) != st.st_size:
                        raise BridgeError("Fonte KDD mutata durante lettura")
                    files.append((name, st.st_dev, st.st_ino, hashlib.sha256(contents).hexdigest()))
            return ((dir_st.st_dev, dir_st.st_ino), tuple(files))
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise BridgeError("Sorgente KDD non verificabile") from exc


def verify_local_origin(bundle):
    """The incoming pair cannot attest itself. An actual persisted outbox is mandatory."""
    if not isinstance(bundle, dict):
        raise BridgeError("Fotografia originale assente")
    origin_id = digest(bundle)
    try:
        outgoing = private_directory(OUTBOX)
        if _path_present(outgoing / (".pending-" + origin_id + ".json")):
            raise BridgeError("Fotografia originaria in recupero incerto")
        raw = read_regular(outgoing / (origin_id + ".json"), expected_parent=outgoing)
        original = strict_json(raw)
    except (BridgeError, OSError) as exc:
        raise BridgeError("Fotografia KDD originaria non persistita") from exc
    if original != bundle or digest(original) != origin_id or raw != canonical(original) + b"\n":
        raise BridgeError("Fotografia KDD originaria non corrispondente")
    return origin_id


def prepare(root=None, *, now=None, _fixture=False):
    """Origin contract: production always uses canonical KDD root; no auto-publish."""
    moment = checked_now(now)
    root = Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001" if root is None else Path(root)
    if _fixture is not True and root != (Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001"):
        raise BridgeError("Sorgente non canonica KDD")
    before = _source_evidence(root, fixture=_fixture)
    pkt = wallet.build(root, now=moment)
    after = _source_evidence(root, fixture=_fixture)
    if before != after:
        raise BridgeError("Fotografia KDD cambiata durante composizione")
    result = {"schema": SCHEMA_BUNDLE, "packet": pkt,
              "packet_sha256": digest(pkt), "preparato_utc": moment.isoformat(timespec="seconds"),
              "provenienza": "KDD_LOCALE_DICHIARATA_NON_AUTENTICATA",
              "trasporto": "MANUALE_NON_ESEGUITO"}
    read_context(result, now=moment)
    return result


def stato_book_150_alla_lettura(packet, now, *, mercato_stato=None, saldo_stato=None):
    """Ricalcola l'eta del book a OGNI lettura, non riusa la freschezza storica."""
    pp = packet.get("patrimonio") if isinstance(packet, dict) else None
    book = pp.get("book_pubblico_150") if isinstance(pp, dict) else None
    if not isinstance(book, dict) or book.get("stato") != "STIMA_BOOK_CON_FEE_IPOTETICA":
        return {"stato": "NON_ATTESTATO", "book_recenti": 0, "book_scaduti": 0}
    rows = book.get("righe")
    if not isinstance(rows, list):
        return {"stato": "NON_VERIFICABILE", "book_recenti": 0, "book_scaduti": 0}
    recent, stale = 0, 0
    for row in rows:
        if not isinstance(row, dict):
            return {"stato": "NON_VERIFICABILE", "book_recenti": 0, "book_scaduti": 0}
        if row.get("stato") != "BOOK_PUBBLICO_OSSERVATO":
            continue
        try:
            seen = instant(row.get("osservato_utc"))
            delta = (now-seen).total_seconds()
        except (BridgeError, TypeError, ValueError):
            return {"stato": "NON_VERIFICABILE", "book_recenti": 0, "book_scaduti": 0}
        # Even a 1-second future book is not an ordinarily recent observation.
        # Clock skew cannot be converted into freshness of an order book.
        if delta < 0:
            return {"stato": "OROLOGIO_INCOERENTE", "book_recenti": 0, "book_scaduti": 0}
        if delta <= 300:
            recent += 1
        else:
            stale += 1
    base_fresh = mercato_stato == "RECENTE" and saldo_stato == "RECENTE"
    return {"stato": ("DATI_BASE_NON_RECENTI" if recent and not base_fresh else
                       "SCADUTO" if stale else
                       "RECENTE_SOLO_FEE_IPOTETICA" if recent else "NESSUN_BOOK_USABILE"),
            "book_recenti": recent, "book_scaduti": stale,
            "limite": "Fee, negoziabilita e bid restano da confermare prima dell'ordine manuale."}


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
    # Optional, backwards-compatible identity on new packets only. It hashes
    # the *source wallet JSON*, not this packet, proposal or market timestamp.
    wallet_sha = section.get("fotografia_portafoglio_sha256")
    if wallet_sha is not None and (
            not isinstance(wallet_sha, str) or not HEX.fullmatch(wallet_sha)):
        raise BridgeError("Impronta patrimoniale originaria non valida")
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
        figure_read_states = {}
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
                    if f.get("figure_candlestick") is not None:
                        import kdd_candles
                        sequence = f.get("serie_ohlcv_chiuse")
                        if not isinstance(sequence, list) or len(sequence) < 50:
                            raise BridgeError("OHLCV figure assenti: "+label)
                        try:
                            original = kdd_candles.recognize({
                                "timeframe": label, "interval_seconds": seconds,
                                "candles": sequence, "pair": tf.get("coppia"),
                                "pair_key": tf.get("pair_key"),
                                "observed_utc": f["rilevazione_utc"],
                                "closed_at_utc": f["chiusura_utc"],
                                "source": f.get("fonte"),
                            }, now=instant(f["rilevazione_utc"]))
                        except (ValueError, KeyError, TypeError, OverflowError) as exc:
                            raise BridgeError("Figure OHLCV non verificabili: "+label) from exc
                        if original != f["figure_candlestick"]:
                            raise BridgeError("Figure OHLCV alterate: "+label)
                    if f.get("figure_candlestick") is not None:
                        figure_read_states[label] = {
                            "stato_alla_lettura": state,
                            "stato_alla_rilevazione": f["figure_candlestick"]["stato"],
                            "rilevazione_utc": f["figure_candlestick"]["rilevazione_utc"],
                            "storico": state != "AGGIORNATO"}
                    states[label] = state
        if len(states) != 4:
            states = {k: states.get(k, "NON_DISPONIBILE") for k in FRAMES}
        # Do not reuse the packet's historical four-frame verdict as current.
        import kdd_candles
        read_frames = {}
        for label in FRAMES:
            source_frame = (tf.get("timeframe") or {}).get(label, {}) if isinstance(tf, dict) else {}
            read_frames[label] = dict(source_frame or {}, stato=states[label])
        comparison_at_read = kdd_candles.compare_context(read_frames)
        all_tf = all(value == "AGGIORNATO" for value in states.values())
        complete += bool(all_tf)
        observations.append({"indice": i, "token": row.get("token"),
                             "stato_identita": row.get("stato_identita"),
                             "timeframe_ricalcolati": states,
                             "figure_candlestick_alla_lettura": figure_read_states,
                             "confronto_figure_4tf_alla_lettura": comparison_at_read,
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
    economic_read = None
    multifonte = pkt.get("evidenze_multifonte")
    if isinstance(multifonte, dict) and multifonte.get("economia") is not None:
        import kdd_economics
        try:
            economic_read = kdd_economics.at_read(
                multifonte["economia"], rows,
                pkt.get("opportunita_esterne_scanner") or [], moment)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise BridgeError("Evidenza economica non verificabile") from exc
    # Re-evaluate persisted Futures evidence at the actual GPT read, not only
    # when the packet was built. Transport digests do not attest semantics.
    import kdd_futures_flow
    derivatives = multifonte.get("derivati_btc") if isinstance(multifonte, dict) else None
    futures_at_read = kdd_futures_flow.at_read(
        derivatives.get("flusso_futures") if isinstance(derivatives, dict) else None,
        moment)
    # Same public evidence reinterpreted at actual GPT read; stale source
    # numbers are suppressed, all wallet/candidate identities remain present.
    import kdd_network_defi
    try:
        network_at_read = kdd_network_defi.at_read(
            multifonte.get("rete_defi") if isinstance(multifonte,dict) else None,
            rows, pkt.get("opportunita_esterne_scanner") or [], moment,
            economia=economic_read)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise BridgeError("Evidenze on-chain/DeFi non verificabili") from exc
    return {"schema": "kdd_gpt_read_context_v001", "snapshot_id": digest(pkt),
            "snapshot_utc": pkt["rilevazione_kdd_utc"],
            "letto_utc": moment.isoformat(timespec="seconds"),
            "mercato": market_status, "saldo": bal_status,
            "n_posizioni": len(rows), "quattro_tf_aggiornati": complete,
            "copertura": observations,
            "evidenze_economiche_alla_lettura": economic_read,
            "flusso_futures_alla_lettura": futures_at_read,
            "rete_defi_alla_lettura": network_at_read,
            "totale_parziale": bool(section.get("totale_parziale")) or partial,
            "book_150_alla_lettura": stato_book_150_alla_lettura(
                pkt, moment, mercato_stato=market_status["stato"],
                saldo_stato=bal_status["stato"]),
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
    context = read_context(strict_json(raw), now=now)
    context["integrita_trasporto"] = "SHA256_BYTE_ESATTI_CONFRONTATO"
    context["origine"] = "BYTE_INTEGRI_SECONDO_HASH_FORNITO_ORIGINE_NON_AUTENTICATA"
    return context


def text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1600 or any(
            ord(c) < 32 and c not in "\t\n" for c in value):
        raise BridgeError("Testo proposta non valido")
    return value


def validate_proposal(proposal, bundle, *, now=None):
    context = read_context(bundle, now=now)
    if not isinstance(proposal, dict) or proposal.get("schema") != SCHEMA_PROPOSAL:
        raise BridgeError("Schema proposta sconosciuto")
    if set(proposal) != PROPOSAL_FIELDS:
        raise BridgeError("Contratto proposta non chiuso")
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
        if not isinstance(row, dict) or set(row) != POSITION_FIELDS:
            raise BridgeError("Campi posizione sconosciuti")
        if row.get("indice") != i or row.get("token") != original.get("token"):
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
        if (not isinstance(s, dict) or set(s) != SOURCE_REF_FIELDS or not isinstance(s.get("url"), str)
                or not piano_gpt.safe_url(s["url"])):
            raise BridgeError("Fonte esterna non valida")
        text(s.get("nome"))
    parent = proposal.get("sostituisce_sha256")
    if parent is not None and (not isinstance(parent, str) or not HEX.fullmatch(parent)):
        raise BridgeError("Riferimento revisione non valido")
    return proposal


def validate_approval_record(entry, *, expected_sha=None):
    """One strict schema contract for archive, transaction and witnesses."""
    if not isinstance(entry, dict) or set(entry) != APPROVAL_FIELDS:
        raise BridgeError("Record integrale approvazione non canonico")
    proposal = entry["proposta"]
    if (not isinstance(proposal, dict)
            or type(entry["versione_sha256"]) is not str
            or not HEX.fullmatch(entry["versione_sha256"])
            or expected_sha is not None and entry["versione_sha256"] != expected_sha
            or digest(proposal) != entry["versione_sha256"]
            or entry["consenso"] != "CONFERMATO_DA_COMANDO_UTENTE"
            or type(entry["consenso"]) is not str
            or type(entry["snapshot_id"]) is not str
            or entry["snapshot_id"] != proposal.get("snapshot_id")
            or not HEX.fullmatch(entry["snapshot_id"])
            or type(entry["approvato_utc"]) is not str
            or entry["nessun_ordine"] is not True
            or type(entry["esecuzione"]) is not str
            or entry["esecuzione"] != "NON_ATTESTATA"):
        raise BridgeError("Record integrale approvazione incoerente")
    when = instant(entry["approvato_utc"])
    if (when.tzinfo is None or when.utcoffset() is None
            or when.utcoffset() != dt.timedelta(0)):
        raise BridgeError("Data approvazione senza UTC")
    if entry["approvato_utc"] != when.isoformat(timespec="seconds"):
        raise BridgeError("Data approvazione non canonica")
    return entry


def make_approval_record(proposal, *, now=None):
    """Freeze the complete approved document BEFORE its write-ahead witness."""
    version = digest(proposal)
    return validate_approval_record({
        "versione_sha256": version,
        "consenso": "CONFERMATO_DA_COMANDO_UTENTE",
        "approvato_utc": checked_now(now).isoformat(timespec="seconds"),
        "snapshot_id": proposal["snapshot_id"], "proposta": proposal,
        "nessun_ordine": True, "esecuzione": "NON_ATTESTATA",
    }, expected_sha=version)


def load_archive(*, create=False):
    try:
        folder = private_directory(ARCHIVE, create=create)
    except BridgeError:
        if not create and not (PRIVATE_ROOT / ARCHIVE).exists():
            return {}
        raise
    out = {}
    for file in sorted(folder.iterdir()):
        if file.name == ".approval.lock" or STAGING.fullmatch(file.name) or RESOLVED.fullmatch(file.name):
            if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077:
                raise BridgeError("Residuo archivio non sicuro")
            continue
        if PENDING.fullmatch(file.name):
            # A pending final is not a confirmed version. An unfinished stage
            # without final is invisible to read-only views; writers still STOP.
            if (folder / file.name[len(".pending-"):]).exists():
                raise BridgeError("PUBBLICAZIONE_INCERTA: archivio non confermato")
            read_regular(file, expected_parent=folder)
            continue
        if file.is_symlink() or not file.is_file() or not re.fullmatch(r"[0-9a-f]{64}\.json", file.name):
            raise BridgeError("Archivio non regolare")
        entry = strict_json(read_regular(file, expected_parent=folder))
        out[file.stem] = validate_approval_record(entry, expected_sha=file.stem)
    return out


def approved_import(proposal, bundle, approved_sha, consent, *, now=None,
                    prepared_record=None, before_commit=None):
    """Only a KDD-origin photograph may be bound to explicit human consent."""
    verify_local_origin(bundle)
    validate_proposal(proposal, bundle, now=now)
    version = digest(proposal)
    if not isinstance(approved_sha, str) or approved_sha != version or consent != "APPROVO_VERSIONE":
        raise BridgeError("Consenso umano esplicito assente o versione diversa")
    folder = private_directory(ARCHIVE, create=True)
    with _archive_write_lock(folder):
        if any(PENDING.fullmatch(p.name) for p in folder.iterdir()):
            raise BridgeError("PUBBLICAZIONE_INCERTA: riconciliazione obbligatoria")
        existing = load_archive()
        if version in existing:
            if existing[version]["proposta"] != proposal:
                raise BridgeError("Versione gia archiviata ma differente")
            return {"stato": "GIA_PRESENTE", "versione_sha256": version}
        parent = proposal.get("sostituisce_sha256")
        heads = set(existing) - {e["proposta"].get("sostituisce_sha256") for e in existing.values()}
        if existing and (len(heads) != 1 or parent not in heads):
            raise BridgeError("Revisione non collegata alla versione corrente")
        if not existing and parent is not None:
            raise BridgeError("Versione precedente inesistente")
        # Approval timestamp and every metadata byte were frozen earlier in
        # Exchange. Bridge MUST write that identical prepared record.
        entry = (make_approval_record(proposal, now=now) if prepared_record is None
                 else validate_approval_record(prepared_record, expected_sha=version))
        if entry["proposta"] != proposal:
            raise BridgeError("Record approvazione diverso dalla proposta autorizzata")
        # Called under the approval flock, after parent/consent validation and
        # immediately before a real archive publication. Crash after intent
        # but before commit => unresolved witness => STOP, not false success.
        if before_commit is not None:
            before_commit(entry)
        status = _exclusive_json_locked(folder, version+".json", entry)
        return {"stato": status, "versione_sha256": version}


def approved_html(*, verified_records=None):
    """Verified approval view; an unanchored legacy archive is STOP-only text.

    The old standalone bridge has no enrollment/witness and historically
    exposed the GPT prose for review. Preserve that *untrusted preview* for
    compatibility without presenting it as an attested human approval.
    Operational HTTP callers ALWAYS pass Exchange-verified records; a broken
    v002 enrollment is never promoted to a legacy preview.
    """
    esc = lambda value: html.escape(str(value), quote=True)
    unverified_legacy = False
    try:
        if verified_records is not None:
            records = verified_records
        elif _approval_view_reader is not None:
            try:
                records = _approval_view_reader()
            except Exception:
                # The presence of an enrollment (valid, old, or corrupted)
                # categorically forbids legacy downgrade. Symlink counts as
                # present, and an undecidable path is STOP via the catch.
                if _path_present(PRIVATE_ROOT / ".decision-enrollment-v001.json"):
                    raise
                records = load_archive()
                unverified_legacy = True
        else:
            # Only a standalone pre-Exchange legacy bridge can reach here.
            # The textual content is *not* a certified approval.
            if _path_present(PRIVATE_ROOT / ".decision-enrollment-v001.json"):
                raise BridgeError("Verifica continuità obbligatoria")
            records = load_archive()
            unverified_legacy = True
        if not isinstance(records, dict):
            raise BridgeError("Approvazioni non verificabili")
        for sha, record in records.items():
            validate_approval_record(record, expected_sha=sha)
    except Exception:
        return "<section id='kdd-gpt-patrimonio'><h2>Proposte patrimoniali GPT</h2><p>Archivio non verificabile: STOP.</p></section>"
    if not records:
        if unverified_legacy:
            return "<section id='kdd-gpt-patrimonio'><h2>Proposte patrimoniali GPT</h2><p>Archivio non verificabile: STOP. Nessuna approvazione attestata.</p></section>"
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
    heading = ("<h2>Anteprima GPT storica NON CERTIFICATA · STOP</h2>"
               if unverified_legacy else
               "<h2>Proposta patrimoniale GPT approvata</h2>")
    warning = ("<p role='status'>Archivio non verificabile: STOP. Il testo"
               " seguente è un'anteprima storica non attribuibile a consenso"
               " integro e non costituisce decisione approvata.</p>"
               if unverified_legacy else "")
    return ("<section id='kdd-gpt-patrimonio'>" + heading + warning +
            "<p>Versione "+esc(latest["versione_sha256"][:16])+" · snapshot "+esc(p["snapshot_utc"])+
            " · ESECUZIONE NON ATTESTATA. Testo generato da GPT, non verificato come fatto finanziario. Valutazione storica: riesaminare al nuovo mercato.</p>"
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
    review = sub.add_parser("review")
    review.add_argument("--file", type=Path, required=True)
    review.add_argument("--expected-sha256", required=True)
    sub.add_parser("preview-proposal", help="valida e mostra solo il digest della proposta privata")
    imp = sub.add_parser("import-approved")
    imp.add_argument("--approved-sha256", required=True)
    imp.add_argument("--consent", required=True)
    sub.add_parser("reconcile-archive", help="riconcilia sotto lock i commit privati incerti")
    sub.add_parser("reconcile-outbox", help="riconcilia fotografie KDD senza Drive")
    args = ap.parse_args(argv)
    try:
        if args.action == "reconcile-outbox":
            print("RECUPERO OUTBOX:", ",".join(reconcile_outbox()) or "NESSUNA_PENDENZA")
        elif args.action == "reconcile-archive":
            print("RECUPERO ARCHIVIO:", ",".join(reconcile_archive()) or "NESSUNA_PENDENZA")
        elif args.action == "prepare":
            result = prepare()
            out = private_directory(OUTBOX, create=True)
            with _archive_write_lock(out):
                if any(p.name.startswith(".pending-") for p in out.iterdir()):
                    raise BridgeError("PUBBLICAZIONE_INCERTA: riconciliare outbox")
                status = _exclusive_json_locked(out, digest(result)+".json", result)
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
            verify_local_origin(envelope)
            validate_proposal(prop, envelope)
            if args.action == "preview-proposal":
                print("ANTEPRIMA NON APPROVATA | versione:", digest(prop),
                      "| posizioni:", len(prop["posizioni"]),
                      "| fotografia:", prop["snapshot_id"])
            else:
                result = approved_import(prop, envelope, args.approved_sha256, args.consent)
                print("APPROVAZIONE:", result["stato"], "sha256:", result["versione_sha256"])
        return 0
    except (BridgeError, wallet.PacketError, OSError, PublicationUncertain) as exc:
        status = "PUBBLICAZIONE_INCERTA" if isinstance(exc, PublicationUncertain) else "NON_PUBBLICATO_O_NON_VERIFICATO"
        detail = str(exc) if isinstance(exc, (BridgeError, wallet.PacketError)) else type(exc).__name__
        print("STOP G2:", status, detail)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
