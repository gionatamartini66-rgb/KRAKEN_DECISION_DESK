"""Read successful paginated Drive connector captures and exact local raw downloads.

This module provides a local execution entry point for ChatGPT or an operator
with the connector and a Python checkout available in the same task. It does
not call the connector, authenticate, or write files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import time

from scripts import kdd_gpt_drive_retriever as retriever

DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
POINT_FIELDS = retriever.FILE_FIELDS
FIELD_ALIASES = {
    "id": ("id", "file_id"),
    "name": ("name", "title"),
    "mimeType": ("mimeType", "mime_type"),
    "parents": ("parents", "parent_ids"),
    "size": ("size", "size_bytes"),
    "createdTime": ("createdTime", "created_time"),
    "modifiedTime": ("modifiedTime", "modified_time"),
    "sha256Checksum": ("sha256Checksum", "sha256_checksum"),
    "md5Checksum": ("md5Checksum", "md5_checksum"),
    "trashed": ("trashed",),
    "version": ("version",),
    "headRevisionId": ("headRevisionId", "head_revision_id"),
}


def _id(value: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or not DRIVE_ID.fullmatch(value) or len(value) < minimum:
        raise retriever.EvidenceFailure("IDENTIFICATIVO_CONNETTORE_INVALIDO")
    return value


def _read_local(path: Path, max_bytes: int, missing: str) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise retriever.EvidenceFailure(missing) from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise retriever.EvidenceFailure("FILE_LOCALE_IRREGOLARE_O_TROPPO_GRANDE")
        raw = stream.read(max_bytes + 1)
        if len(raw) != info.st_size:
            raise retriever.EvidenceFailure("FILE_LOCALE_MUTATO")
        return raw


def _read_json(path: Path, max_bytes: int, missing: str) -> dict:
    try:
        value = json.loads(_read_local(path, max_bytes, missing),
                           object_pairs_hook=retriever._strict_object,
                           parse_constant=retriever._reject_constant)
    except (ValueError, RecursionError) as exc:
        raise retriever.EvidenceFailure("CATTURA_CONNETTORE_INVALIDA") from exc
    if not isinstance(value, dict):
        raise retriever.EvidenceFailure("CATTURA_CONNETTORE_INVALIDA")
    return value


def _normalize_metadata(row: dict) -> dict:
    if not isinstance(row, dict):
        raise retriever.EvidenceFailure("METADATI_CONNETTORE_INVALIDI")
    normalized = {}
    for target, aliases in FIELD_ALIASES.items():
        values = [row[name] for name in aliases if name in row]
        if values:
            if any(value != values[0] or type(value) is not type(values[0]) for value in values[1:]):
                raise retriever.EvidenceFailure("METADATI_CONNETTORE_DISCORDANTI")
            normalized[target] = values[0]
    _id(normalized.get("id"))
    # Missing fields stay missing. Predicate evidence is recorded separately.
    return normalized


def _candidate_query(folder_id: str, name: str) -> str:
    # A selected canonical KDD name and the validated folder ID have no quotes.
    return f"'{folder_id}' in parents and trashed = false and name = '{name}'"


def _known_provenance(file: dict, folder_id: str) -> dict:
    result = {}
    parents, trashed = file.get("parents"), file.get("trashed")
    if parents is not None:
        if parents != [folder_id]:
            raise retriever.EvidenceFailure("CARTELLA_ORIGINE_DISCORDE_CONNETTORE")
        result["cartella"] = "METADATI_PROVIDER"
    if trashed is not None:
        if trashed is not False:
            raise retriever.EvidenceFailure("STATO_CESTINO_DISCORDE_CONNETTORE")
        result["cestino"] = "METADATI_PROVIDER"
    return result


class ConnectorCaptureReader:
    """Read two independently captured list_folder_page scans in core order."""

    def __init__(self, folder_id: str, capture: Path):
        self.folder_id = _id(folder_id, minimum=6)
        self.capture = capture
        self.scan = -1
        self.page = 0
        self.pages = []

    def list_page(self, page_token: str | None, *, timeout: float) -> dict:
        if page_token is None:
            self.scan += 1
            self.page = 0
            if self.scan > 1:
                raise retriever.EvidenceFailure("SCANSIONE_CONNETTORE_INATTESA")
            name = ("prima.json", "dopo.json")[self.scan]
            capture = _read_json(self.capture / name,
                                 retriever.MAX_LIST_PAGES * (retriever.MAX_METADATA_BYTES + 1024),
                                 "SCANSIONE_CONNETTORE_ASSENTE")
            self.pages = capture.get("pages")
            if (capture.get("folder_id") != self.folder_id or not isinstance(self.pages, list)
                    or not 1 <= len(self.pages) <= retriever.MAX_LIST_PAGES):
                raise retriever.EvidenceFailure("SCANSIONE_CONNETTORE_INVALIDA")

        if self.page >= len(self.pages):
            raise retriever.EvidenceFailure("PAGINA_CONNETTORE_ASSENTE")
        receipt = self.pages[self.page]
        if (not isinstance(receipt, dict) or "requested_page_token" not in receipt
                or receipt["requested_page_token"] != page_token):
            raise retriever.EvidenceFailure("PAGINA_CONNETTORE_DISCORDE")
        response = receipt.get("response")
        if (not isinstance(response, dict) or not isinstance(response.get("files"), list)
                or response.get("isError") is True or response.get("error") is not None
                or "nextPageToken" in response
                or len(retriever.canonical(response)) > retriever.MAX_METADATA_BYTES):
            raise retriever.EvidenceFailure("RISPOSTA_CONNETTORE_INVALIDA")
        self.page += 1
        next_token = response.get("next_page_token")
        if next_token is None and self.page != len(self.pages):
            raise retriever.EvidenceFailure("PAGINE_CONNETTORE_SOVRANNUMERARIE")
        # list_folder_page reports an incomplete provider search as an error.
        # The capture contract takes only successful result payloads from it.
        for flag in ("incompleteSearch", "incomplete_search"):
            if flag in response and response[flag] is not False:
                raise retriever.EvidenceFailure("INVENTARIO_NON_COMPLETO")
        return {"files": [_normalize_metadata(row) for row in response["files"]],
                "nextPageToken": next_token, "incompleteSearch": False}

    def download(self, file_id: str, *, max_bytes: int, timeout: float) -> bytes:
        return _read_local(self.capture / "blobs" / _id(file_id), max_bytes, "BYTE_CONNETTORE_ASSENTI")

    def attest_candidate(self, file: dict, *, timeout: float) -> tuple[dict, dict]:
        path = self.capture / ("prima-prove", "dopo-prove")[self.scan] / (_id(file["id"]) + ".json")
        receipt = _read_json(path, retriever.MAX_METADATA_BYTES, "PROVE_CANDIDATO_CONNETTORE_ASSENTI")
        point = _normalize_metadata(receipt.get("metadata"))
        if (point["id"], point.get("name")) != (file["id"], file["name"]):
            raise retriever.EvidenceFailure("IDENTITA_METADATI_PUNTUALI_DISCORDE")
        resolved = dict(file)
        for key, value in point.items():
            if value is None:
                continue
            if key == "size" and type(value) is int:
                value = str(value)
            previous = resolved.get(key)
            if key == "size" and type(previous) is int:
                previous = str(previous)
            if previous is not None and (previous != value or type(previous) is not type(value)):
                raise retriever.EvidenceFailure("METADATI_PUNTUALI_DISCORDI_DA_INVENTARIO")
            resolved[key] = value
        evidence = _known_provenance(resolved, self.folder_id)
        if len(evidence) < 2:
            search = receipt.get("search")
            query = _candidate_query(self.folder_id, file["name"])
            if (not isinstance(search, dict) or search.get("query") != query
                    or not isinstance(search.get("results"), list)):
                raise retriever.EvidenceFailure("FILTRO_CANDIDATO_CONNETTORE_NON_DOCUMENTATO")
            exact = [row for row in map(_normalize_metadata, search["results"])
                     if row["id"] == file["id"] and row.get("name") == file["name"]]
            if len(exact) != 1:
                code = ("STATO_CESTINO_NON_ATTESTATO_DAL_CONNETTORE" if "cestino" not in evidence
                        else "CARTELLA_NON_ATTESTATA_DAL_CONNETTORE")
                raise retriever.EvidenceFailure(code)
            # A positive exact-ID result is evidence from the raw q predicate.
            # An empty search never proves anything about the missing candidate.
            _known_provenance(exact[0], self.folder_id)
            for label in ("cartella", "cestino"):
                evidence.setdefault(label, "FILTRO_PROVIDER")
        return resolved, evidence


def plan_downloads(reader: ConnectorCaptureReader, *, needs_evidence: bool = False) -> dict:
    deadline = time.monotonic() + retriever.MAX_SECONDS
    inventory, _ = retriever._inventory(
        reader, reader.folder_id, deadline, attest_current=True)
    selected = retriever._select_candidates(inventory)
    if needs_evidence:
        return {"stato": "PIANO_PROVE", "file": [
            {"id": file["id"], "nome": file["name"], "fields": POINT_FIELDS,
             "query": _candidate_query(reader.folder_id, file["name"])}
            for file in selected[2] + selected[3]
        ]}
    (_, _, indices, dossiers), _ = retriever._attest_current(
        selected, reader.attest_candidate, deadline)
    index_sizes, dossier_sizes = retriever._current_sizes(indices, dossiers)
    return {"stato": "PIANO_DOWNLOAD", "file": [
        {"id": file["id"], "nome": file["name"], "dimensione_byte": size,
         "controllo_versione": file["version"] is not None or file["headRevisionId"] is not None}
        for file, size in zip(indices + dossiers, index_sizes + dossier_sizes)
    ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("select", "plan", "validate"))
    parser.add_argument("folder_id")
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    try:
        reader = ConnectorCaptureReader(args.folder_id, args.capture)
        result = (plan_downloads(reader, needs_evidence=args.action == "select") if args.action != "validate" else
                  retriever.kdd_get_latest_verified_dossier(reader, reader.folder_id))
    except retriever.EvidenceFailure as exc:
        result = retriever._presentation(retriever.UNVERIFIABLE, str(exc))
    except (OSError, ValueError, RecursionError):
        result = retriever._presentation(retriever.ACCESS, "CATTURA_CONNETTORE_NON_LEGGIBILE")
    print(retriever.canonical(result).decode("utf-8"))
    return 0 if result["stato"] in ("PIANO_PROVE", "PIANO_DOWNLOAD", retriever.RECOVERED, retriever.STALE) else 2


if __name__ == "__main__":
    raise SystemExit(main())
