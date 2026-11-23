"""KDD-27 first tranche: original runtime modules, no Kraken/Drive/Samsung IO."""
import contextlib
import datetime as dt
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request
import json

from scripts import kdd27_runtime as k27
from scripts import kdd27_telemetry as meter

UTC = dt.timezone.utc
START = dt.datetime(2026, 11, 1, tzinfo=UTC)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = k27.Store(Path(self.tmp.name))
        self.assertEqual(self.db.status()["jobs"], [])

    def enroll(self):
        self.db.setup("A", START, enable=True)
        return k27.PROFILES["A"]

    def test_import_alone_never_enrolls_android_or_local_jobs(self):
        self.assertEqual(self.db.status()["jobs"], [])
        self.assertEqual(self.db.run_due(lambda *a: self.fail("worker must not start"), START), [])
        self.assertFalse(any(Path(self.tmp.name).rglob("*.sh")))

    def test_manual_monitor_is_archived_without_shifting_autonomous_deadline(self):
        period=self.enroll()
        before=self.db.status()["jobs"][0][2]
        result=self.db.run_manual_monitor(lambda name,run_id,due:{
            "payload":{"schema":"kdd27_monitor_observation_v001",
                       "monitor_run_id":run_id,"snapshot":{"rilevazione_utc":k27.iso(due)},
                       "dossier_prodotto":False},
            "observed_at":k27.iso(due),
            "cursor":{"ciclo":99},
            "metrics":{"total":{"calls":2,"bytes":120}}},
            START+dt.timedelta(seconds=60))
        self.assertEqual(result["status"],"MANUALE")
        self.assertEqual(self.db.status()["jobs"][0][2],before)
        self.assertEqual(self.db.status()["observations"],1)
        self.assertEqual(self.db.latest()["run_id"],result["run_id"])
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT status FROM runs"
                         " WHERE run_id=?", (result["run_id"],)).fetchone()[0],
                             "MANUALE")

    def test_30_days_rotation_and_dossier_independence(self):
        period = self.enroll()
        calls = []
        def producer(name, run_id, due):
            calls.append(due)
            return {"payload": {"run_id":run_id, "observation": len(calls)},
                    "observed_at": k27.iso(due),
                    "cursor": {"ciclo":len(calls)},
                    "metrics": {"calls":1,"bytes":100}}
        for index in range(1, 361):
            now = START + dt.timedelta(seconds=index*period)
            result = self.db.run_due(producer, now)
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]["status"],"RIUSCITO")
        self.assertEqual(self.db.status()["observations"],360)
        self.assertEqual(self.db.status()["dossiers"],{})
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT SUM(missed) FROM runs").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM gaps").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT data_json FROM cursors").fetchone()[0],
                             '{"ciclo":360}')

    def test_skip_windows_not_backfill_and_bounded_error(self):
        period = self.enroll()
        def offline(*args):
            raise OSError("NETWORK_OFFLINE")
        out = self.db.run_due(offline, START + dt.timedelta(seconds=8*period))
        self.assertEqual(out[0]["status"],"ERRORE")
        self.assertEqual(out[0]["missed"],7)
        self.assertEqual(self.db.status()["observations"],0)
        with self.db.connection() as c:
            gap = c.execute("SELECT count,start_s,end_s FROM gaps").fetchone()
            self.assertEqual(gap[0],7)
            self.assertEqual(c.execute("SELECT next_due_s FROM jobs").fetchone()[0],
                             int(START.timestamp())+9*period)
        self.assertEqual(self.db.run_due(lambda *_: self.fail("replayed"), 
                            START+dt.timedelta(seconds=8*period+50)), [])

    def test_restart_fixes_incomplete_run_and_preserves_preexisting_observation(self):
        p = self.enroll()
        self.db.run_due(lambda name,id,due: {
            "payload":{"token":"BTC","test_only":True},
            "observed_at":k27.iso(due)},START+dt.timedelta(seconds=p))
        before=self.db.latest()
        with self.db.connection() as c:
            c.execute("INSERT INTO runs(run_id,name,due_s,start_s,status)"
                      " VALUES('interrupted','job',123,456,'IN_CORSO')")
        reboot=k27.Store(Path(self.tmp.name))
        self.assertEqual(reboot.run_due(lambda *_: self.fail("not due"),
                          START+dt.timedelta(seconds=p+1)), [])
        with reboot.connection() as c:
            self.assertEqual(c.execute("SELECT status FROM runs"
                         " WHERE run_id='interrupted'").fetchone()[0],"INTERROTTO")
        self.assertEqual(reboot.latest()["sha256"],before["sha256"])

    def test_duplicate_observation_rejected_by_content_and_run_id(self):
        period=self.enroll()
        out=self.db.run_due(lambda *a: {"payload":{"v":1},
                          "observed_at":k27.iso(START)}, 
                          START+dt.timedelta(seconds=period))
        self.assertEqual(len(out),1)
        self.assertEqual(self.db.status()["observations"],1)
        with self.db.connection() as c:
            rec=c.execute("SELECT observation_id,run_id,family,observed_at,"
                          "received_at,sha256,payload_z,payload_bytes,state"
                          " FROM observations").fetchone()
            c.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",rec)
        self.assertEqual(self.db.status()["observations"],1)

    def test_tampered_observation_is_not_reused(self):
        period=self.enroll()
        self.db.run_due(lambda *a:{"payload":{"v":1}},
                        START+dt.timedelta(seconds=period))
        with self.db.connection() as c:
            c.execute("UPDATE observations SET sha256='0'")
        with self.assertRaisesRegex(ValueError,"CORRUZIONE_OSSERVAZIONE"):
            self.db.latest()

    def test_cross_thread_lock_prevents_concurrent_writer(self):
        period=self.enroll()
        entered=threading.Event()
        release=threading.Event()
        def lock_holder():
            with self.db.exclusive():
                entered.set()
                release.wait(3)
        thread=threading.Thread(target=lock_holder)
        thread.start()
        self.assertTrue(entered.wait(3))
        try:
            with self.assertRaisesRegex(RuntimeError,"KDD27_BUSY"):
                self.db.run_due(lambda *a:{"payload":{"v":1}},
                                START+dt.timedelta(seconds=period))
        finally:
            release.set()
            thread.join(3)
        result=self.db.run_due(lambda *a:{"payload":{"v":1}},
                               START+dt.timedelta(seconds=period))
        self.assertEqual(result[0]["status"],"RIUSCITO")

    def test_20_manual_requests_reuse_verified_snapshot_not_twenty_api_refreshes(self):
        ids = [f"request{i:04}" for i in range(20)]
        for uid in ids:
            self.assertEqual(self.db.enqueue_dossier(uid, START)["status"],"IN_ATTESA")
        self.assertTrue(self.db.enqueue_dossier(ids[0],START)["reused_id"])
        expensive=[0]
        cache={}
        def producer(store, uid, when):
            if not cache:
                expensive[0]+=1
                cache.update({"snapshot_sha":"a"*64,"snapshot_time":k27.iso(START),
                              "snapshot_id":"c"*64,"manifest_sha":"d"*64,
                              "source_observation_id":"e"*64,
                              "dossier_sha":"b"*64,"handoff_file":"handoff.json",
                              "dossier_status":"PRONTO_LOCALE",
                              "metrics":{"calls":20,"bytes":2000}})
            return dict(cache)
        results=[]
        for _ in ids:
            results+=self.db.process_queue(producer,START,limit=1)
        self.assertEqual(len(results),20)
        self.assertTrue(all(status=="PRONTO_LOCALE" for _,status in results))
        self.assertEqual(expensive[0],1)
        self.assertEqual(self.db.status()["dossiers"]["PRONTO_LOCALE"],20)
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(DISTINCT request_id)"
                                      " FROM dossier_requests").fetchone()[0],20)
            self.assertEqual(c.execute("SELECT COUNT(DISTINCT dossier_sha)"
                                      " FROM dossier_requests").fetchone()[0],1)
        # No calendar is altered by the manual dossier path.
        self.assertEqual(self.db.status()["jobs"],[])

    def test_monitor_and_dossier_contend_without_wiping_photographs(self):
        p=self.enroll()
        self.db.enqueue_dossier("manual001", START)
        with self.db.exclusive():
            with self.assertRaisesRegex(RuntimeError,"KDD27_BUSY"):
                self.db.process_queue(lambda *a:self.fail("duplicate"))
        done=self.db.run_due(lambda *a:{"payload":{"value":"safe"}},
                             START+dt.timedelta(seconds=p))
        self.assertEqual(done[0]["status"],"RIUSCITO")
        self.db.process_queue(lambda *_: {"snapshot_sha":"a"*64,
                            "snapshot_time":k27.iso(START),
                            "snapshot_id":"c"*64,"manifest_sha":"d"*64,
                            "source_observation_id":"e"*64,
                            "dossier_sha":"b"*64,"handoff_file":"outbox.json",
                            "dossier_status":"PRONTO_LOCALE"},
                            START,limit=1)
        self.assertEqual(self.db.status()["observations"],1)
        self.assertEqual(self.db.dossier_status("manual001")[0]["status"],"PRONTO_LOCALE")



class DossierProducerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = k27.Store(Path(self.tmp.name))

    def test_real_producer_51_requests_reuse_one_partial_and_expose_lacuna(self):
        """Actual KDD producer entry, mocked IO; not a hand-written queue-only fake."""
        import decision_desk as desk
        from scripts import kdd_drive_exchange as exchange
        now = dt.datetime.now(UTC)
        old={"rilevazione_utc":k27.iso(now-dt.timedelta(hours=2))}
        current={"rilevazione_utc":k27.iso(now),"ricerca_setup":{"ciclo":2}}
        wallet={"posizioni":[],"fonte_quantita":"TEST_FIXTURE_SOLO_SINTETICA"}
        wallet_sha=desk.fotografia_portafoglio_sha256(wallet)
        dossier={"kraken_istantanea_utc":current["rilevazione_utc"],
                 "creato_utc":k27.iso(now),"schema":3,
                 "fotografia_portafoglio_sha256":wallet_sha,
                 "evidenze_economiche":{"stato":"PARZIALE"}}
        state={"ultima_rilevazione.json":old,"dossier_multifonte.json":{},
               "portafoglio.json":wallet}
        count={"refresh":0,"deep":0,"export":0}
        def refresh(*,prepare_dossier=False):
            self.assertFalse(prepare_dossier)
            count["refresh"]+=1
            state["ultima_rilevazione.json"]=current
            return current
        def deepen(snapshot, *, wallet_override=None):
            self.assertEqual(snapshot,current)
            self.assertEqual(wallet_override,wallet)
            count["deep"]+=1
            state["dossier_multifonte.json"]=dossier
            return {"stato":"PARZIALE","stato_fonti_mercato":"PARZIALE",
                    "idoneita_analisi_patrimoniale":"NON_IDONEA",
                    "motivi_incompletezza":["MACRO_NON_DISPONIBILE"],
                    "motivi_patrimoniali":["SALDO_NON_RECENTE"]}
        with mock.patch.object(desk,"load",side_effect=lambda name,default=None:
                                  state.get(name,default)), \
             mock.patch.object(desk,"refresh",side_effect=refresh), \
             mock.patch.object(desk,"prepara_dossier_aggiornamento",
                               side_effect=deepen), \
             mock.patch.object(exchange,"prepare_export",
                               side_effect=lambda **kw:count.__setitem__(
                                   "export",count["export"]+1)):
            for n in range(51):
                uid=f"request{n:04}"
                self.assertEqual(self.db.enqueue_dossier(uid,now)["status"],"IN_ATTESA")
            for n in range(51):
                self.assertEqual(
                    self.db.process_queue(k27.real_dossier_producer,now,limit=1),
                    [(f"request{n:04}","PARZIALE_LOCALE")])
        self.assertEqual(count,{"refresh":1,"deep":1,"export":0})
        self.assertEqual(self.db.status()["observations"],1)
        self.assertEqual(self.db.status()["dossiers"]["PARZIALE_LOCALE"],51)
        with self.db.connection() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM dossier_freezes").fetchone()[0],51)
            self.assertEqual(c.execute(
                "SELECT COUNT(DISTINCT source_observation_id) FROM dossier_freezes"
                ).fetchone()[0],1)
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM dossier_artifacts").fetchone()[0],1)
        self.assertIn("MACRO_NON_DISPONIBILE",
              self.db.dossier_status("request0050")[0]["quality_json"])
        self.assertEqual(self.db.status()["jobs"],[])

    def test_source_freeze_survives_restart_and_local_mutation(self):
        import decision_desk as desk
        from scripts import kdd27_freeze as freeze
        now=dt.datetime.now(UTC)
        uid="frozen_001"
        source={"rilevazione_utc":k27.iso(now),"market":4}
        wallet={"posizioni":[]}
        self.db.enqueue_dossier(uid,now)
        rec=self.db.record_dossier_snapshot(uid,source,source["rilevazione_utc"])
        frozen=freeze.freeze(self.db,uid,now=now,source=source,
                    source_observation_id=rec["observation_id"],wallet=wallet)
        original=frozen["snapshot_id"]
        source["market"]=999
        wallet["posizioni"]=[{"token":"XBT","quantita":"1234"}]
        self.assertEqual(freeze.get(self.db,uid)["source"]["market"],4)
        reopened=k27.Store(Path(self.tmp.name))
        self.assertEqual(freeze.get(reopened,uid)["snapshot_id"],original)
        newer={"rilevazione_utc":k27.iso(now),"market":999}
        unchanged=freeze.freeze(reopened,uid,now=now,source=newer,
                         source_observation_id="invalid",wallet=wallet)
        self.assertEqual(unchanged["snapshot_id"],original)
        self.assertEqual(unchanged["wallet"]["posizioni"],[])

    def test_tampering_stored_frozen_observation_fails_closed(self):
        from scripts import kdd27_freeze as freeze
        now=dt.datetime.now(UTC)
        uid="frozen_tamper"
        source={"rilevazione_utc":k27.iso(now),"market":1}
        wallet={"posizioni":[]}
        self.db.enqueue_dossier(uid,now)
        rec=self.db.record_dossier_snapshot(uid,source,source["rilevazione_utc"])
        freeze.freeze(self.db,uid,now=now,source=source,
                     source_observation_id=rec["observation_id"],wallet=wallet)
        with self.db.connection() as c:
            c.execute("UPDATE observations SET sha256='0' WHERE observation_id=?",
                      (rec["observation_id"],))
        with self.assertRaises(freeze.FrozenMismatch):
            freeze.get(self.db,uid)

    def test_stale_source_never_relabelled_current_when_upstream_is_offline(self):
        import decision_desk as desk
        from scripts import kdd_drive_exchange as exchange
        now=dt.datetime.now(UTC)
        bad={"rilevazione_utc":k27.iso(now-dt.timedelta(hours=1))}
        with mock.patch.object(desk,"load",return_value=bad), \
             mock.patch.object(desk,"refresh",side_effect=OSError("network down")), \
             mock.patch.object(exchange,"prepare_export") as export:
            self.db.enqueue_dossier("stale001",now)
            result=self.db.process_queue(k27.real_dossier_producer,now,limit=1)
        self.assertEqual(result,[("stale001","RINVIATO_RETE")])
        self.assertEqual(self.db.dossier_status("stale001")[0]["error"],"OSError")
        export.assert_not_called()


