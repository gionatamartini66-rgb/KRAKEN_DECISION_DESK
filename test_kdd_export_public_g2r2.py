"""D2/G2R2 fail-closed acceptance tests. Synthetic data, NO Android export."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import kdd_export_public_v001 as e

NOW=dt.datetime(2026,10,22,20,0,tzinfo=e.UTC)

class ExportG2R2Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.src=self.root/'runtime';self.src.mkdir()
        self.shared=self.root/'storage'/'emulated'/'0'/'KDD_TEST_SAMSUNG'
        self.shared.mkdir(parents=True)
        (self.src/e.SOURCE_NAME).write_text(json.dumps({
            'rilevazione_utc':'2026-10-22T19:59:00Z',
            'n_coppie_multi':1090,'n_token_multi':610,
            'portafoglio.json':'NEVER_EXPOSE_PORTFOLIO',
            'readonly.json':'NEVER_EXPOSE_KEY',
            'T0':'NEVER_EXPOSE_T0',
            'balances_latest.json':'NEVER_EXPOSE_BALANCES',
            'plans':'NEVER_EXPOSE_PLANS',
            'logs':'NEVER_EXPOSE_LOGS'}))
    def send(self,dest=None,environ=None):
        return e.publish(self.src,self.shared if dest is None else dest,NOW,
                         environ={e.ENV_OPT_IN:'1'} if environ is None else environ)
    def test_01_no_optin_no_publication(self):
        with self.assertRaises(e.ExportError):self.send(environ={})
        self.assertFalse(list(self.shared.iterdir()))
    def test_02_optin_is_not_publication_permission(self):
        with self.assertRaisesRegex(e.ExportError,'NON_PUBBLICATO'):self.send()
        self.assertFalse(list(self.shared.iterdir()))
    def test_03_no_rename_syscall_even_when_authorized(self):
        with mock.patch.object(e.os,'rename',side_effect=AssertionError('rename attempted')) as spy:
            with self.assertRaises(e.ExportError):self.send()
        spy.assert_not_called()
    def test_04_no_dirfd_open_even_with_optin(self):
        with mock.patch.object(e.os,'open',side_effect=AssertionError('write/open attempted')) as spy:
            with self.assertRaises(e.ExportError):self.send()
        spy.assert_not_called()
    def test_05_wrong_path_refused(self):
        outside=self.root/'outside';outside.mkdir()
        with self.assertRaises(e.ExportError):self.send(outside)
        self.assertFalse(list(outside.iterdir()))
    def test_06_symlink_ancestor_has_no_effect(self):
        fake=self.root/'alias';fake.symlink_to(self.shared.parent,target_is_directory=True)
        with self.assertRaises(e.ExportError):self.send(fake/'KDD_TEST_SAMSUNG')
        self.assertFalse(list(self.shared.iterdir()))
    def test_07_directory_rename_before_publish_does_not_publish(self):
        moved=self.root/'relocated';self.shared.rename(moved)
        with self.assertRaises(e.ExportError):self.send()
        self.assertFalse((moved/e.OUTPUT_NAME).exists())
    def test_08_directory_rename_in_final_window_is_not_reachable(self):
        # Verify there is no rename invocation at which a concurrent rename
        # could make the result escape to a second location.
        with mock.patch.object(e.os,'rename',side_effect=AssertionError('race window')) as spy:
            with self.assertRaises(e.ExportError):self.send()
        spy.assert_not_called()
        self.assertFalse((self.shared/e.OUTPUT_NAME).exists())
    def test_09_previously_valid_file_is_preserved(self):
        old=self.shared/e.OUTPUT_NAME;old.write_bytes(b'VALID_PREVIOUS')
        with self.assertRaises(e.ExportError):self.send()
        self.assertEqual(old.read_bytes(),b'VALID_PREVIOUS')
    def test_10_no_import_side_effect(self):
        with mock.patch.object(e.os,'rename',side_effect=AssertionError('should not rename')):
            import importlib;importlib.reload(e)
        self.assertFalse((self.shared/e.OUTPUT_NAME).exists())
    def test_11_cli_no_optin(self):
        with mock.patch.dict(os.environ,{e.ENV_OPT_IN:'0'}),contextlib.redirect_stdout(io.StringIO()):
            rc=e.main(['--source-dir',str(self.src)])
        self.assertEqual(rc,1)
        self.assertFalse((self.shared/e.OUTPUT_NAME).exists())
    def test_12_cli_even_with_optin_cannot_publish(self):
        with mock.patch.dict(os.environ,{e.ENV_OPT_IN:'1'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.main(['--source-dir',str(self.src)]),1)
    def test_13_invalid_env_values_off(self):
        for flag in ('true','yes','0',' 1 ',''):
            self.assertIsNone(e.export_if_enabled(self.src,environ={e.ENV_OPT_IN:flag}))
    def test_14_refresh_hook_on_fails_closed(self):
        with self.assertRaises(e.ExportError):
            e.export_if_enabled(self.src,environ={e.ENV_OPT_IN:'1'})
    def test_15_prepare_public_fields_only(self):
        doc=e.prepare(self.src,NOW)
        content=json.dumps(doc)
        for word in ('NEVER_EXPOSE_KEY','NEVER_EXPOSE_T0','NEVER_EXPOSE_BALANCES','NEVER_EXPOSE_PORTFOLIO','NEVER_EXPOSE_PLANS','NEVER_EXPOSE_LOGS'):
            self.assertNotIn(word,content)
        self.assertEqual(doc['schema'],'kdd_public_market_v002')
        self.assertEqual(doc['freschezza'],'DA_RICALCOLARE_ALLA_LETTURA')
    def test_16_stale_recomputed_at_consume(self):
        doc=e.prepare(self.src,NOW)
        self.assertEqual(e.freshness_at_read(doc,NOW+dt.timedelta(days=3))['stato'],'SCADUTO_ALLA_LETTURA')
    def test_17_future_skew_does_not_claim_fresh(self):
        path=self.src/e.SOURCE_NAME;doc=json.loads(path.read_text())
        doc['rilevazione_utc']=(NOW+dt.timedelta(seconds=89)).isoformat();path.write_text(json.dumps(doc))
        out=e.prepare(self.src,NOW)
        self.assertEqual(e.freshness_at_read(out,NOW)['stato'],'OROLOGIO_INCOERENTE')
    def test_18_symlink_source_rejected(self):
        real=self.src/'real.json';p=self.src/e.SOURCE_NAME;p.rename(real);p.symlink_to(real)
        with self.assertRaises(e.ExportError):e.prepare(self.src,NOW)
    def test_19_concurrent_callers_all_stopped(self):
        answers=[];barrier=threading.Barrier(8)
        def f():
            barrier.wait()
            try:self.send();answers.append('UNSAFE')
            except e.ExportError:answers.append('STOP')
        ts=[threading.Thread(target=f) for _ in range(8)]
        for t in ts:t.start()
        for t in ts:t.join(timeout=4)
        self.assertEqual(answers,['STOP']*8)
        self.assertFalse((self.shared/e.OUTPUT_NAME).exists())
    def test_20_no_private_file_paths_accessed(self):
        with mock.patch.object(e,'_read_source',side_effect=AssertionError('source read attempted')) as m:
            with self.assertRaises(e.ExportError):self.send()
        m.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)