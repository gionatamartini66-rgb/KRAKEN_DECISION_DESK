"""KDD-27 B: durable immutable dossier inputs and produced artifacts.

The private SQLite archive is the ONLY authoritative source for a request
after its first snapshot has been frozen. Local JSON filenames are mutable
compatibility interfaces, not the historical record of a dossier request.
No remote publication, author decision, or GPT analysis occurs here.
"""
from __future__ import annotations
import datetime as dt
import json
import sqlite3
import zlib

from scripts import kdd27_runtime as core

UTC=dt.timezone.utc


class FrozenMismatch(ValueError):
    """A frozen source/artifact differs from the recorded bytes."""


def schema(store):
    with store.connection() as c:
        c.executescript("""
          CREATE TABLE IF NOT EXISTS dossier_freezes(
            request_id TEXT PRIMARY KEY REFERENCES dossier_requests(request_id),
            snapshot_id TEXT NOT NULL UNIQUE, frozen_at TEXT NOT NULL,
            source_observation_id TEXT NOT NULL,
            source_observed_at TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_z BLOB NOT NULL,
            wallet_sha256 TEXT NOT NULL,
            wallet_z BLOB NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            manifest_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS dossier_artifacts(
            dossier_sha256 TEXT PRIMARY KEY, observed_at TEXT NOT NULL,
            snapshot_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            wallet_sha256 TEXT NOT NULL, dossier_z BLOB NOT NULL,
            source_status_json TEXT NOT NULL, built_at TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS dossier_artifacts_by_snapshot
            ON dossier_artifacts(snapshot_id,built_at);
        """)


def _decode(z,digest):
    raw=zlib.decompress(z)
    if core.sha(raw)!=digest:
        raise FrozenMismatch("DIGEST_ARCHIVIO_DISCORDANTE")
    return json.loads(raw)


def get(store, request_id):
    schema(store)
    with store.connection() as c:
        row=c.execute("""SELECT snapshot_id,frozen_at,source_observation_id,
                          source_observed_at,source_sha256,source_z,wallet_sha256,
                          wallet_z,manifest_sha256,manifest_json
                          FROM dossier_freezes WHERE request_id=?""",
                      (request_id,)).fetchone()
        if not row:
            return None
        live=c.execute("SELECT sha256 FROM observations WHERE observation_id=?",
                       (row[2],)).fetchone()
    if not live or live[0]!=row[4]:
        raise FrozenMismatch("OSSERVAZIONE_ORIGINALE_DISCORDANTE")
    try:
        manifest=json.loads(row[9])
    except (ValueError,TypeError) as exc:
        raise FrozenMismatch("MANIFEST_NON_DECODIFICABILE") from exc
    if core.sha(core.encode(manifest))!=row[8]:
        raise FrozenMismatch("MANIFEST_DIGEST_DISCORDANTE")
    reference=core.sha(core.encode({
        "request_id":request_id,"source_id":row[2],"source_sha256":row[4],
        "wallet_sha256":row[6],"manifest_sha256":row[8]}))
    if reference!=row[0]:
        raise FrozenMismatch("SNAPSHOT_ID_DISCORDANTE")
    return {"snapshot_id":row[0],"frozen_at":row[1],
            "source_observation_id":row[2],"source_observed_at":row[3],
            "source_sha256":row[4], "source":_decode(row[5],row[4]),
            "wallet_sha256":row[6],"wallet":_decode(row[7],row[6]),
            "manifest_sha256":row[8], "manifest":manifest}


def _manifest(c, now):
    from scripts.kdd27_families import SPECS, stamped
    observations=[]
    for family,spec in SPECS.items():
        row=c.execute("""SELECT observation_id,sha256,observed_at,state
                         FROM observations WHERE family=?
                         ORDER BY observed_at DESC,received_at DESC LIMIT 1""",
                      (family,)).fetchone()
        if row is None:
            observations.append({"family":family,"stato":"NON_ACQUISITO",
                                 "observation_id":None,"sha256":None,
                                 "osservato_utc":None,"eta_s":None,
                                 "ttl_s":spec["ttl_s"]})
            continue
        observed=stamped(row[2])
        age=(now-observed).total_seconds() if observed else None
        valid=(row[3]=="OSSERVATO" and age is not None
               and -120<=age<=spec["ttl_s"])
        observations.append({"family":family,
                             "stato":"RECENTE" if valid else "SCADUTO"
                                if row[3]=="OSSERVATO" else row[3],
                             "observation_id":row[0],"sha256":row[1],
                             "osservato_utc":row[2],"eta_s":age,
                             "ttl_s":spec["ttl_s"]})
    return {"schema":"kdd27_frozen_manifest_v001",
            "produced_at":core.iso(now),"families":observations,
            "missing":sorted(row["family"] for row in observations
                             if row["stato"]!="RECENTE")}


