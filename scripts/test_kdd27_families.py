"""KDD-27 G2 family-scheduling and source contracts. Synthetic IO only."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zlib
import sqlite3
from scripts import kdd27_runtime as core
from scripts import kdd27_families as families

START=dt.datetime(2026,11,1,tzinfo=dt.timezone.utc)


class FamilyJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=core.Store(Path(self.tmp.name))

    def insert(self,family,payload,when=START,state="OSSERVATO"):
        raw=core.encode(payload)
        ident=core.sha(core.encode([family,when.isoformat(),core.sha(raw)]))
        with self.store.connection() as c:
            c.execute("""INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)""",
                      (ident,"fixture",family,core.iso(when),core.iso(when),
                       core.sha(raw),sqlite3.Binary(zlib.compress(raw)),len(raw),state))
        return ident

    def test_family_schedule_is_explicit_disabled_by_default_and_independent(self):
        self.assertEqual(self.store.status()["jobs"],[])
        self.store.setup_families("A",START,enable=False)
        statuses=self.store.family_coverage(START)
        self.assertGreaterEqual(len(statuses),12)
        self.assertEqual(set(statuses),set(families.SPECS))
        self.assertTrue(all(not item["attivo"] for item in statuses.values()))
        self.assertEqual(self.store.run_due(lambda *a:self.fail("not enabled"),START+
                                             dt.timedelta(days=30)),[])
        periods={name:value["periodo_s"] for name,value in statuses.items()}
        self.assertNotEqual(periods["wallet_spot"],periods["scanner"])
        self.assertNotEqual(periods["scanner"],periods["primary_events"])
        self.assertTrue(all(not spec["approved"] for spec in families.SPECS.values()))
        with self.assertRaises(ValueError):
            self.store.setup_families("A",START,enable=True)

    def test_30_days_source_cursors_and_scheduler_without_any_dossier(self):
        self.store.setup_families("A",START,enable=True)
        with self.store.connection() as c:
            c.execute("DELETE FROM jobs WHERE name NOT IN"
                      " ('wallet_spot','market_catalog','scanner')")
        counter={"wallet_spot":0,"market_catalog":0,"scanner":0}
        def worker(name,run_id,due):
            counter[name]+=1
            old=self.store.latest(name)
            old_cursor=((old or {}).get("payload") or {}).get("rotation",0)
            return {"payload":{"rotation":old_cursor+1},
                    "state":"OSSERVATO","observed_at":core.iso(due),
                    "cursor":{"rotation":old_cursor+1},
                    "metrics":{"source_calls":1,"source_bytes":32}}
        for hour in range(1,721):
            result=self.store.run_due(worker,START+dt.timedelta(hours=hour))
            self.assertTrue(all(row["status"]=="RIUSCITO" for row in result))
        self.assertEqual(counter,{"wallet_spot":720,"market_catalog":720,"scanner":120})
        self.assertEqual(self.store.status()["dossiers"],{})
        self.assertEqual(self.store.status()["observations"],1560)
        self.assertEqual(self.store.latest("scanner")["payload"]["rotation"],120)
        self.assertEqual(self.store.latest("wallet_spot")["payload"]["rotation"],720)
        self.assertEqual(self.store.latest("market_catalog")["payload"]["rotation"],720)
        with self.store.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM gaps").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM dossier_requests").fetchone()[0],0)

    def test_late_android_wake_records_individual_missed_windows(self):
        self.store.setup_families("A",START,enable=True)
        # Avoid performing public IO. Same timestamp, different independent intervals.
        now=START+dt.timedelta(days=31)
        results=self.store.run_due(lambda name,uid,due:{
            "payload":{"family":name},"observed_at":core.iso(now),
            "metrics":{"source_calls":0}},now)
        self.assertEqual(len(results),len(families.SPECS))
        by_family={x["family"]:x["missed"] for x in results}
        self.assertGreater(by_family["wallet_spot"],by_family["scanner"])
        self.assertGreater(by_family["scanner"],by_family["primary_events"])
        with self.store.connection() as c:
            missed=dict(c.execute("SELECT name,count FROM gaps"))
            self.assertEqual(missed["wallet_spot"],by_family["wallet_spot"])
            self.assertEqual(missed["primary_events"],by_family["primary_events"])
        self.assertEqual(self.store.status()["dossiers"],{})

    def test_ttl_is_checked_at_consumer_even_when_sample_is_retained(self):
        ident=self.insert("market_catalog",{"pairs":{},"tickers":{}})
        recent=families.source(self.store,"market_catalog",START+dt.timedelta(minutes=5))
        self.assertEqual(recent["pairs"],{})
        self.assertTrue(self.store.latest("market_catalog")["observation_id"]==ident)
        with self.assertRaisesRegex(families.MissingSource,"FONTE_SCADUTA"):
            families.source(self.store,"market_catalog",START+dt.timedelta(hours=2))
        report=self.store.family_coverage(START+dt.timedelta(hours=2))
        self.assertEqual(report["market_catalog"]["stato"],"SCADUTO")
        self.assertEqual(self.store.status()["observations"],1)

    def test_recent_valid_sample_remains_usable_after_failed_provider_cycle(self):
        self.insert("market_catalog",{"pairs":{"X":1},"tickers":{}},START)
        self.insert("market_catalog",{"stato":"NON_ACQUISITO"},
                    START+dt.timedelta(minutes=9),state="NON_ACQUISITO")
        selected=families.source(self.store,"market_catalog",
                                 START+dt.timedelta(minutes=10))
        self.assertEqual(selected["pairs"],{"X":1})
        report=self.store.family_coverage(START+dt.timedelta(minutes=10))
        self.assertEqual(report["market_catalog"]["stato"],"RECENTE")
        self.assertEqual(report["market_catalog"]["ultimo_tentativo_stato"],
                         "NON_ACQUISITO")
        self.assertEqual(report["market_catalog"]["eta_s"],600)
        with self.assertRaises(families.MissingSource):
            families.source(self.store,"market_catalog",
                             START+dt.timedelta(hours=2))

    def test_missing_scanner_input_yields_zero_external_calls_not_fake_market(self):
        with mock.patch("decision_desk.kraken") as api:
            out=families.collect(self.store,"scanner",START)
        self.assertEqual(out["state"],"NON_ACQUISITO")
        self.assertEqual(out["metrics"]["source_calls"],0)
        self.assertIn("FONTE_ASSENTE",out["payload"]["motivo"])
        api.assert_not_called()

    def test_actual_wallet_and_catalog_adapters_use_bounded_original_producers(self):
        import decision_desk as desk
        wallet={"posizioni":[{"token":"BTC","quantita":"1"}]}
        with mock.patch.object(desk,"load",return_value=wallet):
            balance=families.collect(self.store,"wallet_spot",START,
                     overrides={"saldo":lambda:{"stato":"RIUSCITO"}})
        self.assertEqual(balance["state"],"OSSERVATO")
        self.assertEqual(balance["payload"]["wallet"],wallet)
        self.assertEqual(balance["metrics"]["source_calls"],0)
        called=[]
        def fake_kraken(endpoint,**kwargs):
            called.append(endpoint)
            return {}
        out=families.collect(self.store,"market_catalog",START,
                             overrides={"kraken":fake_kraken})
        self.assertEqual(called,["AssetPairs","Ticker"])
        self.assertEqual(out["metrics"]["source_calls"],2)
        self.assertEqual(out["state"],"OSSERVATO")

    def test_budget_enforced_before_a_third_request_even_if_supplier_fails(self):
        calls=[]
        def supplier(name):
            calls.append(name)
            if name=="FAIL":
                raise OSError("no network")
        bounded=families.BoundCalls(supplier,2)
        with self.assertRaises(OSError):
            bounded("FAIL")
        bounded("second")
        with self.assertRaises(families.ProducerBudget):
            bounded("forbidden")
        self.assertEqual(calls,["FAIL","second"])
        self.assertEqual(bounded.calls,2)

    def test_scanner_rotation_cursor_from_archived_observation(self):
        import ricerca_setup,mercati_spot,decision_desk as desk
        self.insert("market_catalog",{"pairs":{},"tickers":{}},START)
        visits=[]
        def fake_scan(markets,configuration,fetch,now,max_requests=24,*,previous=None):
            prior=(previous or {}).get("ciclo",0)
            visits.append(prior)
            return [],{"ciclo":prior+1,"richieste_ohlc_1h":0,
                       "copertura_progressiva_pct":None},{}
        with mock.patch.object(ricerca_setup,"scan",side_effect=fake_scan), \
             mock.patch.object(mercati_spot,"assemble",return_value=({},{})), \
             mock.patch.object(desk,"load",return_value={"scanner":{}}):
            for index in range(2):
                at=START+dt.timedelta(minutes=index+1)
                acquired=families.collect(self.store,"scanner",at,
                           overrides={"kraken":lambda *_a,**_k:self.fail("unexpected HTTP")})
                self.insert("scanner",acquired["payload"],at)
        self.assertEqual(visits,[0,1])
        self.assertEqual(self.store.latest("scanner")["payload"]["ricerca"]["ciclo"],2)


if __name__=="__main__":
    unittest.main()
