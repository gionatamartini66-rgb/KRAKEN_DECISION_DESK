"""KDD-27: durable experimental scheduler, source observations and dossier queue.

No job is installed or enabled by importing this module. All data stays local:
no private source or balance is transmitted to GitHub. Python stdlib only.
The original producers, packet and Drive bridge remain authoritative.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import zlib

UTC = dt.timezone.utc
SCHEMA = 1
# Experimental configurations only; no automatic enrollment or Android job.
PROFILES = {"A": 7200, "B": 3600}
MONITOR_JOB = "legacy_public_and_wallet_refresh"
MAX_BATCH = 40  # Work per invocation, NEVER an admission or daily dossier cap.


class BudgetDeferred(RuntimeError):
    """A source refresh is deferred, never reported as current."""
CACHE_SECONDS = 300
SNAPSHOT_MAX_AGE_SECONDS = 600


def instant(value=None):
    if value is None:
        return dt.datetime.now(UTC)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, UTC)
    if isinstance(value, dt.datetime) and value.tzinfo:
        return value.astimezone(UTC)
    raise ValueError("Aware UTC timestamp required")


def iso(value=None):
    return instant(value).isoformat(timespec="microseconds")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def private_root():
    # Exact app-local destination, never the FolderSync export directory.
    return Path(__file__).resolve().parents[1] / ".kdd27_private"


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else private_root()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = self.root / "monitor.sqlite3"
        self.lock_path = self.root / "runner.lock"
        with self.connection() as conn:
            conn.executescript("""
              CREATE TABLE IF NOT EXISTS jobs(
                name TEXT PRIMARY KEY, interval_s INTEGER NOT NULL CHECK(interval_s >= 60),
                epoch_s INTEGER NOT NULL, next_due_s INTEGER NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                profile TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS runs(
                run_id TEXT PRIMARY KEY, name TEXT NOT NULL, due_s INTEGER NOT NULL,
                start_s REAL NOT NULL, finish_s REAL, status TEXT NOT NULL,
                missed INTEGER NOT NULL DEFAULT 0, error TEXT,
                metrics_json TEXT, snapshot_sha TEXT);
              CREATE INDEX IF NOT EXISTS runs_name_due ON runs(name,due_s);
              CREATE TABLE IF NOT EXISTS gaps(
                run_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                start_s INTEGER NOT NULL, end_s INTEGER NOT NULL, count INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS observations(
                observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, family TEXT NOT NULL,
                observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
                sha256 TEXT NOT NULL, payload_z BLOB NOT NULL,
                payload_bytes INTEGER NOT NULL, state TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS observations_time
                ON observations(family,observed_at);
              CREATE TABLE IF NOT EXISTS cursors(
                family TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS dossier_requests(
                request_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT, completed_at TEXT,
                snapshot_sha TEXT, snapshot_time TEXT, dossier_sha TEXT,
                handoff_file TEXT, source_run_id TEXT,
                reused_from TEXT, error TEXT, metrics_json TEXT);
              CREATE INDEX IF NOT EXISTS dossier_pending
                ON dossier_requests(status,requested_at);
            """)
        with self.connection() as c:
            columns={row[1] for row in c.execute("PRAGMA table_info(dossier_requests)")}
            for name in ("snapshot_id","manifest_sha","source_observation_id",
                         "publication_state","quality_json","next_attempt_at"):
                if name not in columns:
                    c.execute("ALTER TABLE dossier_requests ADD COLUMN "+name+" TEXT")
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA foreign_keys=ON")
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def exclusive(self, nonblocking=False):
        with open(self.lock_path, "a+b") as f:
            os.chmod(self.lock_path, 0o600)
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX |
                            (fcntl.LOCK_NB if nonblocking else 0))
            except BlockingIOError:
                raise RuntimeError("KDD27_BUSY") from None
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def setup_families(self, profile, now, *, enable=False):
        """Experimental per-source schedules; no Android enrollment.

        The caller must explicitly enable the local schedules; imports and
        status requests never create jobs or infer author approval of rates.
        """
        from scripts.kdd27_families import SPECS
        if profile not in PROFILES:
            raise ValueError("Unknown experimental profile")
        timestamp=int(instant(now).timestamp())
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            for name,spec in SPECS.items():
                period=spec["intervals"][profile]
                epoch=timestamp-timestamp%period
                old=c.execute("SELECT name FROM jobs WHERE name=?",(name,)).fetchone()
                if old is not None:
                    c.rollback()
                    raise ValueError("Existing family schedule: "+name)
                c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                         (name,period,epoch,epoch+period,int(enable),profile))
            c.commit()

    def family_coverage(self, now=None):
        from scripts.kdd27_families import SPECS, stamped
        moment=instant(now)
        report={}
        with self.connection() as c:
            for name,spec in SPECS.items():
                row=c.execute("SELECT observed_at,state FROM observations"
                              " WHERE family=? ORDER BY observed_at DESC LIMIT 1",
                              (name,)).fetchone()
                job=c.execute("SELECT interval_s,next_due_s,enabled FROM jobs"
                              " WHERE name=?",(name,)).fetchone()
                observed=stamped(row[0]) if row else None
                age=(moment-observed).total_seconds() if observed else None
                state=("NON_ACQUISITO" if row is None or row[1]!="OSSERVATO"
                       else "FUTURO" if age < -120
                       else "SCADUTO" if age > spec["ttl_s"]
                       else "RECENTE")
                report[name]={"stato":state,
                              "ttl_s":spec["ttl_s"],
                              "eta_s":age,
                              "osservato_utc":row[0] if row else None,
                              "periodo_s":job[0] if job else None,
                              "prossima_scadenza_s":job[1] if job else None,
                              "attivo":bool(job[2]) if job else False,
                              "limite_chiamate_produttore":spec["producer_budget_calls"],
                              "budget_provider_attestato":False}
        return report

    def setup(self, profile, now, *, enable=False):
        if profile not in PROFILES:
            raise ValueError("Unknown experimental profile")
        period = PROFILES[profile]
        stamp = int(instant(now).timestamp())
        epoch = stamp - (stamp % period)
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            previous = c.execute("SELECT name FROM jobs WHERE name=?", (MONITOR_JOB,)).fetchone()
            if previous:
                # No silent migration from an enrolled timetable.
                c.rollback()
                raise ValueError("Existing schedule; explicit reset needed")
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                      (MONITOR_JOB, period, epoch, epoch + period, int(enable), profile))
            c.commit()

    def status(self):
        with self.connection() as c:
            jobs = c.execute("SELECT name,interval_s,next_due_s,enabled,profile FROM jobs").fetchall()
            pending = c.execute("SELECT status,COUNT(*) FROM dossier_requests GROUP BY status").fetchall()
            n = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            return {"jobs": jobs, "dossiers": dict(pending), "observations": n}

    def _recover(self, c):
        # Caller MUST hold exclusive file lock: no live sibling process can own a run.
        c.execute("UPDATE runs SET status='INTERROTTO', error='PROCESSO_INTERROTTO',"
                  " finish_s=start_s WHERE status='IN_CORSO'")
        c.execute("UPDATE dossier_requests SET status='IN_ATTESA',"
                  " error='RIPRESA_DOPO_INTERRUZIONE' WHERE status='IN_CORSO'")

    def run_due(self, worker, now=None):
        """Execute only latest elapsed slot; record skipped nominal windows."""
        timestamp = int(instant(now).timestamp())
        with self.exclusive(nonblocking=True):
            with self.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                self._recover(c)
                rows = c.execute("SELECT name,interval_s,next_due_s FROM jobs"
                                 " WHERE enabled=1 AND next_due_s<=?",
                                 (timestamp,)).fetchall()
                entries = []
                for name, period, next_due in rows:
                    missed = (timestamp - next_due) // period
                    due = next_due + missed * period
                    run_id = uuid.uuid4().hex
                    c.execute("INSERT INTO runs(run_id,name,due_s,start_s,status,missed)"
                              " VALUES(?,?,?,?,?,?)",
                              (run_id, name, due, time.time(), "IN_CORSO", missed))
                    if missed:
                        c.execute("INSERT INTO gaps VALUES(?,?,?,?,?)",
                                  (run_id, name, next_due, due - period, missed))
                    c.execute("UPDATE jobs SET next_due_s=? WHERE name=?",
                              (due + period, name))
                    entries.append((run_id, name, due, missed))
                c.commit()
            results = []
            for run_id, name, due, missed in entries:
                try:
                    measurement = worker(name, run_id, due)
                    if not isinstance(measurement, dict) or "payload" not in measurement:
                        raise ValueError("Worker must return payload")
                    payload = measurement["payload"]
                    serialized = encode(payload)
                    digest = sha(serialized)
                    measured_at = measurement.get("observed_at") or iso()
                    metrics = measurement.get("metrics") or {}
                    cursor = measurement.get("cursor")
                    state = measurement.get("state", "OSSERVATO")
                    if state not in ("OSSERVATO","NON_ACQUISITO","NON_DISPONIBILE",
                                     "RINVIATO_BUDGET"):
                        raise ValueError("Invalid producer observation state")
                    observation_id = sha(encode([run_id, name, measured_at, digest]))
                    with self.connection() as c:
                        c.execute("BEGIN IMMEDIATE")
                        c.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                                  (observation_id, run_id, name, measured_at, iso(),
                                   digest, sqlite3.Binary(zlib.compress(serialized)),
                                   len(serialized), state))
                        if cursor is not None:
                            c.execute("INSERT INTO cursors VALUES(?,?,?)"
                                      " ON CONFLICT(family) DO UPDATE SET "
                                      "data_json=excluded.data_json,updated_at=excluded.updated_at",
                                      (name, encode(cursor).decode(), iso()))
                        c.execute("UPDATE runs SET status=?,finish_s=?,"
                                  "metrics_json=?,snapshot_sha=? WHERE run_id=?",
                                  ("RIUSCITO" if state=="OSSERVATO" else state,
                                   time.time(), encode(metrics).decode(), digest, run_id))
                        c.commit()
                    results.append({"run_id": run_id,
                                    "status": "RIUSCITO" if state=="OSSERVATO" else state,
                                    "missed": missed,"family":name,"sha256": digest})
                except Exception as exc:
                    with self.connection() as c:
                        c.execute("UPDATE runs SET status='ERRORE',finish_s=?,error=?"
                                  " WHERE run_id=?", (time.time(), type(exc).__name__, run_id))
                    results.append({"run_id": run_id, "status": "ERRORE",
                                    "error": type(exc).__name__, "missed": missed})
            return results

    def run_manual_monitor(self, worker, now=None):
        """An explicit desk refresh is also archived, without shifting A deadlines."""
        moment = instant(now)
        run_id = uuid.uuid4().hex
        with self.exclusive():
            with self.connection() as c:
                c.execute("INSERT INTO runs(run_id,name,due_s,start_s,status)"
                          " VALUES(?,?,?,?,?)", (run_id,MONITOR_JOB,
                            int(moment.timestamp()),time.time(),"IN_CORSO"))
            try:
                produced=worker(MONITOR_JOB,run_id,int(moment.timestamp()))
                raw=encode(produced["payload"])
                digest=sha(raw)
                observed=produced.get("observed_at") or iso()
                with self.connection() as c:
                    c.execute("BEGIN IMMEDIATE")
                    c.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                              (sha(encode([run_id,MONITOR_JOB,observed,digest])),run_id,
                               MONITOR_JOB,observed,iso(),digest,
                               sqlite3.Binary(zlib.compress(raw)),len(raw),"OSSERVATO"))
                    if produced.get("cursor") is not None:
                        c.execute("INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(family)"
                                  " DO UPDATE SET data_json=excluded.data_json,"
                                  "updated_at=excluded.updated_at",
                                  (MONITOR_JOB,encode(produced["cursor"]).decode(),iso()))
                    c.execute("UPDATE runs SET status='MANUALE',finish_s=?,"
                              "metrics_json=?,snapshot_sha=? WHERE run_id=?",
                              (time.time(),encode(produced.get("metrics") or {}).decode(),
                               digest,run_id))
                    c.commit()
                return {"run_id":run_id,"snapshot_sha":digest,
                        "observed_at":observed,"status":"MANUALE"}
            except BaseException as exc:
                with self.connection() as c:
                    c.execute("UPDATE runs SET status='ERRORE',finish_s=?,error=?"
                              " WHERE run_id=?",
                              (time.time(),type(exc).__name__,run_id))
                raise

    def record_dossier_snapshot(self, request_id, snapshot, observed_at):
        """Append an independently acquired B snapshot, never alter A calendar."""
        raw = encode(snapshot)
        digest = sha(raw)
        observed = dt.datetime.fromisoformat(observed_at)
        if observed.tzinfo is None or observed > instant()+dt.timedelta(minutes=2):
            raise ValueError("Invalid dossier snapshot time")
        uid = sha(encode(['DOSSIER_FRESHNESS', observed_at, digest]))
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                      (uid, request_id, 'DOSSIER_FRESHNESS', observed_at, iso(),
                       digest, sqlite3.Binary(zlib.compress(raw)),len(raw),'OSSERVATO'))
            c.commit()
        return {'sha256':digest,'observation_id':uid}

    def latest(self, family=MONITOR_JOB):
        with self.connection() as c:
            row = c.execute("SELECT run_id,observed_at,sha256,payload_z,"
                            "observation_id,state,received_at"
                            " FROM observations WHERE family=?"
                            " ORDER BY observed_at DESC LIMIT 1", (family,)).fetchone()
        if not row:
            return None
        raw = zlib.decompress(row[3])
        if sha(raw) != row[2]:
            raise ValueError("CORRUZIONE_OSSERVAZIONE")
        return {"run_id": row[0], "observed_at": row[1],
                "sha256": row[2], "payload": json.loads(raw),
                "observation_id":row[4],"state":row[5],
                "received_at":row[6]}

    def enqueue_dossier(self, request_id=None, now=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
            raise ValueError("Invalid request id")
        timestamp = iso(now)
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT status FROM dossier_requests WHERE request_id=?",
                            (request_id,)).fetchone()
            if row:
                c.commit()
                return {"request_id": request_id, "status": row[0], "reused_id": True}
            c.execute("INSERT INTO dossier_requests(request_id,requested_at,status)"
                      " VALUES(?,?,'IN_ATTESA')", (request_id,timestamp))
            c.commit()
        return {"request_id": request_id, "status": "IN_ATTESA", "reused_id": False}

    def dossier_status(self, request_id=None, limit=20):
        with self.connection() as c:
            if request_id:
                rows = c.execute("SELECT * FROM dossier_requests WHERE request_id=?",
                                 (request_id,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM dossier_requests ORDER BY requested_at DESC"
                                 " LIMIT ?", (limit,)).fetchall()
            keys = [item[1] for item in c.execute("PRAGMA table_info(dossier_requests)")]
        return [dict(zip(keys, row)) for row in rows]

    def process_queue(self, producer, now=None, limit=MAX_BATCH, *, wait=False):
        """Serialize dossier runs with monitor runs, without modifying job dates."""
        results = []
        with self.exclusive(nonblocking=not wait):
            with self.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                self._recover(c)
                # Recover provider-delayed requests only when their recorded
                # retry clock has elapsed, without changing the original id.
                c.execute("UPDATE dossier_requests SET status='IN_ATTESA'"
                          " WHERE status IN ('RINVIATO_PROVIDER','RINVIATO_RETE')"
                          " AND next_attempt_at IS NOT NULL AND next_attempt_at<=?",
                          (iso(instant(now)),))
                c.commit()
            for _ in range(limit):
                with self.connection() as c:
                    c.execute("BEGIN IMMEDIATE")
                    row = c.execute("SELECT request_id FROM dossier_requests WHERE"
                                    " status='IN_ATTESA' ORDER BY requested_at LIMIT 1").fetchone()
                    if row is None:
                        c.commit()
                        break
                    request_id = row[0]
                    c.execute("UPDATE dossier_requests SET status='IN_CORSO',started_at=?,"
                              "error=NULL WHERE request_id=?", (iso(), request_id))
                    c.commit()
                try:
                    produced = producer(self, request_id, instant(now))
                    if not isinstance(produced, dict):
                        raise ValueError("Invalid dossier producer result")
                    required = ("snapshot_sha","snapshot_time","snapshot_id",
                                "manifest_sha","dossier_sha","source_observation_id")
                    if any(not produced.get(k) for k in required):
                        raise ValueError("Incomplete dossier provenance")
                    with self.connection() as c:
                        state=produced.get("dossier_status","PARZIALE_LOCALE")
                        if state not in ("PRONTO_LOCALE","PARZIALE_LOCALE"):
                            raise ValueError("Invalid dossier completion state")
                        c.execute("UPDATE dossier_requests SET status=?,completed_at=?,"
                                  "snapshot_sha=?,snapshot_time=?,dossier_sha=?,handoff_file=?,"
                                  "source_run_id=?,reused_from=?,metrics_json=?,snapshot_id=?,"
                                  "manifest_sha=?,source_observation_id=?,publication_state=?,"
                                  "quality_json=? WHERE request_id=?",
                                  (state,iso(),produced["snapshot_sha"],
                                   produced["snapshot_time"],produced["dossier_sha"],
                                   produced.get("handoff_file"),produced.get("source_run_id"),
                                   produced.get("reused_from"),
                                   encode(produced.get("metrics") or {}).decode(),
                                   produced["snapshot_id"],produced["manifest_sha"],
                                   produced["source_observation_id"],
                                   produced.get("publication_state","NON_PREPARATO"),
                                   encode(produced.get("quality") or {}).decode(),request_id))
                    results.append((request_id,state))
                except Exception as exc:
                    state = ('RINVIATO_PROVIDER' if isinstance(exc,BudgetDeferred)
                             else 'RINVIATO_RETE' if isinstance(exc, (OSError,ConnectionError))
                             else 'ERRORE')
                    due=(instant(now)+dt.timedelta(minutes=5)).isoformat() if (
                        state.startswith("RINVIATO_")) else None
                    with self.connection() as c:
                        c.execute("UPDATE dossier_requests SET status=?,"
                                  "completed_at=?,error=?,next_attempt_at=?"
                                  " WHERE request_id=?",
                                  (state,iso(),type(exc).__name__,due,request_id))
                    results.append((request_id,state))
        return results


def real_family_worker(store, name, run_id, due):
    """Execute ONE existing source producer in its own due window."""
    from scripts import kdd27_families as families
    from scripts.kdd27_telemetry import Telemetry
    with Telemetry() as meter:
        result=families.collect(store,name)
    measured=meter.report()
    measured.update(result.get("metrics") or {})
    return {"payload":result["payload"],
            "observed_at":result.get("observed_at") or iso(),
            "state":result.get("state","OSSERVATO"),
            "cursor":result.get("cursor"),"metrics":measured}


def real_monitor_worker(name, run_id, due):
    """Run original market/scanner producers without the full dossier/packet."""
    if name != MONITOR_JOB:
        raise ValueError("Unexpected job")
    import decision_desk as desk
    from scripts.kdd27_telemetry import Telemetry
    with Telemetry() as meter:
        data = desk.refresh(prepare_dossier=False)
    payload = {
        "schema": "kdd27_monitor_observation_v001",
        "monitor_run_id": run_id, "scheduled_utc": iso(due),
        "snapshot": data, "wallet_sha256": desk.fotografia_portafoglio_sha256(
            desk.load("portafoglio.json", {})),
        "dossier_prodotto": False,
        "stato": "RILEVAZIONE_COMPLETA_DEL_CORE"
    }
    return {"payload": payload, "observed_at": data["rilevazione_utc"],
            "cursor": data.get("ricerca_setup", {}),
            "metrics": dict(meter.report(),
                        scope="CORE_LEGACY_SENZA_DOSSIER",
                        scanner_requests=(data.get("ricerca_setup") or {})
                          .get("richieste_ohlc_1h"))}


def real_dossier_producer(store, request_id, now):
    """Use immutable historical snapshot; never replace it on retry."""
    from scripts.kdd27_telemetry import Telemetry
    with Telemetry() as meter:
        outcome=_real_dossier_producer(store,request_id,instant(now))
    outcome["metrics"]=meter.report()
    return outcome


def _real_dossier_producer(store, request_id, now):
    import decision_desk as desk
    from scripts import kdd_drive_exchange as exchange
    from scripts import kdd27_freeze as frozen_archive

    frozen=frozen_archive.get(store,request_id)
    if frozen is None:
        wallet=desk.load("portafoglio.json",{})
        wallet_digest=desk.fotografia_portafoglio_sha256(wallet)
        monitor=store.latest()
        cached=store.latest("DOSSIER_FRESHNESS")
        chosen=None
        if monitor and monitor.get("state")=="OSSERVATO":
            source=(monitor.get("payload") or {}).get("snapshot")
            observed=(source or {}).get("rilevazione_utc") if isinstance(source,dict) else None
            if isinstance(source,dict) and monitor["payload"].get("wallet_sha256")==wallet_digest:
                try:
                    age=(now-dt.datetime.fromisoformat(observed)).total_seconds()
                    if 0<=age<=SNAPSHOT_MAX_AGE_SECONDS:
                        chosen=source
                except (ValueError,TypeError,OverflowError):
                    pass
        if chosen is None and cached and cached.get("state")=="OSSERVATO":
            source=cached.get("payload")
            observed=source.get("rilevazione_utc") if isinstance(source,dict) else None
            try:
                age=(now-dt.datetime.fromisoformat(observed)).total_seconds()
                # Reuse only if its source AND wallet were actually frozen together.
                with store.connection() as c:
                    proof=c.execute("SELECT 1 FROM dossier_freezes WHERE"
                         " source_sha256=? AND wallet_sha256=? LIMIT 1",
                         (sha(encode(source)),wallet_digest)).fetchone()
                if 0<=age<=SNAPSHOT_MAX_AGE_SECONDS and proof:
                    chosen=source
            except (ValueError,TypeError,OverflowError):
                pass
        if chosen is None:
            chosen=desk.refresh(prepare_dossier=False)
            # Wallet may have changed during the refresh; save only the
            # post-refresh exact private image, never silently use an older one.
            wallet=desk.load("portafoglio.json",{})
            wallet_digest=desk.fotografia_portafoglio_sha256(wallet)
        if not isinstance(chosen,dict) or not chosen.get("rilevazione_utc"):
            raise ValueError("MERCATO_NON_DISPONIBILE")
        record=store.record_dossier_snapshot(request_id,chosen,chosen["rilevazione_utc"])
        frozen=frozen_archive.freeze(
            store,request_id,now=now,source=chosen,
            source_observation_id=record["observation_id"],wallet=wallet)

    # All subsequent operations consume THIS exact archived market and wallet,
    # even after the local JSON, roster, scanner or later family samples change.
    snapshot=frozen["source"]
    portfolio=frozen["wallet"]
    snapshot_sha=frozen["source_sha256"]
    wallet_sha=frozen["wallet_sha256"]
    instant_source=dt.datetime.fromisoformat(frozen["source_observed_at"])
    age=(now-instant_source).total_seconds()
    if not -120<=age<=3600:
        # Frozen means frozen: a missed retry cannot silently become today's
        # snapshot. Make the stale request explicit, retain its immutable ID.
        raise ValueError("FOTOGRAFIA_CONGELATA_SCADUTA")

    # Consume only immutable, TTL-checked family observations selected when
    # this request was frozen. Later scheduler activity cannot change inputs.
    inputs=frozen_archive.family_inputs(store,frozen,now)
    catalog=inputs.get("market_catalog") or {}
    asset_pairs=((catalog.get("osservazione") or {}).get("pairs")
                 if catalog.get("stato")=="RECENTE" else None)
    previous_dossier={}
    economic=inputs.get("fundamentals") or {}
    network=inputs.get("network_defi") or {}
    used_ids=[frozen["source_observation_id"]]
    if catalog.get("stato")=="RECENTE":
        used_ids.append(catalog["observation_id"])
    if economic.get("stato")=="RECENTE":
        previous_dossier["evidenze_economiche"]=economic["osservazione"]
        used_ids.append(economic["observation_id"])
    if network.get("stato")=="RECENTE":
        previous_dossier["evidenze_rete_defi"]=network["osservazione"]
        used_ids.append(network["observation_id"])
    cached_artifact=frozen_archive.recent_artifact(store,frozen,now,CACHE_SECONDS)
    reused_from=None
    if cached_artifact:
        dossier=cached_artifact["dossier"]
        quality=cached_artifact["status"]
        with store.connection() as c:
            old=c.execute("SELECT request_id FROM dossier_requests WHERE"
                          " dossier_sha=? AND status IN"
                          " ('PRONTO_LOCALE','PARZIALE_LOCALE')"
                          " ORDER BY completed_at DESC LIMIT 1",
                          (cached_artifact["dossier_sha"],)).fetchone()
        reused_from=old[0] if old else None
        dossier_digest=cached_artifact["dossier_sha"]
    else:
        options={"wallet_override":portfolio,
                 "previous_dossier_override":previous_dossier}
        if asset_pairs is not None:
            options["asset_pairs"]=asset_pairs
        quality=desk.prepara_dossier_aggiornamento(snapshot,**options)
        quality=dict(quality or {})
        quality["observations_consumed"]=used_ids
        quality["snapshot_id"]=frozen["snapshot_id"]
        dossier=desk.load("dossier_multifonte.json",{})
        if not isinstance(dossier,dict) or not dossier.get("kraken_istantanea_utc"):
            raise ValueError("DOSSIER_NON_PRODOTTO")
        dossier_digest=frozen_archive.persist_artifact(store,frozen,dossier,quality)

    completeness=(quality.get("stato_fonti_mercato")
                  if isinstance(quality,dict) else "NON_VERIFICABILE")
    eligible=(quality.get("idoneita_analisi_patrimoniale")
              if isinstance(quality,dict) else "NON_IDONEA")
    state=quality.get("stato") if isinstance(quality,dict) else "NON_DISPONIBILE"
    if state=="NON_DISPONIBILE":
        raise ValueError("DOSSIER_NON_DISPONIBILE")
    if dossier.get("fotografia_portafoglio_sha256")!=wallet_sha:
        raise ValueError("DOSSIER_DIVERGE_DA_WALLET_CONGELATO")
    if dossier.get("kraken_istantanea_utc")!=frozen["source_observed_at"]:
        raise ValueError("DOSSIER_DIVERGE_DA_MERCATO_CONGELATO")

    local_handoff=None
    publication="NON_PREPARATO"
    missing=[]
    if isinstance(quality,dict):
        missing=list(quality.get("motivi_incompletezza") or [])[:30]
        missing+=list(quality.get("motivi_patrimoniali") or [])[:30]
    current_wallet=desk.load("portafoglio.json",{})
    wallet_same=desk.fotografia_portafoglio_sha256(current_wallet)==wallet_sha
    current_source=desk.load("ultima_rilevazione.json",{})
    market_same=(isinstance(current_source,dict)
                 and sha(encode(current_source))==snapshot_sha)
    current_dossier=desk.load("dossier_multifonte.json",{})
    dossier_same=(isinstance(current_dossier,dict)
                  and sha(encode(current_dossier))==dossier_digest)
    if not wallet_same:
        missing.append("FILE_WALLET_MUTATO_RISPETTO_ALLA_FOTO_CONGELATA")
    if not market_same:
        missing.append("FILE_MERCATO_MUTATO_RISPETTO_ALLA_FOTO_CONGELATA")
    if not dossier_same:
        missing.append("FILE_DOSSIER_MUTATO_RISPETTO_ALLA_FOTO_CONGELATA")
    # PARTIAL material is preserved for review but an ineligible or stale
    # packet is NEVER automatically handed to GPT as if fully current.
    can_export=(eligible=="IDONEA" and wallet_same and market_same
                and dossier_same and 0<=age<=SNAPSHOT_MAX_AGE_SECONDS)
    if can_export:
        try:
            # Existing validated packet and two-file FolderSync preparation.
            local_handoff=exchange.prepare_export(require_recent=True)
            # Check no producer replaced its current inputs during export.
            stable=(desk.fotografia_portafoglio_sha256(
                        desk.load("portafoglio.json",{}))==wallet_sha and
                    sha(encode(desk.load("ultima_rilevazione.json",{})))==snapshot_sha and
                    sha(encode(desk.load("dossier_multifonte.json",{})))==dossier_digest)
            if stable:
                publication="PRONTO_PER_FOLDERSYNC"
            else:
                local_handoff=None
                publication="PUBBLICAZIONE_INCERTA_FILE_MUTATO"
                missing.append("FILE_MUTATO_DURANTE_ESPORTAZIONE")
        except Exception as exc:
            local_handoff=None
            publication="NON_PREPARATO_"+type(exc).__name__
            missing.append("HANDOFF_NON_PREPARATO:"+type(exc).__name__)
    else:
        publication="NON_PREPARATO_DATI_NON_IDONEI"
        if age>SNAPSHOT_MAX_AGE_SECONDS:
            missing.append("FOTOGRAFIA_SCADUTA_AL_CONSUMO")

    availability=("PRONTO_LOCALE" if can_export and
                  publication=="PRONTO_PER_FOLDERSYNC"
                  else "PARZIALE_LOCALE")
    return {"snapshot_sha":snapshot_sha,
            "snapshot_time":frozen["source_observed_at"],
            "snapshot_id":frozen["snapshot_id"],
            "manifest_sha":frozen["manifest_sha256"],
            "source_observation_id":frozen["source_observation_id"],
            "source_run_id":frozen["source_observation_id"],
            "dossier_sha":dossier_digest,
            "handoff_file":str(local_handoff) if local_handoff else None,
            "publication_state":publication,
            "dossier_status":availability,
            "quality":{"stato_fonti":completeness,
                       "idoneita":eligible,
                       "stato_produttore":state,
                       "lacune":missing,
                       "immagine_congelata_utc":frozen["frozen_at"],
                       "manifest_origin":frozen["manifest_sha256"],
                       "reused_artifact_from":reused_from,
                       "observations_consumed":quality.get("observations_consumed",used_ids)
                         if isinstance(quality,dict) else used_ids},
            "reused_from":reused_from}


def main(argv=None):
    parser = argparse.ArgumentParser(description="KDD-27 G2 experimental, no automatic Android registration")
    parser.add_argument("command", choices=("status","run-due","dossiers"))
    args = parser.parse_args(argv)
    store = Store()
    if args.command=="status":
        print(json.dumps(store.status(),ensure_ascii=False))
    elif args.command=="run-due":
        print(json.dumps(store.run_due(lambda n,i,d: real_family_worker(store,n,i,d)),ensure_ascii=False))
    else:
        print(json.dumps(store.process_queue(real_dossier_producer),ensure_ascii=False))


if __name__ == "__main__":
    main()
