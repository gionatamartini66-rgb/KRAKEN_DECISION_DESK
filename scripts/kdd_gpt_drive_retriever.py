"""KDD G2-C: bounded read-only Drive dossier recovery, isolated prototype.

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
import time
from typing import Callable, Protocol
from urllib.parse import quote

from scripts import kdd_drive_index as index
from scripts.kdd_drive_index import canonical

UTC = dt.timezone.utc
MAX_BYTES = index.MAX_DOSSIER_BYTES
MAX_LIST_PAGES = 80  # Per scan
MAX_INVENTORY_FILES = 10_000  # Per scan, including unrelated rows
MAX_METADATA_BYTES = 512 * 1024  # Per response, enforced by the transport
MAX_DOWNLOADS = 4
MAX_TOTAL_BYTES = 16_000_000
MAX_SECONDS = 30
MAX_REQUEST_SECONDS = 5
VALIDATION_WINDOW = dt.timedelta(seconds=2)
FILE_FIELDS = ("id,name,mimeType,parents,size,createdTime,modifiedTime,"
               "sha256Checksum,md5Checksum,trashed,version,headRevisionId")
DRIVE_TIMESTAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})[Tt]([0-9]{2}:[0-9]{2}):([0-5][0-9]|60)"
    r"(?:\.([0-9]+))?([Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z"
)
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
    # The transport must enforce the given timeout and response cap during I/O.
    def list_page(self, page_token: str | None, *, timeout: float) -> dict: ...
    def download(self, file_id: str, *, max_bytes: int, timeout: float) -> bytes: ...
    def file_metadata(self, file_id: str, *, timeout: float) -> dict: ...


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
    handoff: dict
    provider_sha_checked: bool


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, val in pairs:
        if key in result:
            raise EvidenceFailure("JSON_DUPLICATE_KEYS")
        result[key] = val
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceFailure("JSON_NONFINITE_NUMBER")


def _canonical_object(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                         parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise EvidenceFailure("JSON_INVALIDO") from exc
    if not isinstance(obj, dict):
        raise EvidenceFailure("SCHEMA_TRASPORTO_INVALIDO")
    try:
        expected = canonical(obj) + b"\n"
    except (ValueError, TypeError, RecursionError) as exc:
        raise EvidenceFailure("JSON_NON_CANONICO") from exc
    if raw != expected:
        raise EvidenceFailure("BYTE_NON_CANONICI")
    return obj


def _now(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        value = dt.datetime.now(UTC)
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceFailure("OROLOGIO_LETTURA_INVALIDO")
    return value.astimezone(UTC)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EvidenceFailure("LIMITE_DURATA_RECUPERO")
    return min(remaining, MAX_REQUEST_SECONDS)


def _inventory(reader: DriveReader, folder_id: str, deadline: float, *,
               attest_current: bool = False) -> tuple[list[dict], dict]:
    cursor: str | None = None
    used_tokens: set[str] = set()
    seen_ids: set[str] = set()
    items: list[dict] = []
    audit = {"file_estranei": 0, "nomi_fuori_schema_con_prefisso_kdd": 0,
             "dossier_storici_senza_indice": 0, "numero_dossier": 0}
    for _ in range(MAX_LIST_PAGES):
        page = reader.list_page(cursor, timeout=_remaining(deadline))
        _remaining(deadline)
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
            if len(seen_ids) > MAX_INVENTORY_FILES:
                raise EvidenceFailure("LIMITE_INVENTARIO")
            name = file.get("name")
            if not isinstance(name, str) or not name:
                raise EvidenceFailure("NOME_FILE_MANCANTE")
            if index.LEGACY.fullmatch(name) is not None:
                audit["dossier_storici_senza_indice"] += 1
                audit["numero_dossier"] += 1
                continue
            dossier_match = index.DOSSIER.fullmatch(name)
            match = dossier_match or index.INDEX.fullmatch(name)
            if match is None:
                if name.startswith((index.INDEX_PREFIX, index.DOSSIER_PREFIX)):
                    raise EvidenceFailure("NOME_PUBBLICAZIONE_KDD_INVALIDO")
                audit["file_estranei"] += 1
                audit["nomi_fuori_schema_con_prefisso_kdd"] += name.startswith("kdd_handoff_")
                continue
            try:
                index.prepared_from_stamp(match[1])
            except ValueError as exc:
                raise EvidenceFailure("DATA_PUBBLICAZIONE_KDD_INVALIDA") from exc
            if not attest_current:
                if file.get("trashed") is True:
                    raise EvidenceFailure("ELEMENTO_CESTINATO_NELLA_RISPOSTA")
                if file.get("trashed") is not False:
                    raise EvidenceFailure("STATO_CESTINO_DOSSIER_NON_ATTESTATO")
                if file.get("parents") != [folder_id]:
                    raise EvidenceFailure("CARTELLA_ORIGINE_NON_ATTESTATA")
            items.append(_file_metadata(file))
            if dossier_match:
                audit["numero_dossier"] += 1
        token = page.get("nextPageToken")
        if token is None:
            return items, audit
        if not isinstance(token, str) or not token or token in used_tokens:
            raise EvidenceFailure("PAGINAZIONE_INCOERENTE")
        used_tokens.add(token)
        cursor = token
    raise EvidenceFailure("LIMITE_PAGINE")


def _file_metadata(file: dict) -> dict:
    return {key: file.get(key) for key in FILE_FIELDS.split(",")}


def _drive_timestamp(value: object) -> tuple[dt.datetime, bool, str] | None:
    if value is None:
        return None
    match = DRIVE_TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise EvidenceFailure("TIMESTAMP_DRIVE_INVALIDO")
    date, hour_minute, seconds, fraction, zone = match.groups()
    leap = seconds == "60"
    try:
        ordinary_seconds = "59" if leap else seconds
        whole = index.utc(f"{date}T{hour_minute}:{ordinary_seconds}{zone.upper()}")
        if leap:
            following = whole + dt.timedelta(seconds=1)
            if following.day != 1 or following.time() != dt.time():
                raise ValueError("Leap second outside the end of a UTC month")
    except (ValueError, OverflowError) as exc:
        raise EvidenceFailure("TIMESTAMP_DRIVE_INVALIDO") from exc
    # Compare exact fractions, including digits beyond datetime's precision.
    return whole, leap, (fraction or "").rstrip("0")


def _select_candidates(files: list[dict]) -> tuple[str, str, list[dict], list[dict]]:
    if not files:
        raise EvidenceFailure("INDICE_CORRENTE_ASSENTE")
    named = {}
    for file in files:
        named.setdefault(file["name"], []).append(file)
    keys = [(index.INDEX.fullmatch(name) or index.DOSSIER.fullmatch(name)).groups()
            for name in named]
    stamp = max(stamp for stamp, _ in keys)
    digests = {digest for key, digest in keys if key == stamp}
    if len(digests) != 1:
        raise EvidenceFailure("PUBBLICAZIONE_CORRENTE_AMBIGUA")
    digest = digests.pop()
    dossier_name, index_name = index.names(stamp, digest)
    indices, dossiers = named.get(index_name, []), named.get(dossier_name, [])
    if not indices:
        raise EvidenceFailure("INDICE_CORRENTE_ASSENTE")
    if not dossiers:
        raise EvidenceFailure("DOSSIER_INDICIZZATO_NON_ARRIVATO")
    if len(indices) + len(dossiers) > MAX_DOWNLOADS:
        raise EvidenceFailure("LIMITE_CANDIDATI_CORRENTI")
    return stamp, digest, sorted(indices, key=lambda f: f["id"]), sorted(dossiers, key=lambda f: f["id"])


def _candidate_size(file: dict, limit: int) -> int:
    if file["mimeType"] not in ("application/json", "application/octet-stream", "text/plain"):
        raise EvidenceFailure("TIPO_FILE_NON_BINARY")
    # Drive creation and source modification describe different events.
    # FolderSync can preserve a modification timestamp older than the upload.
    _drive_timestamp(file["createdTime"])
    _drive_timestamp(file["modifiedTime"])
    version, revision = file["version"], file["headRevisionId"]
    if version is not None and (not isinstance(version, str)
                                or not re.fullmatch(r"[1-9][0-9]{0,18}", version)):
        raise EvidenceFailure("VERSIONE_DRIVE_INVALIDA")
    if revision is not None and (not isinstance(revision, str) or not revision.strip()):
        raise EvidenceFailure("REVISIONE_DRIVE_INVALIDA")
    size = file["size"]
    if (type(size) not in (str, int) or not re.fullmatch(r"[0-9]{1,7}", str(size))
            or not 2 <= int(size) <= limit):
        raise EvidenceFailure("DIMENSIONE_NON_VALIDA")
    return int(size)


def _checked_download(reader: DriveReader, file: dict, size: int, deadline: float) -> tuple[bytes, str]:
    raw = reader.download(file["id"], max_bytes=size, timeout=_remaining(deadline))
    _remaining(deadline)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise EvidenceFailure("BYTE_DIFFERENTI_DALL_INVENTARIO")
    raw_sha = hashlib.sha256(raw).hexdigest()
    source_sha = file.get("sha256Checksum")
    if source_sha is not None:
        if not isinstance(source_sha, str) or not index.SHA256.fullmatch(source_sha.lower()) or raw_sha != source_sha.lower():
            raise EvidenceFailure("CHECKSUM_DRIVE_DISCORDANTE")
    md5 = file.get("md5Checksum")
    if md5 is not None:
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5) or hashlib.md5(raw).hexdigest() != md5.lower():
            raise EvidenceFailure("MD5_DRIVE_DISCORDANTE")
    return raw, raw_sha


def _read_identical(reader: DriveReader, candidates: list[dict], sizes: list[int],
                    deadline: float) -> tuple[bytes, str]:
    raw, raw_sha = _checked_download(reader, candidates[0], sizes[0], deadline)
    for duplicate, size in zip(candidates[1:], sizes[1:]):
        other, _ = _checked_download(reader, duplicate, size, deadline)
        if raw != other:
            raise EvidenceFailure("DUPLICATO_CORRENTE_DISCORDANTE")
    return raw, raw_sha


def _current_sizes(indices: list[dict], dossiers: list[dict]) -> tuple[list[int], list[int]]:
    index_sizes = [_candidate_size(file, index.MAX_INDEX_BYTES) for file in indices]
    dossier_sizes = [_candidate_size(file, MAX_BYTES) for file in dossiers]
    if sum(index_sizes) + sum(dossier_sizes) > MAX_TOTAL_BYTES:
        raise EvidenceFailure("LIMITE_BYTE_RECUPERO")
    return index_sizes, dossier_sizes


def _read_current(reader: DriveReader, stamp: str, digest: str, indices: list[dict],
                  dossiers: list[dict], deadline: float) -> tuple[Dossier, str]:
    index_sizes, dossier_sizes = _current_sizes(indices, dossiers)
    index_raw, index_sha = _read_identical(reader, indices, index_sizes, deadline)
    try:
        manifest = _canonical_object(index_raw)
        index.check_index(manifest, stamp, digest)
    except (EvidenceFailure, ValueError, OverflowError) as exc:
        raise EvidenceFailure("INDICE_CORRENTE_INVALIDO") from exc

    if any(size != manifest["dimensione_byte"] for size in dossier_sizes):
        raise EvidenceFailure("DIMENSIONE_DOSSIER_DISCORDE_DA_INDICE")
    raw, raw_sha = _read_identical(reader, dossiers, dossier_sizes, deadline)
    if raw_sha != manifest["sha256_byte"]:
        raise EvidenceFailure("BYTE_DOSSIER_DISCORDI_DA_INDICE")
    handoff = _canonical_object(raw)
    if handoff.get("schema") != SCHEMA:
        raise EvidenceFailure("SCHEMA_TRASPORTO_INVALIDO")
    if hashlib.sha256(raw[:-1]).hexdigest() != digest:
        raise EvidenceFailure("IDENTITA_LOGICA_DISCORDANTE")
    try:
        _, _, expected_index = index.publication(handoff, raw)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise EvidenceFailure("SCHEMA_TRASPORTO_INVALIDO") from exc
    if expected_index != manifest:
        raise EvidenceFailure("INDICE_E_DOSSIER_DISCORDANTI")
    file = dossiers[0]
    selected = Dossier(file["id"], file["name"], digest, raw_sha,
                       index.utc(manifest["preparato_utc"]), index.utc(manifest["snapshot_utc"]),
                       handoff, file["sha256Checksum"] is not None)
    return selected, index_sha


def _check_current_versions(reader: DriveReader, candidates: list[dict], deadline: float) -> int:
    checked = 0
    for file in candidates:
        if file["version"] is None and file["headRevisionId"] is None:
            continue
        observed = reader.file_metadata(file["id"], timeout=_remaining(deadline))
        _remaining(deadline)
        if not isinstance(observed, dict) or _file_metadata(observed) != file:
            raise EvidenceFailure("VERSIONE_CORRENTE_CAMBIATA_DURANTE_LA_LETTURA")
        checked += 1
    return checked


def _attest_current(current, attest, deadline):
    stamp, digest, indices, dossiers = current
    rows = [attest(file, timeout=_remaining(deadline)) for file in indices + dossiers]
    _remaining(deadline)
    files = [file for file, _ in rows]
    return (stamp, digest, files[:len(indices)], files[len(indices):]), dict(
        (file["id"], evidence) for file, evidence in rows)


def _final_context(dossier: Dossier, validator: BridgeReader, when: dt.datetime) -> dict:
    # Original KDD bridge is the normative semantic validator. It validates
    # packet digest, wallet identities, prices, timestamps, evidence and freshness.
    try:
        context = validator.validate(dossier.handoff, when, dossier.logical_sha)
    except ImportError as exc:
        raise EvidenceFailure("VALIDATORE_KDD_INDISPONIBILE") from exc
    except Exception as exc:
        # Do not expose untrusted payload text or internal exception messages.
        raise EvidenceFailure("VALIDATORE_KDD_NON_SUPERATO") from exc
    if not isinstance(context, dict) or context.get("schema") != "kdd_gpt_read_context_v001":
        raise EvidenceFailure("RISULTATO_VALIDATORE_INVALIDO")
    if (context.get("snapshot_utc") != dossier.handoff["packet"]["rilevazione_kdd_utc"]
            or context.get("nessun_ordine") is not True):
        raise EvidenceFailure("CONTRATTO_VALIDATORE_INCOERENTE")
    return context


def _presentation(status: str, code: str, selected: Dossier | None = None, **more) -> dict:
    out = {"stato": status, "codice": code, "nessun_ordine": True,
           "integrita_origine": "NON_AUTENTICATA",
           "integrita_documento": "VERIFICATA" if selected else "NON_VERIFICATA"}
    if selected is not None:
        out.update({"file_id": selected.file_id, "nome": selected.name,
                    "digest_logico": selected.logical_sha, "sha256_byte": selected.raw_sha,
                    "sha256_drive_confrontato": selected.provider_sha_checked,
                    "preparato_utc": selected.prepared.isoformat(),
                    "snapshot_utc": selected.snapshot.isoformat()})
    out.update(more)
    return out


SOURCE_STATES = {
    "RECENTE": "RECENTE",
    "DA_AGGIORNARE": "SCADUTA",
    "ORIGINE_SCONOSCIUTA": "NON_VERIFICABILE",
    "OROLOGIO_INCOERENTE": "NON_VERIFICABILE",
    "OROLOGI_DISALLINEATI": "NON_VERIFICABILE",
}


def _base_sources(dossier: Dossier, context: dict) -> dict:
    if any(not isinstance(context.get(key), dict) for key in ("mercato", "saldo")):
        raise EvidenceFailure("STATO_LETTURA_ASSENTE")
    sources = {
        key: {"stato": SOURCE_STATES.get(context[key].get("stato"), "NON_VERIFICABILE"),
              "stato_bridge": context[key].get("stato")}
        for key in ("mercato", "saldo")
    }
    if not dossier.handoff["packet"]["saldo"].get("ultima_acquisizione_utc"):
        sources["saldo"]["stato"] = "ASSENTE"
    return sources


def _base_outcome(sources: dict) -> tuple[str, str]:
    states = {source["stato"] for source in sources.values()}
    if "NON_VERIFICABILE" in states:
        return UNVERIFIABLE, "FONTE_BASE_NON_VERIFICABILE"
    if "ASSENTE" in states:
        return UNVERIFIABLE, "FONTE_BASE_ASSENTE"
    if "SCADUTA" in states:
        return STALE, "FONTI_BASE_SCADUTE"
    return RECOVERED, "FONTI_BASE_RECENTI"


def _analytical_evidence(dossier: Dossier, context: dict) -> dict:
    packet = dossier.handoff["packet"]
    multifonte = packet.get("evidenze_multifonte")
    multifonte = multifonte if isinstance(multifonte, dict) else {}
    derivatives = multifonte.get("derivati_btc")
    derivatives = derivatives if isinstance(derivatives, dict) else {}
    holdings = packet["patrimonio"]
    evidence = {}
    for label, source, key in (
        ("economia", multifonte.get("economia"), "evidenze_economiche_alla_lettura"),
        ("flusso_futures", derivatives.get("flusso_futures"), "flusso_futures_alla_lettura"),
        ("rete_defi", multifonte.get("rete_defi"), "rete_defi_alla_lettura"),
        ("book", holdings.get("profondita_book_pubblica", holdings.get("book_pubblico_150")),
         "book_alla_lettura"),
    ):
        value = context.get(key)
        state = value.get("stato") if isinstance(value, dict) else None
        availability = "STATI_NEL_CONTESTO"
        if source is None or state == "NON_ACQUISITO":
            availability = "ASSENTE"
        elif not isinstance(value, dict) or state in (
                "NON_ATTESTATO", "NON_VERIFICABILE", "NON_VERIFICATO", "OROLOGIO_INCOERENTE"):
            availability = "NON_VERIFICABILE"
        evidence[label] = {"disponibilita": availability, "stato_bridge": state,
                           "chiave_contesto_kdd": key}
    return evidence


def _without_read_clock(context: dict) -> dict:
    comparable = dict(context)
    comparable.pop("letto_utc", None)
    for key in ("mercato", "saldo", "evidenze_economiche_alla_lettura"):
        value = comparable.get(key)
        if isinstance(value, dict):
            comparable[key] = {k: v for k, v in value.items()
                               if k not in ("letto_utc", "eta_minuti")}
    network_key = "rete_defi_alla_lettura"
    network = comparable.get(network_key)
    if isinstance(network, dict) and network.get("stato") == "NON_ACQUISITO":
        network = dict(network)
        comparable[network_key] = network
        # The bridge inserts the read time into empty DeFi rows in this case.
        # When observations exist, their acquisition times stay in the comparison.
        for group in ("posizioni", "candidati"):
            if isinstance(network.get(group), list):
                network[group] = [
                    dict(row, defi={k: v for k, v in row["defi"].items() if k != "acquisito_utc"})
                    for row in network[group]
                ]
    return comparable


def _validated_answer(selected: Dossier, validator: BridgeReader,
                      read_clock: Callable[[], dt.datetime | None], deadline: float,
                      audit: dict) -> dict:
    # The original bridge has both source start times and expiry cutoffs.
    # Compare both ends of a small window and deliver only inside that window.
    # One retry lets a cutoff already crossed during the first pass settle.
    moment = _now(read_clock())
    for _ in range(2):
        _remaining(deadline)
        context = _final_context(selected, validator, moment)
        sources = _base_sources(selected, context)
        state, code = _base_outcome(sources)
        answer = _presentation(state, code, selected, **audit, contesto_kdd=context,
                               fonti_base=sources, evidenze=_analytical_evidence(selected, context),
                               limiti_analitici={
                                   "copertura": "STATI_PER_FONTE_E_POSIZIONE_NEL_CONTESTO_KDD",
                                   "lacune_da_verificare": context.get("lacune_da_verificare", []),
                               })
        finished = _now(read_clock())
        _remaining(deadline)
        if finished < moment:
            raise EvidenceFailure("OROLOGIO_ARRETRATO_DURANTE_VALIDAZIONE")
        if finished == moment:
            answer["validita_controllata_utc"] = finished.isoformat()
            return answer

        horizon = moment + VALIDATION_WINDOW
        if finished <= horizon:
            probe = _final_context(selected, validator, horizon)
            stable = _without_read_clock(context) == _without_read_clock(probe)
            conclusion = _now(read_clock())
            _remaining(deadline)
            if conclusion < finished:
                raise EvidenceFailure("OROLOGIO_ARRETRATO_DURANTE_VALIDAZIONE")
            if stable and conclusion <= horizon:
                answer["validita_controllata_utc"] = conclusion.isoformat()
                return answer
            finished = conclusion
        moment = finished
    raise EvidenceFailure("FRESCHEZZA_FINALE_NON_GARANTITA")


def kdd_get_latest_verified_dossier(reader: DriveReader, folder_id: str, *,
                                   validator: BridgeReader | None = None,
                                   now: dt.datetime | None = None,
                                   clock: Callable[[], dt.datetime] | None = None) -> dict:
    """Recover the current visible Drive candidate without historical fallback.

    The newest dated publication must have both a valid index and matching
    dossier. Drive scans/version checks only detect reported changes.
    A fixed `now` allows deterministic fixture replay; `clock` can advance.
    """
    audit = {}
    try:
        deadline = time.monotonic() + MAX_SECONDS
        if now is not None and clock is not None:
            raise EvidenceFailure("OROLOGIO_LETTURA_AMBIGUO")
        if not isinstance(folder_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", folder_id):
            raise EvidenceFailure("CARTELLA_NON_CONFIGURATA")
        validator = validator if validator is not None else OriginalKddBridge()
        attest = getattr(reader, "attest_candidate", None)
        first, audit = _inventory(reader, folder_id, deadline, attest_current=attest is not None)
        audit.update(numero_file_indicizzazione=len(first), massimo_preparato_utc_verificato=False)
        inventoried = current = _select_candidates(first)
        if attest is not None:
            current, _ = _attest_current(current, attest, deadline)
        stamp, digest, indices, dossiers = current
        candidates = indices + dossiers
        audit.update(criterio_selezione="MASSIMO_PREPARATO_UTC_INDICIZZATO",
                     numero_file_correnti=len(candidates), numero_candidati_correnti=len(dossiers),
                     dossier_fuori_selezione_non_validati=audit["numero_dossier"] - len(dossiers))
        selected, index_sha = _read_current(reader, stamp, digest, indices, dossiers, deadline)
        second, _ = _inventory(reader, folder_id, deadline, attest_current=attest is not None)
        observed = _select_candidates(second)
        if (observed != inventoried
                or (attest is not None and {file["id"]: file for file in first}
                    != {file["id"]: file for file in second})):
            raise EvidenceFailure("INVENTARIO_CAMBIATO_DURANTE_LA_LETTURA")
        if attest is None:
            checked = _check_current_versions(reader, candidates, deadline)
        else:
            observed, evidence = _attest_current(observed, attest, deadline)
            if observed != current:
                raise EvidenceFailure("METADATI_PUNTUALI_CAMBIATI_DURANTE_LA_LETTURA")
            checked = sum(file["version"] is not None or file["headRevisionId"] is not None
                          for file in candidates)
            audit["attestazioni_drive"] = evidence
        audit.update(inventario_stabile_su_due_scansioni=True, numero_controlli_versione=checked,
                     stabilita_versioni_drive=("ATTESTATA_PER_TUTTI_I_CANDIDATI" if checked == len(candidates)
                                              else "PARZIALE" if checked else "NON_ATTESTATA"),
                     atomicita_inventario=False)
        return _validated_answer(selected, validator, clock or (lambda: now), deadline,
                                 dict(audit, massimo_preparato_utc_verificato=True,
                                      nome_indice=indices[0]["name"], sha256_indice=index_sha))
    except (AccessUnavailable, PermissionError):
        return _presentation(ACCESS, "AUTORIZZAZIONE_O_LETTURA_ASSENTE", **audit)
    except EvidenceFailure as exc:
        return _presentation(UNVERIFIABLE, str(exc), **audit)
    except OSError:
        return _presentation(ACCESS, "ACCESSO_FONTE_NON_DISPONIBILE", **audit)
    except Exception:
        return _presentation(UNVERIFIABLE, "ERRORE_NON_CLASSIFICATO", **audit)


class DriveV3ReadOnlyAdapter:
    """Production-shaped Drive REST v3 adapter with *injected* authorized I/O.

    Both callbacks accept timeout and max_bytes keyword arguments and enforce
    them during I/O, before parsing JSON or buffering the complete body.
    Authentication, permissions, retries and networking live outside this class.
    This class never requests an OAuth token or makes requests by itself.
    """
    ROOT = "https://www.googleapis.com/drive/v3/files"

    def __init__(self, folder_id: str,
                 json_get: Callable[..., dict],
                 bytes_get: Callable[..., bytes]):
        self.folder_id = folder_id
        self.json_get = json_get
        self.bytes_get = bytes_get

    def list_page(self, page_token: str | None, *, timeout: float) -> dict:
        escaped = self.folder_id.replace("'", "\\'")
        params = {
            "q": f"'{escaped}' in parents and trashed = false",
            "fields": f"nextPageToken,incompleteSearch,files({FILE_FIELDS})",
            "pageSize": 250,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "user",
        }
        if page_token is not None:
            params["pageToken"] = page_token
        return self.json_get(self.ROOT, params, timeout=timeout, max_bytes=MAX_METADATA_BYTES)

    def file_metadata(self, file_id: str, *, timeout: float) -> dict:
        return self.json_get(self.ROOT + "/" + quote(file_id, safe=""),
                             {"fields": FILE_FIELDS, "supportsAllDrives": "true"},
                             timeout=timeout, max_bytes=MAX_METADATA_BYTES)

    def download(self, file_id: str, *, max_bytes: int, timeout: float) -> bytes:
        return self.bytes_get(self.ROOT + "/" + quote(file_id, safe=""),
                              {"alt": "media", "supportsAllDrives": "true"},
                              timeout=timeout, max_bytes=max_bytes)
