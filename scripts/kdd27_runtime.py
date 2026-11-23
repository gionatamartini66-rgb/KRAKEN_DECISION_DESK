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
MAX_QUEUE = 40
MAX_DEEP_DAY = 20  # Experimental per-UTC-day cap; not a provider rate-limit.


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
                    observation_id = sha(encode([run_id, name, measured_at, digest]))
                    with self.connection() as c:
                        c.execute("BEGIN IMMEDIATE")
                        c.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                                  (observation_id, run_id, name, measured_at, iso(),
                                   digest, sqlite3.Binary(zlib.compress(serialized)),
                                   len(serialized), "OSSERVATO"))
                        if cursor is not None:
                            c.execute("INSERT INTO cursors VALUES(?,?,?)"
                                      " ON CONFLICT(family) DO UPDATE SET "
                                      "data_json=excluded.data_json,updated_at=excluded.updated_at",
                                      (name, encode(cursor).decode(), iso()))
                        c.execute("UPDATE runs SET status='RIUSCITO',finish_s=?,"
                                  "metrics_json=?,snapshot_sha=? WHERE run_id=?",
                                  (time.time(), encode(metrics).decode(), digest, run_id))
                        c.commit()
                    results.append({"run_id": run_id, "status": "RIUSCITO",
                                    "missed": missed, "sha256": digest})
                except Exception as exc:
                    with self.connection() as c:
                        c.execute("UPDATE runs SET status='ERRORE',finish_s=?,error=?"
                                  " WHERE run_id=?", (time.time(), type(exc).__name__, run_id))
                    results.append({"run_id": run_id, "status": "ERRORE",
                                    "error": type(exc).__name__, "missed": missed})
            return results

    def latest(self, family=MONITOR_JOB):
        with self.connection() as c:
            row = c.execute("SELECT run_id,observed_at,sha256,payload_z"
                            " FROM observations WHERE family=?"
                            " ORDER BY observed_at DESC LIMIT 1", (family,)).fetchone()
        if not row:
            return None
        raw = zlib.decompress(row[3])
        if sha(raw) != row[2]:
            raise ValueError("CORRUZIONE_OSSERVAZIONE")
        return {"run_id": row[0], "observed_at": row[1],
                "sha256": row[2], "payload": json.loads(raw)}

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
            count = c.execute("SELECT COUNT(*) FROM dossier_requests WHERE status IN"
                              " ('IN_ATTESA','IN_CORSO')").fetchone()[0]
            if count >= MAX_QUEUE:
                c.rollback()
                raise ValueError("CODA_COMPLETA")
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

    def process_queue(self, producer, now=None, limit=40):
        """Serialize dossier runs with monitor runs, without modifying job dates."""
        results = []
        with self.exclusive(nonblocking=True):
            with self.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                self._recover(c)
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
                    required = ("snapshot_sha","snapshot_time","dossier_sha","handoff_file")
                    if any(not produced.get(k) for k in required):
                        raise ValueError("Incomplete dossier provenance")
                    with self.connection() as c:
                        c.execute("UPDATE dossier_requests SET status='PRONTO_LOCALE',"
                                  "completed_at=?,snapshot_sha=?,snapshot_time=?,"
                                  "dossier_sha=?,handoff_file=?,source_run_id=?,"
                                  "reused_from=?,metrics_json=? WHERE request_id=?",
                                  (iso(), *(produced[k] for k in required),
                                   produced.get("source_run_id"),produced.get("reused_from"),
                                   encode(produced.get("metrics") or {}).decode(),request_id))
                    results.append((request_id,"PRONTO_LOCALE"))
                except Exception as exc:
                    state = ('RINVIATO_BUDGET' if isinstance(exc, BudgetDeferred)
                             else 'ERRORE')
                    with self.connection() as c:
                        c.execute("UPDATE dossier_requests SET status=?,"
                                  "completed_at=?,error=? WHERE request_id=?",
                                  (state, iso(), type(exc).__name__, request_id))
                    results.append((request_id,state))
        return results


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
    """On-demand dossier from one coherent legacy snapshot, existing bridge."""
    import decision_desk as desk
    from scripts import kdd_drive_exchange as exchange
    current = desk.load("ultima_rilevazione.json", {})
    observed = current.get("rilevazione_utc") if isinstance(current,dict) else None
    try:
        age = (now - dt.datetime.fromisoformat(observed)).total_seconds()
    except (TypeError, ValueError, OverflowError):
        age = float("inf")
    from scripts.kdd27_telemetry import Telemetry
    with Telemetry() as meter:
        result = _produce_dossier_measured(store, request_id, now, desk, exchange,
                                          current, age)
    result['metrics'] = meter.report()
    return result