def freeze(store, request_id, *, now, source, source_observation_id, wallet):
    """Immutable single-transaction bind of exact source, wallet and family IDs.

    Caller holds process-level KDD27 exclusion lock. A repeated request
    retrieves its original binding; no replacement or silent re-freeze.
    """
    schema(store)
    old=get(store,request_id)
    if old is not None:
        return old
    if not isinstance(source,dict) or not isinstance(wallet,dict):
        raise ValueError("Dossier source/wallet not JSON objects")
    observed=source.get("rilevazione_utc")
    source_clock=dt.datetime.fromisoformat(observed)
    if source_clock.tzinfo is None or not -120<=(
            now-source_clock.astimezone(UTC)).total_seconds()<=core.SNAPSHOT_MAX_AGE_SECONDS:
        raise ValueError("DOSSIER_SNAPSHOT_SCADUTO")
    raw=core.encode(source)
    wallet_raw=core.encode(wallet)
    source_sha=core.sha(raw)
    wallet_sha=core.sha(wallet_raw)
    with store.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        exists=c.execute("SELECT request_id FROM dossier_freezes WHERE request_id=?",
                         (request_id,)).fetchone()
        if exists:
            c.commit()
            return get(store,request_id)
        original=c.execute("SELECT sha256,state FROM observations"
                           " WHERE observation_id=?",
                           (source_observation_id,)).fetchone()
        if not original or original[0]!=source_sha or original[1]!="OSSERVATO":
            c.rollback()
            raise FrozenMismatch("SORGENTE_SQLITE_NON_VERIFICATA")
        manifest=_manifest(c,now)
        man_sha=core.sha(core.encode(manifest))
        snapshot_id=core.sha(core.encode({
            "request_id":request_id,"source_id":source_observation_id,
            "source_sha256":source_sha,"wallet_sha256":wallet_sha,
            "manifest_sha256":man_sha}))
        c.execute("""INSERT INTO dossier_freezes VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (request_id,snapshot_id,core.iso(now),source_observation_id,
                   observed,source_sha,sqlite3.Binary(zlib.compress(raw)),
                   wallet_sha,sqlite3.Binary(zlib.compress(wallet_raw)),
                   man_sha,core.encode(manifest).decode()))
        c.commit()
    return get(store,request_id)


def persist_artifact(store, frozen, dossier, status, *, observed_at=None):
    """Preserve source+wallet-bound output, even with missing external feeds."""
    schema(store)
    if dossier.get("kraken_istantanea_utc") != frozen["source_observed_at"]:
        raise FrozenMismatch("DOSSIER_SORGENTE_DISCORDANTE")
    wallet_sha=dossier.get("fotografia_portafoglio_sha256")
    if wallet_sha != frozen["wallet_sha256"]:
        raise FrozenMismatch("DOSSIER_WALLET_DISCORDANTE")
    raw=core.encode(dossier)
    sha=core.sha(raw)
    original_status=core.encode(status).decode()
    with store.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        exists=c.execute("SELECT source_sha256,wallet_sha256,snapshot_id"
                         " FROM dossier_artifacts WHERE dossier_sha256=?",
                         (sha,)).fetchone()
        if exists and (exists[0]!=frozen["source_sha256"]
                       or exists[1]!=frozen["wallet_sha256"]):
            c.rollback()
            raise FrozenMismatch("COLLISIONE_ARTEFATTO")
        if not exists:
            c.execute("INSERT INTO dossier_artifacts VALUES(?,?,?,?,?,?,?,?)",
                      (sha,observed_at or core.iso(),frozen["snapshot_id"],
                       frozen["source_sha256"],frozen["wallet_sha256"],
                       sqlite3.Binary(zlib.compress(raw)),original_status,core.iso()))
        c.commit()
    return sha


def recent_artifact(store, frozen, now, max_age_s):
    """Return immutable output only for EXACT same frozen market and wallet."""
    schema(store)
    with store.connection() as c:
        row=c.execute("""SELECT dossier_sha256,dossier_z,source_status_json,built_at
                         FROM dossier_artifacts WHERE source_sha256=?
                         AND wallet_sha256=? ORDER BY built_at DESC LIMIT 1""",
                      (frozen["source_sha256"],frozen["wallet_sha256"])).fetchone()
    if not row:
        return None
    built=dt.datetime.fromisoformat(row[3])
    age=(now-built).total_seconds()
    if not 0<=age<=max_age_s:
        return None
    return {"dossier_sha":row[0],"dossier":_decode(row[1],row[0]),
            "status":json.loads(row[2]),"built_at":row[3]}


def family_inputs(store, frozen, now):
    """Data manifest is immutable even if jobs continue collecting new samples."""
    by_family={r["family"]:r for r in frozen["manifest"]["families"]}
    result={}
    with store.connection() as c:
        for family,row in by_family.items():
            if row["stato"]!="RECENTE" or not row.get("observation_id"):
                result[family]={"stato":row["stato"],"osservazione":None}
                continue
            obs=c.execute("SELECT sha256,payload_z FROM observations"
                          " WHERE observation_id=?", (row["observation_id"],)).fetchone()
            if not obs or obs[0]!=row["sha256"]:
                raise FrozenMismatch("FAMILY_SOURCE_MUTATED:"+family)
            result[family]={"stato":"RECENTE",
                            "osservazione":_decode(obs[1],obs[0]),
                            "observation_id":row["observation_id"],
                            "sha256":row["sha256"]}
    return result
