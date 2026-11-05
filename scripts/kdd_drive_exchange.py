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
import secrets
import stat
import tempfile
import threading
from scripts import kdd_bridge_g2 as bridge

EXCHANGE_ROOT = Path("/storage/emulated/0/KDD_TEST_SAMSUNG")
INCOMING_NAME = "proposta_portafoglio.json"
EXPORT_NAME = re.compile(r"kdd_handoff_[0-9a-f]{64}\.json\Z")
_DECISION_LOCK = threading.RLock()  # coordinates threads; flock coordinates processes


class ExchangeError(bridge.BridgeError):
    domain = "validation"


class FolderSyncError(ExchangeError):
    domain = "foldersync"


class PrivatePersistenceError(ExchangeError):
    domain = "private"


class ProposalValidationError(ExchangeError):
    domain = "validation"


class DecisionContinuityError(PrivatePersistenceError):
    """A missing/ambiguous chain is NOT an empty history."""
    domain = "private"


_ENROLLMENT = ".decision-enrollment-v001.json"
_WITNESSES = "decision_witnesses"
_WITNESS_SCHEMA = "kdd_decision_witness_v002"
_ENROLLMENT_SCHEMA = "kdd_decision_enrollment_v002"
_RESTORE_STOP = "STOP DECISIONI — RIPRISTINO NECESSARIO"


def _witness_dir():
    root = bridge.PRIVATE_ROOT
    bridge._check_dir(root)
    directory = root / _WITNESSES
    bridge._check_dir(directory)
    return directory