def _produce_dossier_measured(store, request_id, now, desk, exchange,
                              current, age):
    if not (0 <= age <= SNAPSHOT_MAX_AGE_SECONDS):
        current = desk.refresh(prepare_dossier=False)
    observed = current["rilevazione_utc"]
    # Caches already-built dossier only for the identical Kraken snapshot and
    # within a bounded age. No renewed timestamps are assigned to cached data.
    old = desk.load("dossier_multifonte.json", {})
    reuse = (isinstance(old,dict) and old.get("kraken_istantanea_utc")==observed
             and isinstance(old.get("creato_utc"),str))
    if reuse:
        try:
            elapsed = (now-dt.datetime.fromisoformat(old["creato_utc"])).total_seconds()
            reuse = 0 <= elapsed <= CACHE_SECONDS
        except (ValueError, TypeError):
            reuse = False
    if not reuse:
        day = now.date().isoformat()
        with store.connection() as c:
            n = c.execute("SELECT COUNT(*) FROM dossier_requests WHERE"
                          " status='PRONTO_LOCALE' AND reused_from IS NULL AND"
                          " substr(completed_at,1,10)=?", (day,)).fetchone()[0]
        if n >= MAX_DEEP_DAY:
            raise BudgetDeferred('BUDGET_DOSSIER_GIORNALIERO')
        status = desk.prepara_dossier_aggiornamento(current)
        if status.get("stato") in ("NON_DISPONIBILE", "PARZIALE"):
            raise ValueError("DOSSIER_NON_IDONEO")
        old = desk.load("dossier_multifonte.json", {})
    dossier_digest = sha(encode(old))
    with store.connection() as c:
        prev = c.execute("SELECT request_id,handoff_file FROM dossier_requests WHERE"
                         " dossier_sha=? AND status='PRONTO_LOCALE'"
                         " ORDER BY completed_at DESC LIMIT 1",
                         (dossier_digest,)).fetchone()
    local_handoff = None
    if reuse and prev and prev[1]:
        # Revalidate existing local handoff; a reference to a missing or
        # corrupted file cannot satisfy a new request, nor renew its clock.
        path = Path(prev[1])
        try:
            parent = exchange.EXCHANGE_ROOT.resolve(strict=True)
            if path.is_symlink() or path.resolve().parent != parent:
                raise ValueError('OUTBOX_NON_ATTENDIBILE')
            if not 2 <= path.stat().st_size <= exchange.bridge.MAX_BYTES:
                raise ValueError('DIMENSIONE_HANDOFF')
            raw = exchange.bridge.strict_json(path.read_bytes())
            check = exchange.bridge.read_context(raw, now=now)
            if check['mercato']['stato'] != 'RECENTE' or check['saldo']['stato'] != 'RECENTE':
                raise ValueError('HANDOFF_SCADUTO')
            local_handoff = path
        except (OSError,ValueError,KeyError,AttributeError,TypeError):
            local_handoff = None
    if local_handoff is None:
        local_handoff = exchange.prepare_export(require_recent=True)
    recent = store.latest()
    return {"snapshot_sha": sha(encode(current)), "snapshot_time": observed,
            "dossier_sha": dossier_digest, "handoff_file": str(local_handoff),
            "source_run_id": (recent or {}).get("run_id"),
            "reused_from": prev[0] if prev and reuse else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="KDD-27 G2 experimental, no automatic Android registration")
    parser.add_argument("command", choices=("status","run-due","dossiers"))
    args = parser.parse_args(argv)
    store = Store()
    if args.command=="status":
        print(json.dumps(store.status(),ensure_ascii=False))
    elif args.command=="run-due":
        print(json.dumps(store.run_due(real_monitor_worker),ensure_ascii=False))
    else:
        print(json.dumps(store.process_queue(real_dossier_producer),ensure_ascii=False))


if __name__ == "__main__":
    main()
