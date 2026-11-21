"""KDD V001 Drive publication names and minimal index, shared by writer and reader."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

SCHEMA = "kdd_drive_index_v001"
MAX_INDEX_BYTES = 2048
MAX_DOSSIER_BYTES = 8_000_000  # Original bridge limit
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LEGACY = re.compile(r"kdd_handoff_[0-9a-f]{64}\.json\Z")
DOSSIER_PREFIX = "kdd_handoff_v001_"
INDEX_PREFIX = "kdd_handoff_index_v001_"
SUFFIX = r"([0-9]{8}T[0-9]{12}Z)_([0-9a-f]{64})\.json\Z"
DOSSIER = re.compile(DOSSIER_PREFIX + SUFFIX)
INDEX = re.compile(INDEX_PREFIX + SUFFIX)
INDEX_FIELDS = frozenset(("schema", "dossier", "dossier_sha256", "preparato_utc",
                          "snapshot_utc", "snapshot_id", "sha256_byte", "dimensione_byte"))


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def utc(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamp KDD assente")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp KDD senza fuso")
    return parsed.astimezone(dt.timezone.utc)


def names(stamp: str, digest: str) -> tuple[str, str]:
    suffix = f"{stamp}_{digest}.json"
    return DOSSIER_PREFIX + suffix, INDEX_PREFIX + suffix


def prepared_from_stamp(stamp: str) -> str:
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
    clock = f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}.{stamp[15:21]}"
    return utc(f"{date}T{clock}Z").isoformat(timespec="microseconds")


def publication(bundle: dict, raw: bytes) -> tuple[str, str, dict]:
    digest = hashlib.sha256(raw[:-1]).hexdigest()
    prepared = utc(bundle["preparato_utc"])
    stamp = f"{prepared.year:04d}{prepared:%m%dT%H%M%S%f}Z"
    dossier, index = names(stamp, digest)
    snapshot = utc(bundle["packet"]["rilevazione_kdd_utc"])
    return dossier, index, {
        "schema": SCHEMA, "dossier": dossier, "dossier_sha256": digest,
        "preparato_utc": prepared.isoformat(timespec="microseconds"),
        "snapshot_utc": snapshot.isoformat(timespec="microseconds"),
        "snapshot_id": bundle["packet_sha256"], "sha256_byte": hashlib.sha256(raw).hexdigest(),
        "dimensione_byte": len(raw),
    }


def check_index(index: dict, stamp: str, digest: str) -> None:
    dossier, _ = names(stamp, digest)
    if (set(index) != INDEX_FIELDS or index["schema"] != SCHEMA
            or index["dossier"] != dossier or index["dossier_sha256"] != digest
            or index["preparato_utc"] != prepared_from_stamp(stamp)
            or any(not isinstance(index[key], str) or not SHA256.fullmatch(index[key])
                   for key in ("snapshot_id", "sha256_byte"))
            or type(index["dimensione_byte"]) is not int
            or not 2 <= index["dimensione_byte"] <= MAX_DOSSIER_BYTES):
        raise ValueError("Indice KDD incoerente")
    if utc(index["snapshot_utc"]).isoformat(timespec="microseconds") != index["snapshot_utc"]:
        raise ValueError("Timestamp fotografia non canonico")
