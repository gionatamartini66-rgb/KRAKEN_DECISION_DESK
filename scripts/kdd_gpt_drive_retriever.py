"""KDD G2-A: deterministic read-only Drive dossier recovery, isolated prototype.

No Google credentials, private KDD filesystem, network calls, files written, orders,
plugin registration or deploy. A Drive adapter and bridge validator are injected.

Production validation delegates to the UNMODIFIED KDD bridge.read_context().
This module does not claim to authenticate the producer: checksums only attest
byte consistency and the handoff's self-consistent canonical representation.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import re
from typing import Callable, Protocol
from urllib.parse import quote

UTC = dt.timezone.utc
MAX_BYTES = 8_000_000  # The canonical bridge's maximum
MAX_LIST_PAGES = 1000
MAX_INVENTORY_FILES = 10000
HANDOFF = re.compile(r"kdd_handoff_([0-9a-f]{64})\.json\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "kdd_private_handoff_v001"

RECOVERED = "DOSSIER_RECUPERATO"
STALE = "DOSSIER_SCADUTO"
UNVERIFIABLE = "DOSSIER_NON_VERIFICABILE"
ACCESS = "ACCESSO_NON_DISPONIBILE"


class AccessUnavailable(Exception):
    """No authenticated or usable read-only access to the Drive source."""


class EvidenceFailure(Exception):
    """A non-sensitive failure in the inventory, bytes or logical contract."""


class DriveReader(Protocol):
    def list_page(self, page_token: str | None) -> dict: ...
    def download(self, file_id: str) -> bytes: ...


class BridgeReader(Protocol):
    def validate(self, handoff: dict, when: dt.datetime, logical_sha: str) -> dict: ...


class OriginalKddBridge:
    """The original bridge is mandatory at runtime; no partial fallback."""

    def validate(self, handoff: dict, when: dt.datetime, logical_sha: str) -> dict:
        from scripts import kdd_bridge_g2 as bridge
        return bridge.read_context(handoff, now=when, expected_sha256=logical_sha)


@dataclass(frozen=True)
class Dossier:
    file_id: str
    name: str
    logical_sha: str
    raw_sha: str
    prepared: dt.datetime
    snapshot: dt.datetime
    context: dict
    provider_sha_checked: bool


def canonical(obj: object) -> bytes:
    """Exactly the existing bridge.canonical() JSON serialization."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, val in pairs:
        if key in result:
            raise EvidenceFailure("JSON_DUPLICATE_KEYS")
        result[key] = val
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceFailure("JSON_NONFINITE_NUMBER")