def _read_enrollment():
    """The enrollment anchors a proposal ID AND each full approval digest."""
    root = bridge.PRIVATE_ROOT
    bridge._check_dir(root)
    if any(re.fullmatch(r"\.decision-enrollment-.*\\.tmp", p.name)
           for p in root.iterdir()):
        raise bridge.BridgeError("Staging iscrizione non riconciliato")
    enrollment = bridge.strict_json(bridge.read_regular(
        root / _ENROLLMENT, expected_parent=root))
    if (set(enrollment) != {"schema", "nonce", "events", "approvals"}
            or enrollment["schema"] != _ENROLLMENT_SCHEMA
            or not isinstance(enrollment["nonce"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", enrollment["nonce"])
            or type(enrollment["events"]) is not list
            or enrollment["events"] != sorted(set(enrollment["events"]))
            or any(not isinstance(s, str) or not bridge.HEX.fullmatch(s)
                   for s in enrollment["events"])
            or type(enrollment["approvals"]) is not list):
        raise bridge.BridgeError("Iscrizione continuità non valida o legacy")
    approved = enrollment["approvals"]
    if (any(not isinstance(item, dict)
            or set(item) != {"versione_sha256", "record_sha256"}
            or any(not isinstance(item[k], str)
                   or not bridge.HEX.fullmatch(item[k])
                   for k in ("versione_sha256", "record_sha256"))
            for item in approved)
            or approved != sorted(approved, key=lambda x: x["versione_sha256"])
            or len({item["versione_sha256"] for item in approved}) != len(approved)):
        raise bridge.BridgeError("Iscrizione approvazioni non valida")
    return enrollment


def _read_witnesses():
    """Every approved document must exactly match witness AND enrollment."""
    enrollment = _read_enrollment()
    directory = _witness_dir()
    witnessed_events, witnessed_approvals = {}, {}
    for item in directory.iterdir():
        match = re.fullmatch(r"([ea])-([0-9a-f]{64})\.json", item.name)
        if match is None:
            raise bridge.BridgeError("Residuo di continuità non verificabile")
        kind, sha = match.groups()
        proof = bridge.strict_json(bridge.read_regular(
            item, expected_parent=directory))
        if (set(proof) != {"schema", "kind", "sha", "record", "record_sha256"}
                or proof["schema"] != _WITNESS_SCHEMA
                or proof["kind"] != kind or proof["sha"] != sha
                or not isinstance(proof["record_sha256"], str)
                or not bridge.HEX.fullmatch(proof["record_sha256"])
                or not isinstance(proof["record"], dict)
                or bridge.digest(proof["record"]) != proof["record_sha256"]):
            raise bridge.BridgeError("Testimonianza di continuità alterata")
        if kind == "e":
            if proof["record_sha256"] != sha:
                raise bridge.BridgeError("Impronta evento non valida")
            witnessed_events[sha] = proof["record"]
        else:
            bridge.validate_approval_record(proof["record"], expected_sha=sha)
            witnessed_approvals[sha] = proof["record"]
    anchor = {e["versione_sha256"]: e["record_sha256"]
              for e in enrollment["approvals"]}
    if (set(enrollment["events"]) != set(witnessed_events)
            or set(anchor) != set(witnessed_approvals)
            or any(bridge.digest(witnessed_approvals[sha]) != digest
                   for sha, digest in anchor.items())):
        raise bridge.BridgeError("Impronte di continuità mancanti o mutate")
    return witnessed_events, witnessed_approvals


def _enrollment_add(kind, sha, record):
    """Durably reserve history in the independent enrollment BEFORE witness.

    A dropped witness plus a dropped history file must still disagree with
    the persisted enrollment's monotone expected identifiers.
    """
    root = bridge.PRIVATE_ROOT
    bridge._check_dir(root)
    marker = root / _ENROLLMENT
    enrollment = _read_enrollment()
    if kind == "e":
        if sha in enrollment["events"] or bridge.digest(record) != sha:
            raise DecisionContinuityError(_RESTORE_STOP)
        enrollment["events"] = sorted([*enrollment["events"], sha])
    else:
        bridge.validate_approval_record(record, expected_sha=sha)
        if any(item["versione_sha256"] == sha for item in enrollment["approvals"]):
            raise DecisionContinuityError(_RESTORE_STOP)
        enrollment["approvals"] = sorted(
            [*enrollment["approvals"], {"versione_sha256": sha,
                                       "record_sha256": bridge.digest(record)}],
            key=lambda item: item["versione_sha256"])
    stage = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".decision-enrollment-",
                                         suffix=".tmp", dir=root, delete=False) as stream:
            stage = Path(stream.name)
            stream.write(bridge.canonical(enrollment) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(stage, 0o600)
        os.replace(stage, marker)
        stage = None
        bridge._sync_dir(root)
    except (bridge.BridgeError, OSError) as exc:
        raise bridge.PublicationUncertain(
            "PUBBLICAZIONE_INCERTA: iscrizione decisioni") from exc
    finally:
        # A failed enrollment write may be an interrupted approval intent.
        # Preserve an unresolved stage as forensic evidence: normal reads
        # fail closed until an explicitly authorised reconciliation.
        pass


def _verify_continuity():
    """Any missing witness OR missing original record is STOP, never empty."""
    try:
        witnessed_events, witnessed_approvals = _read_witnesses()
        events = _history_unchecked()
        approvals = _approvals_unchecked()
        actual_events = {bridge.digest(row): row for row in events}
        if (actual_events != witnessed_events
                or approvals != witnessed_approvals):
            raise bridge.BridgeError("Storia deliberazioni discontinua")
        return events, approvals
    except (bridge.BridgeError, OSError, TypeError, KeyError) as exc:
        # Diagnostic specificity is display-only. Domain routing uses types.
        label = str(exc)
        suffix = (" | " + label if label.startswith((
            "STOP ARCHIVIO DECISIONI:", "STOP ARCHIVIO APPROVAZIONI:")) else "")
        raise DecisionContinuityError(_RESTORE_STOP + suffix) from exc


def _write_witness(kind, sha, record, *, enrolling=False):
    """Write-ahead immutable evidence, fsynced BEFORE event/approval commit.

    A crash between this write and destination commit leaves a detectable
    unresolved witness; no subsequent decision may silently bypass it.
    """
    if kind not in ("e", "a") or not bridge.HEX.fullmatch(sha):
        raise bridge.BridgeError("Testimonianza non valida")
    if not isinstance(record, dict):
        raise bridge.BridgeError("Record testimonianza assente")
    if kind == "e":
        if bridge.digest(record) != sha:
            raise bridge.BridgeError("Impronta evento non valida")
    else:
        bridge.validate_approval_record(record, expected_sha=sha)
    if not enrolling:
        _enrollment_add(kind, sha, record)
    directory = _witness_dir()
    final = directory / (kind + "-" + sha + ".json")
    obj = {"schema": _WITNESS_SCHEMA, "kind": kind, "sha": sha,
           "record": record, "record_sha256": bridge.digest(record)}
    raw = bridge.canonical(obj) + b"\n"
    try:
        fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        bridge._sync_dir(directory)
    except OSError as exc:
        raise bridge.PublicationUncertain(
            "PUBBLICAZIONE_INCERTA: testimonianza decisionale") from exc
    except bridge.BridgeError as exc:
        raise DecisionContinuityError(_RESTORE_STOP) from exc


def _continuity_snapshot(events, approvals):
    return bridge.digest({
        "eventi": sorted(bridge.digest(x) for x in events),
        "approvazioni": sorted(
            ({"versione_sha256": sha, "record_sha256": bridge.digest(record)}
             for sha, record in approvals.items()),
            key=lambda row: row["versione_sha256"]),
    })


def initialize_decision_continuity(*, mode, acknowledgement, expected_sha256=None,
                                   verified_approval_hashes=None):
    """EXPLICIT local enrollment or audited migration. Never called on reads.

    New: requires author acknowledgement and pristine observed inputs.
    Migration: requires independently checked expected state SHA; any
    missing-old-evidence possibility must be resolved by operator audit.
    This function is never run on the live Samsung by a test or import.
    """
    if mode not in ("NEW", "RECONCILE"):
        raise DecisionContinuityError(_RESTORE_STOP)
    literal = ("INIZIALIZZO_NUOVO_STORICO" if mode == "NEW"
               else "RICONCILIO_STORICO_PRECEDENTE")
    if acknowledgement != literal:
        raise DecisionContinuityError(_RESTORE_STOP)
    with _DECISION_LOCK:
        inbox = bridge.private_directory(bridge.INBOX, create=True)
        with bridge._archive_write_lock(inbox):
            root = bridge.PRIVATE_ROOT
            if bridge._path_present(root / _ENROLLMENT) or bridge._path_present(root / _WITNESSES):
                raise DecisionContinuityError(_RESTORE_STOP)
            events = _history_unchecked()
            approvals = _approvals_unchecked()
            out = root / bridge.OUTBOX
            if mode == "NEW":
                if events or approvals or bridge._path_present(inbox / INCOMING_NAME):
                    raise DecisionContinuityError(_RESTORE_STOP)
                if bridge._path_present(out):
                    bridge._check_dir(out)
                    if any(out.iterdir()):
                        raise DecisionContinuityError(_RESTORE_STOP)
            elif (not isinstance(expected_sha256, str)
                    or expected_sha256 != _continuity_snapshot(events, approvals)):
                raise DecisionContinuityError(_RESTORE_STOP)
            # A v001 ID-only history cannot certify archived metadata.
            # RECONCILE of pre-existing approvals requires independent,
            # explicitly supplied full-record hashes. No auto-upgrade.
            if approvals and (mode != "RECONCILE"
                    or type(verified_approval_hashes) is not dict
                    or set(verified_approval_hashes) != set(approvals)
                    or any(type(verified_approval_hashes[k]) is not str
                           or verified_approval_hashes[k] != bridge.digest(v)
                           for k, v in approvals.items())):
                raise DecisionContinuityError(_RESTORE_STOP)
            bridge.ensure_dir(root / _WITNESSES)
            for entry in events:
                _write_witness("e", bridge.digest(entry), entry, enrolling=True)
            for version, record in approvals.items():
                _write_witness("a", version, record, enrolling=True)
            # Enrollment is written LAST. Partial migration is not "new".
            enrollment = root / _ENROLLMENT
            data = bridge.canonical({
                "schema": _ENROLLMENT_SCHEMA,
                "nonce": secrets.token_hex(16),
                "events": sorted(bridge.digest(entry) for entry in events),
                "approvals": sorted(
                    ({"versione_sha256": sha, "record_sha256": bridge.digest(record)}
                     for sha, record in approvals.items()),
                    key=lambda row: row["versione_sha256"]),
            }) + b"\n"
            try:
                fd = os.open(enrollment, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                bridge._sync_dir(root)
            except OSError as exc:
                raise bridge.PublicationUncertain(
                    "PUBBLICAZIONE_INCERTA: inizializzazione storico") from exc
            _verify_continuity()
            return {"modo": mode, "eventi": len(events), "approvazioni": len(approvals)}


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
            _verify_continuity()
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
    """Origin is private KDD evidence, never part of FolderSync transport."""
    snapshot = proposal.get("snapshot_id") if isinstance(proposal, dict) else None
    if not isinstance(snapshot, str) or not bridge.HEX.fullmatch(snapshot):
        raise ProposalValidationError("Identita della fotografia non valida")
    try:
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
    except (bridge.BridgeError, OSError) as exc:
        raise PrivatePersistenceError(
            "STOP PERSISTENZA PRIVATA: origine KDD non verificabile") from exc


def validate_raw(raw):
    try:
        proposal = bridge.strict_json(raw)
    except bridge.BridgeError as exc:
        raise ProposalValidationError("STOP VALIDAZIONE: documento non valido") from exc
    bundle = find_origin(proposal)
    try:
        bridge.validate_proposal(proposal, bundle)
    except bridge.BridgeError as exc:
        raise ProposalValidationError("STOP VALIDAZIONE: proposta incompatibile") from exc
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


def _private_file_identity(path):
    """None ONLY for proven ENOENT. EIO, symlink and unsafe inode are STOP."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise bridge.BridgeError("Voce privata non verificabile: STOP") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise bridge.BridgeError("Voce privata non regolare: STOP")
    return (info.st_dev, info.st_ino)


def _approvals_unchecked():
    """Strict archive reader for continuity reconciliation; no recursion."""
    # Never mistake an unreadable approval archive for an empty consent chain.

    try:
        try:
            folder = bridge.private_directory(bridge.ARCHIVE)
        except bridge.BridgeError:
            if _missing_private_directory(bridge.ARCHIVE):
                return {}
            raise
        identity = bridge._check_dir(folder)
        versions = bridge.load_archive()
        if bridge._check_dir(folder) != identity:
            raise bridge.BridgeError("Archivio approvazioni sostituito")
        expected = {p.stem for p in folder.iterdir()
                    if re.fullmatch(r"[0-9a-f]{64}\.json", p.name)}
        if expected != set(versions):
            raise bridge.BridgeError("Archivio approvazioni non riconciliato")
        return versions
    except (OSError, bridge.BridgeError) as exc:
        raise bridge.BridgeError("STOP ARCHIVIO APPROVAZIONI: stato non verificabile") from exc


def _checked_approvals():
    return _verify_continuity()[1]


# Downward dependency injection: Bridge never imports Exchange. All direct
# approved_html() consumers use this exact fail-closed continuity validator.
bridge._approval_view_reader = _checked_approvals


def receive(raw):
    """Validate and import a new version without losing a still-pending choice."""
    with _decision_writer():
        return _receive_locked(raw)


def _receive_locked(raw):
    proposal, _ = validate_raw(raw)
    folder = bridge.private_directory(bridge.INBOX, create=True)
    final = folder / INCOMING_NAME
    sha = bridge.digest(proposal)
    approved = _checked_approvals()
    events = decision_history()
    if sha in approved or any(e["versione_sha256"] == sha for e in events):
        raise bridge.BridgeError("Versione già deliberata: nessuna riattivazione")

    before = _private_file_identity(final)
    if before is not None:
        existing = pending()
        if existing is not None:
            old = bridge.digest(existing[0])
        else:
            # Expired proposals remain identifiable from their private JSON.
            # Never treat an unreadable existing file as an empty inbox.
            old = bridge.digest(bridge.strict_json(
                bridge.read_regular(final, expected_parent=folder)))
        if old == sha:
            # An earlier os.replace may have succeeded while directory fsync
            # failed. Do not claim an idempotent SUCCESS until durability is
            # rechecked on this attempt.
            try:
                bridge._sync_dir(folder)
            except (OSError, bridge.BridgeError) as exc:
                raise bridge.PublicationUncertain(
                    "PUBBLICAZIONE_INCERTA: inbox da riconciliare") from exc
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
        if _private_file_identity(final) != before:
            raise bridge.BridgeError("Inbox privata mutata durante ricezione: STOP")
        try:
            os.replace(stage, final)
        except OSError as exc:
            # Replace may have completed before raising: never claim rollback.
            raise bridge.PublicationUncertain(
                "PUBBLICAZIONE_INCERTA: sostituzione inbox da verificare") from exc
        stage = None
        try:
            bridge._sync_dir(folder)
        except (OSError, bridge.BridgeError) as exc:
            raise bridge.PublicationUncertain(
                "PUBBLICAZIONE_INCERTA: inbox da riconciliare") from exc
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
        try:
            shared_dir = EXCHANGE_ROOT.lstat()
        except FileNotFoundError:
            return None  # A genuinely missing shared directory is not EIO.
        if not stat.S_ISDIR(shared_dir.st_mode):
            raise bridge.BridgeError("Cartella FolderSync non regolare: STOP")
        try:
            info = source.lstat()
        except FileNotFoundError:
            # Do not interpret a vanished/replaced parent as missing proposal.
            current_dir = EXCHANGE_ROOT.lstat()
            if (current_dir.st_dev, current_dir.st_ino) != (
                    shared_dir.st_dev, shared_dir.st_ino):
                raise bridge.BridgeError("Cartella FolderSync sostituita: STOP")
            return None
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
        raise FolderSyncError("STOP FolderSync: errore filesystem condiviso") from exc
    except bridge.BridgeError as exc:
        raise FolderSyncError("STOP FolderSync: file condiviso non verificabile") from exc
    # A known, already decided version may be stale when FolderSync copies it
    # back. Recognize its exact content digest before freshness validation.
    try:
        proposal = bridge.strict_json(raw)
    except bridge.BridgeError as exc:
        raise ProposalValidationError("STOP VALIDAZIONE: proposta ricevuta malformata") from exc
    sha = bridge.digest(proposal)
    with _decision_writer():
        approved = _checked_approvals()
        events = decision_history()
        if sha in approved or any(e["versione_sha256"] == sha for e in events):
            return sha  # previous A must not replace current B
        current = pending()
        if current is not None and bridge.digest(current[0]) == sha:
            return sha
        return _receive_locked(raw)

_PRIVATE_STOP = "STOP PERSISTENZA PRIVATA: proposta non leggibile o non verificabile"


def _missing_private_directory(name):
    """Verified absence of one private directory, never an obscured EIO."""
    if name not in (bridge.INBOX, bridge.ARCHIVE):
        raise bridge.BridgeError("Directory privata non autorizzata")
    root = bridge.PRIVATE_ROOT
    chain = (Path.home() / ".local", Path.home() / ".local" / "state",
             root.parent, root, root / name)
    for path in chain:
        try:
            os.lstat(path)
        except FileNotFoundError:
            return True
        bridge._check_dir(path, owner_only=path in
                          (root.parent, root, root / name))
    return False


def _missing_private_inbox():
    return _missing_private_directory(bridge.INBOX)


def pending():
    """None means VERIFIED ABSENCE, never an unreadable private proposal."""
    _verify_continuity()
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
    except (bridge.BridgeError, OSError) as exc:
        raise PrivatePersistenceError(_PRIVATE_STOP) from exc
    try:
        return validate_raw(raw)
    except (ProposalValidationError, PrivatePersistenceError) as exc:
        # This is an *already persisted private* document, not an inbound
        # candidate. A corrupted/ownerless local draft belongs to private.
        raise PrivatePersistenceError(_PRIVATE_STOP) from exc


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
        approved = _checked_approvals()
        if sha in approved:
            # An idempotent replay must never invent a fresh timestamp.
            return {"stato": "GIA_PRESENTE", "versione_sha256": sha}
        record = bridge.make_approval_record(proposal)
        result = bridge.approved_import(
            proposal, bundle, sha, "APPROVO_VERSIONE", prepared_record=record,
            before_commit=lambda exact: _write_witness("a", sha, exact))
        # No publication is declared successful without verifying the exact
        # durable record against BOTH enrollment and independent witness.
        _checked_approvals()
        return result

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



def _history_unchecked():
    """Strict low-level event reader for continuity checks; no recursion."""
    try:
        try:
            parent = bridge.private_directory(bridge.INBOX)
        except bridge.BridgeError:
            if _missing_private_inbox():
                return []
            raise
        before = bridge._check_dir(parent)
        folder = parent / DECISION_EVENTS
        try:
            os.lstat(folder)
        except FileNotFoundError:
            if bridge._check_dir(parent) != before:
                raise bridge.BridgeError("Inbox decisionale sostituita: STOP")
            return []
        bridge._check_dir(folder)
        rows = []
        basic = {"versione_sha256", "stato", "nota", "creato_utc"}
        for path in sorted(folder.iterdir()):
            if re.fullmatch(r"\.kdd-event-[A-Za-z0-9_-]+\.tmp", path.name):
                _private_file_identity(path)  # Inert but must be regular/private.
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
        return sorted(rows, key=_event_time)
    except (bridge.BridgeError, OSError) as exc:
        raise bridge.BridgeError("STOP ARCHIVIO DECISIONI: storia non verificabile") from exc


def decision_history():
    return _verify_continuity()[0]


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
        approved = _checked_approvals()
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
        # A witness exists and is fsynced BEFORE the first event write.
        _write_witness("e", bridge.digest(entry), entry)
        target = folder / filename
        if bridge._path_present(target):
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
            if bridge._path_present(target):
                raise bridge.BridgeError("Collisione evento durante commit: STOP")
            # Same-dir rename under the shared interprocess decision lock.
            try:
                os.rename(stage, target)
            except OSError as exc:
                raise bridge.PublicationUncertain(
                    "PUBBLICAZIONE_INCERTA: evento da riconciliare") from exc
            stage = None
            try:
                bridge._sync_dir(folder)
            except (OSError, bridge.BridgeError) as exc:
                raise bridge.PublicationUncertain(
                    "PUBBLICAZIONE_INCERTA: evento da riconciliare") from exc
            return "INSERITO"
        finally:
            if stage is not None:
                stage.unlink(missing_ok=True)

def render_page(token):
    esc = lambda s: html.escape(str(s), quote=True)
    sync_error = private_sync_error = validation_error = None
    try:
        receive_synced()
    except FolderSyncError as exc:
        sync_error = str(exc)
    except PrivatePersistenceError as exc:
        private_sync_error = str(exc)
    except ProposalValidationError as exc:
        validation_error = str(exc)
    except bridge.BridgeError:
        validation_error = "STOP VALIDAZIONE: ricezione KDD non verificabile"
    try:
        item = pending()
        if item is not None:
            # A private draft is not displayable as decidable without a
            # trustworthy account of prior approvals and author decisions.
            _checked_approvals()
            decision_history()
        error = None
    except bridge.BridgeError as exc:
        item, error = None, str(exc)
    if error:
        preview = "<p class='warn'>STOP: " + esc(error) + "</p>"
    elif item is None:
        if private_sync_error:
            preview = "<p class='warn'>STOP PERSISTENZA PRIVATA: ricezione non verificabile.</p>"
        elif validation_error:
            preview = "<p class='warn'>STOP VALIDAZIONE: documento non attribuibile.</p>"
        elif sync_error:
            preview = "<p class='warn'>STOP FolderSync: ingresso non verificabile.</p>"
        else:
            preview = "<p>Nessuna proposta ricevuta dalla chat o da Drive.</p>"
    else:
        proposal, bundle = item
        state = bridge.read_context(bundle)
        sha = bridge.digest(proposal)
        already_approved = sha in _checked_approvals()
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
    if private_sync_error:
        preview = ("<p class='warn'>STOP PERSISTENZA PRIVATA: "
                   + esc(private_sync_error) + "</p>" + preview)
    if validation_error:
        preview = ("<p class='warn'>STOP VALIDAZIONE: "
                   + esc(validation_error) + "</p>" + preview)
    if item is not None and not error and (already_approved or declined):
        preview = preview.split("<button onclick=", 1)[0]
    try:
        events = decision_history()
        approvals = _checked_approvals()
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
        archive = bridge.approved_html(verified_records=approvals) + "<h3>Decisioni e riesami datati</h3>" + (history or "<p>Nessun evento registrato.</p>")
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
                  if sha in _checked_approvals() else ("RIFIUTATA", "RINVIATA"))
        if states and not (sha not in _checked_approvals() and any(
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
    fresh = sub.add_parser("inizializza-storico")
    fresh.add_argument("--consenso", required=True)
    migrate = sub.add_parser("riconcilia-storico")
    migrate.add_argument("--consenso", required=True)
    migrate.add_argument("--expected-sha256", required=True)
    incoming = sub.add_parser("ricevi-chat")
    incoming.add_argument("--file-sha256", required=True)
    incoming.add_argument("--proposta-sha256", required=True)
    incoming.add_argument("--consenso-pubblicazione", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action in ("inizializza-storico", "riconcilia-storico"):
            mode = "NEW" if args.action == "inizializza-storico" else "RECONCILE"
            result = initialize_decision_continuity(
                mode=mode, acknowledgement=args.consenso,
                expected_sha256=getattr(args, "expected_sha256", None))
            print("CONTINUITA DECISIONI ISCRITTA |", result["modo"],
                  "| eventi:", result["eventi"],
                  "| approvazioni:", result["approvazioni"])
            return 0
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