class DossierHTTPTests(unittest.TestCase):
    def test_real_localhost_handler_request_id_idempotence_and_status(self):
        import http.client
        from http.server import ThreadingHTTPServer
        import urllib.parse
        import serve
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(k27,"private_root",return_value=Path(folder)), \
             mock.patch.object(serve,"kick_dossier_queue") as kick:
            server=ThreadingHTTPServer(("127.0.0.1",0),serve.Handler)
            server.daemon_threads=True
            with mock.patch.object(serve,"PORT",server.server_address[1]):
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    port=server.server_address[1]
                    def post(token, uid):
                        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=3)
                        body=urllib.parse.urlencode({"token":token,"request_id":uid})
                        conn.request("POST","/dossier/richiedi",body,
                                     {"Content-Type":"application/x-www-form-urlencoded"})
                        response=conn.getresponse()
                        code=response.status
                        response.read()
                        conn.close()
                        return code
                    identifier="a"*32
                    self.assertEqual(post(serve.TOKEN,identifier),303)
                    self.assertEqual(post(serve.TOKEN,identifier),303)
                    self.assertEqual(post("invalid-token","b"*32),403)
                    conn=http.client.HTTPConnection("127.0.0.1",port,timeout=3)
                    conn.request("GET","/dossier/stato")
                    response=conn.getresponse()
                    self.assertEqual(response.status,200)
                    rows=json.loads(response.read())
                    conn.close()
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]["request_id"],identifier)
                    self.assertEqual(rows[0]["status"],"IN_ATTESA")
                    self.assertTrue(kick.called)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(3)

class TelemetryTests(unittest.TestCase):
    def test_http_byte_count_and_no_url_leak(self):
        class Remote:
            def __enter__(self): return self
            def __exit__(self,*a): return None
            def read(self,*a): return b'1234567'
        with mock.patch.object(meter,"ORIGINAL", lambda *a, **kw: Remote()):
            with meter.Telemetry() as met:
                with urllib.request.urlopen("https://api.kraken.com/0/public/Ticker?pair=SENSITIVE") as r:
                    self.assertEqual(r.read(),b"1234567")
            record=met.report()
        self.assertEqual(record["total"],{"calls":1,"bytes":7,"errors":0})
        self.assertEqual(record["sources"][0]["provider"],"kraken")
        self.assertNotIn("SENSITIVE",str(record))


if __name__ == "__main__":
    unittest.main()
