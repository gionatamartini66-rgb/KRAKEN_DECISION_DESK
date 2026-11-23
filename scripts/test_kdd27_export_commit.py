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
        return lambda bundle: self.real_read(bundle,now=when[0])

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
