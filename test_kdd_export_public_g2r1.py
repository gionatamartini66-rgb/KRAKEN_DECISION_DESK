"""Independent G2R1 regressions reimplementing Sol's 16 published scenarios.
NOT claimed to be Sol's unavailable original test_redteam_additional.py bytes.
"""
import contextlib
import datetime as dt
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import kdd_export_public_v001 as exp

NOW=dt.datetime(2026,10,22,17,50,tzinfo=exp.UTC)
class ThreatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.s=base/'runtime';self.s.mkdir()
        self.d=base/'storage'/'emulated'/'0'/'KDD_TEST_SAMSUNG';self.d.mkdir(parents=True)
        self.o=base/'outsider';self.o.mkdir()
        self.raw={'rilevazione_utc':'2026-10-22T17:49:00Z','n_coppie_multi':10,'n_token_multi':5,
                  'wallet':{'secret':'SECRET_PRIVATE'},'T0':{'balance':10}}
        self.save()
        self.p=mock.patch.object(exp,'DEFAULT_DEST',self.d);self.p.start();self.addCleanup(self.p.stop)
    def save(self):
        (self.s/exp.SOURCE_NAME).write_text(json.dumps(self.raw))
    def on(self):return {exp.ENV_OPT_IN:'1'}
    def send(self):return exp.publish(self.s,self.d,NOW,environ=self.on())
    def test_01_strict_allowlist(self):
        doc=self.send(); text=(self.d/exp.OUTPUT_NAME).read_text()
        self.assertNotIn('SECRET_PRIVATE',text);self.assertNotIn('T0',text)
        self.assertEqual(doc['tipo'],'mercato_pubblico_non_patrimoniale')
    def test_02_wrong_parent_same_basename(self):
        wrong=self.o/'KDD_TEST_SAMSUNG';wrong.mkdir()
        with self.assertRaises(exp.ExportError):exp.publish(self.s,wrong,NOW,environ=self.on())
        self.assertFalse((wrong/exp.OUTPUT_NAME).exists())
    def test_03_ancestor_symlink(self):
        a=self.o/'KDD_TEST_SAMSUNG';a.mkdir()
        chain=self.o/'link';chain.symlink_to(self.d.parent,target_is_directory=True)
        fake=chain/'KDD_TEST_SAMSUNG'
        with self.assertRaises(exp.ExportError):exp.publish(self.s,fake,NOW,environ=self.on())
        self.assertFalse((a/exp.OUTPUT_NAME).exists())
    def test_04_source_ancestor_symlink(self):
        ancestor=self.o/'proxy';ancestor.symlink_to(self.s,target_is_directory=True)
        with self.assertRaises(exp.ExportError):exp.publish(ancestor,self.d,NOW,environ=self.on())
        self.assertFalse((self.d/exp.OUTPUT_NAME).exists())
    def test_05_future_89_seconds_not_current(self):
        self.raw['rilevazione_utc']=(NOW+dt.timedelta(seconds=89)).isoformat();self.save()
        doc=self.send()
        self.assertEqual(doc['stato_al_momento_esportazione'],'OROLOGIO_INCOERENTE_ENTRO_TOLLERANZA')
        self.assertEqual(exp.freshness_at_read(doc,NOW)['stato'],'OROLOGIO_INCOERENTE')
    def test_06_provenance_not_authenticated(self):
        doc=self.send()
        self.assertIn('non autenticata',doc['provenienza'])
        self.assertIn('NON timestamp nativo',doc['rilevazione_semantica'])
    def test_07_existing_file_preserved_after_rename_failure(self):
        target=self.d/exp.OUTPUT_NAME;target.write_text('PREVIOUS_VALID')
        with mock.patch.object(exp.os,'rename',side_effect=OSError('simulated')):
            with self.assertRaises(exp.ExportError):self.send()
        self.assertEqual(target.read_text(),'PREVIOUS_VALID')
        self.assertEqual(list(self.d.glob('.kdd_market_*')),[])
    def test_08_partial_output_cleanup(self):
        target=self.d/exp.OUTPUT_NAME;target.write_text('OLD')
        with mock.patch.object(exp.os,'fsync',side_effect=OSError('simulated')):
            with self.assertRaises(exp.ExportError):self.send()
        self.assertEqual(target.read_text(),'OLD')
        self.assertEqual(list(self.d.glob('.kdd_market_*')),[])
    def test_09_absent_flag_no_file_access(self):
        with mock.patch.object(exp,'_read_source',side_effect=AssertionError('SOURCE READ')):
            self.assertIsNone(exp.export_if_enabled(self.s,dest_dir=self.d,environ={}))
        with self.assertRaises(exp.ExportError):exp.publish(self.s,self.d,NOW,environ={})
    def test_10_process_environment_true_false(self):
        with mock.patch.dict(os.environ,{exp.ENV_OPT_IN:'false'}):
            self.assertIsNone(exp.export_if_enabled(self.s,dest_dir=self.d))
        with mock.patch.dict(os.environ,{exp.ENV_OPT_IN:'1'}):
            self.assertIsNotNone(exp.export_if_enabled(self.s,dest_dir=self.d))
    def test_11_cli_requires_flag(self):
        with mock.patch.dict(os.environ,{exp.ENV_OPT_IN:'0'}),contextlib.redirect_stdout(io.StringIO()):
            rc=exp.main(['--source-dir',str(self.s)])
        self.assertNotEqual(rc,0)
        self.assertFalse((self.d/exp.OUTPUT_NAME).exists())
    def test_12_swap_directory_during_prepare(self):
        d=self.d; moved=self.o/'moved_dir'
        original=exp.prepare
        def swap(*args,**kwargs):
            result=original(*args,**kwargs)
            d.rename(moved)
            d.symlink_to(moved,target_is_directory=True)
            return result
        with mock.patch.object(exp,'prepare',side_effect=swap):
            with self.assertRaises(exp.ExportError):self.send()
        self.assertFalse((moved/exp.OUTPUT_NAME).exists())
    def test_13_source_read_is_bounded_after_stat(self):
        large=self.s/exp.SOURCE_NAME
        large.write_bytes(b'{' + b' '*(exp.MAX_SOURCE_BYTES+1))
        with self.assertRaises(exp.ExportError):self.send()
        self.assertFalse((self.d/exp.OUTPUT_NAME).exists())
    def test_14_cached_freshness_3_days_later(self):
        doc=self.send()
        self.assertNotEqual(doc['freschezza'],'CORRENTE')
        self.assertEqual(exp.freshness_at_read(doc,NOW+dt.timedelta(days=3))['stato'],'SCADUTO_ALLA_LETTURA')
    def test_15_invalid_source_preserves_previous_without_fresh_flag(self):
        self.send()
        p=self.d/exp.OUTPUT_NAME;prior=p.read_bytes()
        self.raw['n_token_multi']=True;self.save()
        with self.assertRaises(exp.ExportError):self.send()
        self.assertEqual(prior,p.read_bytes())
        self.assertIn('DA_RICALCOLARE',p.read_text())
    def test_16_concurrent_writers_fail_or_atomic(self):
        statuses=[];barrier=threading.Barrier(10)
        def writer():
            barrier.wait()
            try:self.send();statuses.append('OK')
            except (exp.ExportError,OSError):statuses.append('STOP')
        threads=[threading.Thread(target=writer) for _ in range(10)]
        for x in threads:x.start()
        for x in threads:x.join()
        self.assertEqual(len(statuses),10)
        self.assertIn('OK',statuses)
        self.assertEqual(json.loads((self.d/exp.OUTPUT_NAME).read_text())['schema'],exp.SCHEMA)
    def test_17_direct_publish_requires_opt_in(self):
        with self.assertRaises(exp.ExportError):exp.publish(self.s,self.d,NOW,environ={})
    def test_18_cli_arbitrary_dest_rejected_by_parser(self):
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            exp.main(['--source-dir',str(self.s),'--dest-dir',str(self.o)])
    def test_19_no_fsync_fails_closed_before_publish(self):
        with mock.patch.object(exp.os,'fsync',side_effect=OSError('failed')):
            with self.assertRaises(exp.ExportError):self.send()
        self.assertFalse((self.d/exp.OUTPUT_NAME).exists())
    def test_20_missing_dirfd_capability(self):
        with mock.patch.object(exp.os,'supports_dir_fd',set()):
            with self.assertRaises(exp.ExportError):self.send()
    def test_21_final_symlink_blocked(self):
        symlink=self.d/exp.OUTPUT_NAME;symlink.symlink_to(self.o/'never')
        with self.assertRaises(exp.ExportError):self.send()
        self.assertTrue(symlink.is_symlink())
    def test_22_no_reset_known_good_on_source_corruption(self):
        self.send();original=(self.d/exp.OUTPUT_NAME).read_bytes()
        (self.s/exp.SOURCE_NAME).write_text('not json')
        with self.assertRaises(exp.ExportError):self.send()
        self.assertEqual((self.d/exp.OUTPUT_NAME).read_bytes(),original)

if __name__=='__main__':unittest.main(verbosity=2)