def parse_handoff(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                         parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise EvidenceFailure("JSON_INVALIDO") from exc
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
        raise EvidenceFailure("SCHEMA_TRASPORTO_INVALIDO")
    try:
        expected = canonical(obj) + b"\n"
    except (ValueError, TypeError, RecursionError) as exc:
        raise EvidenceFailure("JSON_NON_CANONICO") from exc
    if raw != expected:
        raise EvidenceFailure("BYTE_NON_CANONICI")
    return obj


def _timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise EvidenceFailure("TIMESTAMP_ASSENTE")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise EvidenceFailure("TIMESTAMP_INVALIDO") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceFailure("TIMESTAMP_SENZA_FUSO")
    return parsed.astimezone(UTC)


def _now(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        value = dt.datetime.now(UTC)
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceFailure("OROLOGIO_LETTURA_INVALIDO")
    return value.astimezone(UTC)


def _inventory(reader: DriveReader, folder_id: str) -> list[dict]:
    cursor: str | None = None
    used_tokens: set[str] = set()
    seen_ids: set[str] = set()
    items: list[dict] = []
    for _ in range(MAX_LIST_PAGES):
        page = reader.list_page(cursor)
        if not isinstance(page, dict) or not isinstance(page.get("files"), list):
            raise EvidenceFailure("PAGINA_NON_VALIDA")
        if page.get("incompleteSearch") is not False:
            raise EvidenceFailure("INVENTARIO_NON_COMPLETO")
        for file in page["files"]:
            if not isinstance(file, dict) or not isinstance(file.get("id"), str) or not file["id"]:
                raise EvidenceFailure("METADATI_NON_VALIDI")
            if file["id"] in seen_ids:
                raise EvidenceFailure("IDENTIFICATIVO_DRIVE_DUPLICATO")
            seen_ids.add(file["id"])
            if file.get("trashed") is True:
                raise EvidenceFailure("ELEMENTO_CESTINATO_NELLA_RISPOSTA")
            if not isinstance(file.get("parents"), list) or folder_id not in file["parents"]:
                raise EvidenceFailure("CARTELLA_ORIGINE_NON_ATTESTATA")
            items.append(file)
            if len(items) > MAX_INVENTORY_FILES:
                raise EvidenceFailure("LIMITE_INVENTARIO")
        token = page.get("nextPageToken")
        if token is None:
            return items
        if not isinstance(token, str) or not token or token in used_tokens:
            raise EvidenceFailure("PAGINAZIONE_INCOERENTE")
        used_tokens.add(token)
        cursor = token
    raise EvidenceFailure("LIMITE_PAGINE")


def _inventory_fingerprint(items: list[dict]) -> str:
    """Detect metadata changes and additions between the two complete scans."""
    return hashlib.sha256(canonical(sorted(items, key=lambda f: f["id"]))).hexdigest()


def _read_candidate(reader: DriveReader, validator: BridgeReader, file: dict,
                    when: dt.datetime) -> Dossier:
    name = file.get("name")
    match = HANDOFF.fullmatch(name) if isinstance(name, str) else None
    if match is None:
        raise EvidenceFailure("NOME_DOSSIER_INVALIDO")
    if file.get("mimeType") not in ("application/json", "application/octet-stream", "text/plain"):
        raise EvidenceFailure("TIPO_FILE_NON_BINARY")
    size = file.get("size")
    if type(size) not in (str, int) or not str(size).isdigit() or not (2 <= int(size) <= MAX_BYTES):
        raise EvidenceFailure("DIMENSIONE_NON_VALIDA")
    raw = reader.download(file["id"])
    if not isinstance(raw, bytes) or len(raw) != int(size) or len(raw) > MAX_BYTES:
        raise EvidenceFailure("BYTE_DIFFERENTI_DALL_INVENTARIO")
    raw_sha = hashlib.sha256(raw).hexdigest()
    source_sha = file.get("sha256Checksum")
    provider_sha_checked = False
    if source_sha is not None:
        if not isinstance(source_sha, str) or not SHA256.fullmatch(source_sha.lower()) or raw_sha != source_sha.lower():
            raise EvidenceFailure("CHECKSUM_DRIVE_DISCORDANTE")
        provider_sha_checked = True
    md5 = file.get("md5Checksum")
    if md5 is not None:
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5) or hashlib.md5(raw).hexdigest() != md5.lower():
            raise EvidenceFailure("MD5_DRIVE_DISCORDANTE")
    handoff = parse_handoff(raw)
    logical_sha = hashlib.sha256(canonical(handoff)).hexdigest()
    if logical_sha != match.group(1):
        raise EvidenceFailure("IDENTITA_LOGICA_DISCORDANTE")
    packet = handoff.get("packet")
    if not isinstance(packet, dict):
        raise EvidenceFailure("PACCHETTO_ASSENTE")
    prepared = _timestamp(handoff.get("preparato_utc"))
    snapshot = _timestamp(packet.get("rilevazione_kdd_utc"))
    # Original KDD bridge is the normative semantic validator. It validates
    # packet digest, wallet identities, prices, timestamps, evidence and freshness.
    try:
        context = validator.validate(handoff, when, logical_sha)
    except Exception as exc:
        # Fail closed even for missing import/bridge dependencies. Do not
        # expose untrusted payload text or internal exception messages.
        raise EvidenceFailure("VALIDATORE_KDD_NON_SUPERATO") from exc
    if not isinstance(context, dict) or context.get("schema") != "kdd_gpt_read_context_v001":
        raise EvidenceFailure("RISULTATO_VALIDATORE_INVALIDO")
    if context.get("snapshot_utc") != packet["rilevazione_kdd_utc"] or context.get("nessun_ordine") is not True:
        raise EvidenceFailure("CONTRATTO_VALIDATORE_INCOERENTE")
    return Dossier(file["id"], name, logical_sha, raw_sha, prepared, snapshot,
                   context, provider_sha_checked)


def _presentation(status: str, code: str, selected: Dossier | None = None, **more) -> dict:
    out = {"stato": status, "codice": code, "nessun_ordine": True,
           "integrita_origine": "NON_AUTENTICATA"}
    if selected is not None:
        out.update({"file_id": selected.file_id, "nome": selected.name,
                    "digest_logico": selected.logical_sha, "sha256_byte": selected.raw_sha,
                    "sha256_drive_confrontato": selected.provider_sha_checked,
                    "preparato_utc": selected.prepared.isoformat(),
                    "snapshot_utc": selected.snapshot.isoformat(),
                    "contesto_kdd": selected.context})
    out.update(more)
    return out


def kdd_get_latest_verified_dossier(reader: DriveReader, folder_id: str, *,
                                   validator: BridgeReader | None = None,
                                   now: dt.datetime | None = None) -> dict:
    """Single entry point. All source paths fail closed; no historical fallback.

    Two complete paginated inventories surround validation to detect concurrent
    metadata changes. Drive doesn't offer atomic cross-page snapshots, so this
    is a best-effort stability check, not absolute transactional isolation.
    """
    try:
        moment = _now(now)
        if not isinstance(folder_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", folder_id):
            raise EvidenceFailure("CARTELLA_NON_CONFIGURATA")
        validator = validator if validator is not None else OriginalKddBridge()
        first = _inventory(reader, folder_id)
        candidates = []
        for file in first:
            name = file.get("name")
            if not isinstance(name, str):
                raise EvidenceFailure("NOME_FILE_MANCANTE")
            if not name.startswith("kdd_handoff_"):
                continue
            candidates.append(file)
        if not candidates:
            raise EvidenceFailure("NESSUN_DOSSIER")
        validated: list[Dossier] = []
        for file in candidates:
            validated.append(_read_candidate(reader, validator, file, moment))
        second = _inventory(reader, folder_id)
        if _inventory_fingerprint(first) != _inventory_fingerprint(second):
            raise EvidenceFailure("INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")
        newest = max(d.prepared for d in validated)
        tied = [d for d in validated if d.prepared == newest]
        if len({d.logical_sha for d in tied}) != 1:
            raise EvidenceFailure("DUPLICATI_TEMPORALI_INCOMPATIBILI")
        selected = min(tied, key=lambda d: d.file_id)
        market = selected.context.get("mercato")
        balance = selected.context.get("saldo")
        if not isinstance(market, dict) or not isinstance(balance, dict):
            raise EvidenceFailure("STATO_LETTURA_ASSENTE")
        states = [market.get("stato"), balance.get("stato")]
        if any(s in ("OROLOGIO_INCOERENTE", "OROLOGI_DISALLINEATI") for s in states):
            raise EvidenceFailure("OROLOGIO_INCOERENTE")
        state = RECOVERED if states == ["RECENTE", "RECENTE"] else STALE
        return _presentation(state, "LETTURA_VERIFICATA" if state == RECOVERED else "FONTI_NON_RECENTI",
                             selected, numero_dossier=len(candidates),
                             inventario_stabile_su_due_scansioni=True)
    except (AccessUnavailable, PermissionError):
        return _presentation(ACCESS, "AUTORIZZAZIONE_O_LETTURA_ASSENTE")
    except EvidenceFailure as exc:
        return _presentation(UNVERIFIABLE, str(exc))
    except (OSError, TimeoutError, ConnectionError):
        return _presentation(ACCESS, "ACCESSO_FONTE_NON_DISPONIBILE")
    except Exception:
        return _presentation(UNVERIFIABLE, "ERRORE_NON_CLASSIFICATO")


class DriveV3ReadOnlyAdapter:
    """Production-shaped Drive REST v3 adapter with *injected* authorized I/O.

    json_get(url, params) -> JSON and bytes_get(url, params) -> bytes.
    Authentication, permissions, retries and networking live outside this class.
    This class never requests an OAuth token or makes requests by itself.
    """
    ROOT = "https://www.googleapis.com/drive/v3/files"

    def __init__(self, folder_id: str,
                 json_get: Callable[[str, dict], dict],
                 bytes_get: Callable[[str, dict], bytes]):
        self.folder_id = folder_id
        self.json_get = json_get
        self.bytes_get = bytes_get

    def list_page(self, page_token: str | None) -> dict:
        escaped = self.folder_id.replace("'", "\\'")
        params = {
            "q": f"'{escaped}' in parents and trashed = false",
            "fields": ("nextPageToken,incompleteSearch,"
                       "files(id,name,mimeType,parents,size,createdTime,modifiedTime,"
                       "sha256Checksum,md5Checksum,trashed)"),
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "user",
        }
        if page_token is not None:
            params["pageToken"] = page_token
        return self.json_get(self.ROOT, params)

    def download(self, file_id: str) -> bytes:
        return self.bytes_get(self.ROOT + "/" + quote(file_id, safe=""),
                              {"alt": "media", "supportsAllDrives": "true"})
