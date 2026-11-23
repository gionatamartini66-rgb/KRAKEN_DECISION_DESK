"""KDD-27 G2: authentic export/recovery time-of-check races, synthetic IO.

No Android, Drive, FolderSync, real holdings or private API. Original
scripts.kdd_drive_exchange, scripts.kdd_bridge_g2 and GPT retriever are run
in an isolated synthetic fixture. RED before precommit fix is intentional.
"""
from __future__ import annotations

import copy
import datetime as dt
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from scripts import kdd_drive_exchange as exchange
from scripts import kdd_bridge_g2 as bridge
from scripts import kdd_drive_index as index
from scripts import kdd_gpt_drive_retriever as retriever
from scripts import test_kdd_bridge_g2 as source_fixture
from scripts import test_kdd_gpt_drive_retriever as retrieval_fixture

UTC=dt.timezone.utc


class ExportCommitRaceTests(unittest.TestCase):
    def setUp(self):
        fixture=source_fixture.BridgeG2Tests(
            "test_01_real_original_producer_retains_all_rows_and_eur_provenance")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture=fixture
        self.bundle=fixture.bundle
        self.T=source_fixture.T
        self.folder=Path(tempfile.mkdtemp(prefix="kdd27-export-",dir=fixture.home))
        patch=mock.patch.object(exchange,"EXCHANGE_ROOT",self.folder)
        patch.start()
        self.addCleanup(patch.stop)
        self.real_read=bridge.read_context

    def _read_at(self,when):
        return lambda bundle,**kwargs: self.real_read(
            bundle,now=kwargs.get("now") or when[0])

    def _names(self):
        raw=bridge.canonical(self.bundle)+b"\n"
        dossier,manifest,_=index.publication(self.bundle,raw)
        return dossier,manifest

    def test_red_time_expired_after_dossier_rename_must_not_publish_index(self):
        """On the original HEAD: index published after base TTL expired."""
        watch=[self.T]
        dossier,index_name=self._names()
        publisher=exchange._publish_export_file
        def step(root,name,raw,**kwargs):
            publisher(root,name,raw,**kwargs)
            if name==dossier:
                watch[0]=self.T+dt.timedelta(seconds=1801)
        with mock.patch.object(bridge,"prepare",return_value=self.bundle), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)), \
             mock.patch.object(exchange,"_publish_export_file",side_effect=step):
            try:
                exchange.prepare_export(require_recent=True)
            except bridge.BridgeError:
                pass
        self.assertTrue((self.folder/dossier).is_file())
        self.assertFalse((self.folder/index_name).exists(),
                         "An expired snapshot was committed to FolderSync")

    def test_red_stale_pending_journal_must_not_commit_index_after_retry(self):
        """Interrupted after dossier; at retry source is 1801s old."""
        watch=[self.T]
        dossier,index_name=self._names()
        original=exchange._publish_export_file
        def interrupt(root,name,raw,**kwargs):
            if name==index_name:
                raise KeyboardInterrupt("fixture simulated crash after dossier")
            return original(root,name,raw,**kwargs)
        with mock.patch.object(bridge,"prepare",return_value=self.bundle), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)), \
             mock.patch.object(exchange,"_publish_export_file",side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                exchange.prepare_export(require_recent=True)
        self.assertTrue((self.folder/dossier).exists())
        self.assertFalse((self.folder/index_name).exists())
        watch[0]=self.T+dt.timedelta(seconds=1801)
        with mock.patch.object(bridge,"prepare") as new_prepare, \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)):
            with self.assertRaises(bridge.BridgeError):
                exchange.prepare_export(require_recent=True)
            new_prepare.assert_not_called()
        self.assertFalse((self.folder/index_name).exists(),
                         "Retry committed an expired publication before checking age")
        journal=bridge.PRIVATE_ROOT/"drive-export"
        self.assertFalse((journal/exchange._PENDING_EXPORT).exists())
        archived=journal/"rejected"/(bridge.digest(self.bundle)+".json")
        self.assertTrue(archived.is_file())
        self.assertEqual(bridge.strict_json(archived.read_bytes()),
                         {"dossier_sha256":bridge.digest(self.bundle)})
        self.assertEqual(bridge.verify_local_origin(self.bundle),
                         bridge.digest(self.bundle))
        # A rejected journal is retained privately, but no longer blocks the
        # next authorized transaction. A synthetic test clock returns to T.
        watch[0]=self.T
        with mock.patch.object(bridge,"prepare",return_value=self.bundle), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)):
            self.assertEqual(exchange.prepare_export(require_recent=True),dossier)
        self.assertTrue((self.folder/index_name).is_file())
        self.assertEqual(archived.read_bytes(),
                         bridge.canonical({"dossier_sha256":bridge.digest(self.bundle)})+b"\n")

    def test_original_gpt_recovers_actual_previous_export_with_later_orphan(self):
        """Real writer emits both files; failed newer writer exposes only dossier."""
        watch=[self.T]
        with mock.patch.object(bridge,"prepare",return_value=self.bundle), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)):
            old_name=exchange.prepare_export(require_recent=True)
        old_raw=bridge.canonical(self.bundle)+b"\n"
        old_d,old_idx,_=index.publication(self.bundle,old_raw)
        self.assertEqual(old_name,old_d)
        self.assertTrue((self.folder/old_idx).is_file())

        later=self.T+dt.timedelta(seconds=1)
        newer=bridge.prepare(self.fixture.fixture.root,now=later,_fixture=True)
        new_raw=bridge.canonical(newer)+b"\n"
        new_d,new_idx,_=index.publication(newer,new_raw)
        self.assertNotEqual(new_d,old_d)
        writer=exchange._publish_export_file
        watch[0]=later
        def expire_after_dossier(root,name,raw,**kwargs):
            outcome=writer(root,name,raw,**kwargs)
            if name==new_d:
                watch[0]=self.T+dt.timedelta(seconds=1801)
            return outcome
        with mock.patch.object(bridge,"prepare",return_value=newer), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)), \
             mock.patch.object(exchange,"_publish_export_file",side_effect=expire_after_dossier):
            with self.assertRaises(exchange.ExportGateRejected):
                exchange.prepare_export(require_recent=True)
        self.assertTrue((self.folder/new_d).is_file())
        self.assertFalse((self.folder/new_idx).exists())

        # Drive-shaped inventory of the EXACT bytes written by real producer.
        files=[]
        blobs={}
        old_index_id=None
        old_dossier_id=None
        for i,path in enumerate(sorted(self.folder.glob("kdd_handoff*json"))):
            raw=path.read_bytes()
            file_id="actual-"+str(i)
            files.append(retrieval_fixture.file_metadata(path.name,file_id,raw))
            blobs[file_id]=raw
            if path.name==old_idx:
                old_index_id=file_id
            if path.name==old_d:
                old_dossier_id=file_id
        self.assertIsNotNone(old_index_id)
        self.assertIsNotNone(old_dossier_id)
        driver=retrieval_fixture.FakeDrive(retrieval_fixture.pages_from(files),blobs)
        got=retriever.kdd_get_latest_verified_dossier(
            driver,retrieval_fixture.FOLDER,now=later)
        self.assertEqual(got["stato"],retriever.RECOVERED)
        self.assertEqual(got["file_id"],old_dossier_id)
        self.assertEqual(driver.downloads,[old_index_id,old_dossier_id])

    def test_true_kdd27_freeze_gate_blocks_book_expiry_during_index_commit(self):
        """Actual B -> exchange -> original bridge, family TTL expires AFTER dossier."""
        import json
        import sqlite3
        import zlib
        import decision_desk as desk
        from scripts import kdd27_runtime as k27
        from scripts import kdd27_freeze as freeze
        base=self.T
        source=copy.deepcopy(self.fixture.fixture.snapshot)
        wallet=copy.deepcopy(self.fixture.fixture.portfolio)
        # Keep a genuinely built original packet and a matching frozen wallet.
        packet=self.bundle["packet"]
        wallet_sha=desk.fotografia_portafoglio_sha256(wallet)
        self.assertEqual(packet["rilevazione_kdd_utc"],source["rilevazione_utc"])
        self.assertEqual(packet["patrimonio"]["fotografia_portafoglio_sha256"],wallet_sha)
        uid="SYNTHETIC_KDD27_TTL"
        store=k27.Store(self.folder/"private_sqlite")
        store.enqueue_dossier(uid,base)
        book={"bid":100,"ask":101,"synthetic":True}
        raw=k27.encode(book)
        digest=k27.sha(raw)
        oid=k27.sha(k27.encode(["spot_book",k27.iso(base),digest]))
        with store.connection() as c:
            c.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                      (oid,"fixture","spot_book",k27.iso(base),k27.iso(base),
                       digest,sqlite3.Binary(zlib.compress(raw)),len(raw),"OSSERVATO"))
        observed=store.record_dossier_snapshot(uid,source,source["rilevazione_utc"])
        frozen=freeze.freeze(store,uid,now=base,source=source,
                             source_observation_id=observed["observation_id"],wallet=wallet)
        self.assertEqual(next(x for x in frozen["manifest"]["families"]
                              if x["family"]=="spot_book")["stato"],"RECENTE")
        dossier={"schema":3,"kraken_istantanea_utc":source["rilevazione_utc"],
                 "fotografia_portafoglio_sha256":wallet_sha,"sample":"synthetic"}
        docs={"portafoglio.json":wallet,"ultima_rilevazione.json":source,
              "dossier_multifonte.json":{}}
        def build(snapshot,**kwargs):
            self.assertEqual(snapshot,source)
            docs["dossier_multifonte.json"]=dossier
            return {"stato":"PRONTO_PER_ESAME_GPT_CON_LIMITI",
                    "stato_fonti_mercato":"VERIFICATA",
                    "idoneita_analisi_patrimoniale":"IDONEA"}
        watch=[base]
        genuine_instant=k27.instant
        def clock(value=None):
            return watch[0] if value is None else genuine_instant(value)
        publisher=exchange._publish_export_file
        def publishing(root,name,data,**kwargs):
            result=publisher(root,name,data,**kwargs)
            if index.DOSSIER.fullmatch(name):
                watch[0]=base+dt.timedelta(seconds=301)
            return result
        with mock.patch.object(k27,"instant",side_effect=clock), \
             mock.patch.object(desk,"load",side_effect=lambda name,default=None:
                               docs.get(name,default)), \
             mock.patch.object(desk,"prepara_dossier_aggiornamento",side_effect=build), \
             mock.patch.object(bridge,"prepare",return_value=self.bundle), \
             mock.patch.object(bridge,"read_context",side_effect=self._read_at(watch)), \
             mock.patch.object(exchange,"_publish_export_file",side_effect=publishing):
            outcome=store.process_queue(k27.real_dossier_producer,now=base,limit=1)
        self.assertEqual(outcome,[(uid,"PARZIALE_LOCALE")])
        exports=[p.name for p in self.folder.iterdir() if p.is_file()]
        self.assertFalse(any(index.INDEX.fullmatch(name) for name in exports))
        row=store.dossier_status(uid)[0]
        self.assertIn("ExportGateRejected",row["publication_state"])
        self.assertIsNotNone(freeze.get(store,uid))
        self.assertEqual(store.status()["dossiers"]["PARZIALE_LOCALE"],1)

    def test_red_gpt_original_recovers_last_indexed_pair_despite_newer_orphan(self):
        """A newer dossier without index must not shadow valid indexed pair."""
        old_files,old_blobs=retrieval_fixture.publication_files(
            self.bundle,"old",drive_when=self.T)
        newer=copy.deepcopy(self.bundle)
        newer["preparato_utc"]=(self.T+dt.timedelta(seconds=1)).isoformat()
        new_files,new_blobs=retrieval_fixture.publication_files(
            newer,"orphan",drive_when=self.T+dt.timedelta(seconds=1))
        self.assertNotEqual(old_files[1]["name"],new_files[1]["name"])
        fake=retrieval_fixture.FakeDrive(
            retrieval_fixture.pages_from([*old_files,new_files[1]]),
            dict(old_blobs,**new_blobs))
        result=retriever.kdd_get_latest_verified_dossier(
            fake,retrieval_fixture.FOLDER,now=self.T+dt.timedelta(seconds=1))
        self.assertEqual(result["stato"],retriever.RECOVERED)
        self.assertEqual(result["file_id"],"old")
        self.assertEqual(fake.downloads,["old-index","old"])


if __name__=="__main__":
    unittest.main()
