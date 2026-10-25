"""G0, fully synthetic checks for the KDD PR20 local preflight.
No Kraken API, Google Drive, Android shared storage, or live KDD access.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).with_name('kdd_pr20_preflight_g0_20261025.py')
spec=importlib.util.spec_from_file_location('kdd_preflight',SCRIPT)
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class G0PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='kdd-test-g0-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.mirror=self.root/'KDD_GITHUB_SAFE'
        self.mirror.mkdir()
        self.live=self.root/'KRAKEN_DECISION_DESK_V001'
        self.live.mkdir()
        for f in ('decision_desk.py','serve.py','grafico_4h.py','test_decision_desk.py'):
            (self.live/f).write_text('# synthetic only\n')
        (self.live/'config.json').write_text('{"synthetic":true}')
        (self.live/'portafoglio.json').write_text(json.dumps({'t0_id':'T0_2026-10-19_0800_KRAKEN_PRO'}))
        (self.live/'README.md').write_text('<!-- CHECKPOINT_SORGENTI_SHA256: '+'0'*64+' -->\n')
        (self.live/'vendor').mkdir()
        for f in p.ASSETS:
            (self.live/'vendor'/f).write_text('synthetic')
        (self.live/'storico_portafoglio').mkdir()
        (self.live/'storico_portafoglio'/'T0_2026-10-19_0800_KRAKEN_PRO.json').write_text('{}')
        (self.live/'piano_gpt.json').write_text('SECRET_TEST_ONLY')
        (self.live/'migrazione_attesa.json').write_text('SECRET_MIG_TEST_ONLY')

    def test_source_pin_values(self):
        self.assertEqual(p.PIN,'8948faffe097bdfcbd1f4cbdd12fc6e9849448b9')
        self.assertEqual(p.FILES['serve.py'],'c09fd8acb4ff95a44497d55c4c935be04578a8d1')

    def test_local_input_validates(self):
        p.validate_local(self.live)

    def test_local_symlink_refused(self):
        (self.live/'config.json').unlink()
        (self.live/'config.json').symlink_to(self.live/'README.md')
        with self.assertRaises(p.Stop): p.validate_local(self.live)

    def test_missing_attestation_does_not_pass(self):
        with mock.patch.dict('os.environ',{},clear=True):
            self.assertFalse(p.has_independent_proof())
        with mock.patch.dict('os.environ',{p.TRUST_PROOF:'a'*24},clear=True):
            self.assertTrue(p.has_independent_proof())

    def test_local_proof_prompt_is_not_persisted(self):
        with mock.patch.dict('os.environ', {}, clear=True), \
             mock.patch.object(p.getpass, 'getpass', return_value='c'*24):
            p.obtain_historical_proof()
            self.assertEqual(__import__('os').environ.get(p.TRUST_PROOF), 'c'*24)
        self.assertNotIn('c'*24, (self.live/'README.md').read_text())

    def test_bad_local_proof_is_rejected(self):
        with mock.patch.dict('os.environ', {}, clear=True), \
             mock.patch.object(p.getpass, 'getpass', return_value='invalid'):
            with self.assertRaisesRegex(p.Stop, 'format invalid'):
                p.obtain_historical_proof()

    def test_present_proof_skips_prompt(self):
        with mock.patch.dict('os.environ', {p.TRUST_PROOF:'d'*24}, clear=True), \
             mock.patch.object(p.getpass, 'getpass', side_effect=AssertionError('prompt unnecessary')):
            p.obtain_historical_proof()

    def test_staging_avoids_unneeded_private_documents(self):
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)
            with mock.patch.object(p,'get_blob',return_value=b'# approved source\n'), \
                 mock.patch.dict('os.environ',{p.TRUST_PROOF:'b'*24},clear=True):
                p.stage_private(self.live,stage,self.mirror)
            self.assertEqual((stage/'serve.py').read_bytes(),b'# approved source\n')
            self.assertTrue((stage/'portafoglio.json').exists())
            self.assertTrue((stage/'storico_portafoglio'/'T0_2026-10-19_0800_KRAKEN_PRO.json').exists())
            self.assertFalse((stage/'piano_gpt.json').exists())
            self.assertFalse((stage/'migrazione_attesa.json').exists())
            self.assertEqual((stage/'config.json').stat().st_mode&0o777,0o600)
            self.assertIn(p.source_fingerprint(stage),(stage/'README.md').read_text())

    def test_existing_pinned_commit_requires_no_fetch(self):
        result=mock.Mock(returncode=0,stdout='',stderr='')
        resultsha=mock.Mock(returncode=0,stdout='')
        expected=p.FILES
        def git(repo,*args,**kw):
            if args[:2]==('cat-file','-e'): return result
            if args[:1]==('rev-parse',):
                fname=args[1].split(':',1)[1]
                return mock.Mock(returncode=0,stdout=expected[fname]+'\n')
            raise AssertionError('unexpected git call: '+str(args))
        with mock.patch.object(p,'git',side_effect=git) as cmd:
            p.fetch_pinned(self.mirror)
            self.assertEqual(cmd.call_count,1+len(expected))

    def test_branch_diverged_rejected_if_not_local(self):
        calls=0
        def git(repo,*args,**kw):
            nonlocal calls
            if args[:2]==('cat-file','-e'):
                calls+=1
                return mock.Mock(returncode=1 if calls==1 else 0,stdout='')
            if args[0]=='fetch': return mock.Mock(returncode=0,stdout='')
            if args[:2]==('rev-parse','FETCH_HEAD'):
                return mock.Mock(returncode=0,stdout='deadbeef'*5+'\n')
            if args[:2]==('merge-base','--is-ancestor'):
                return mock.Mock(returncode=1,stdout='')
            raise AssertionError(args)
        with mock.patch.object(p,'git',side_effect=git), self.assertRaisesRegex(p.Stop,'no longer descends'):
            p.fetch_pinned(self.mirror)

    def test_docs_only_branch_advance_does_not_invalidate_pinned_code(self):
        calls=0
        def git(repo,*args,**kw):
            nonlocal calls
            if args[:2]==('cat-file','-e'):
                calls+=1
                return mock.Mock(returncode=1 if calls==1 else 0,stdout='')
            if args[0]=='fetch': return mock.Mock(returncode=0,stdout='')
            if args[:2]==('rev-parse','FETCH_HEAD'):
                return mock.Mock(returncode=0,stdout='a'*40+'\n')
            if args[:2]==('merge-base','--is-ancestor'):
                return mock.Mock(returncode=0,stdout='')
            if args[:1]==('rev-parse',):
                name=args[1].split(':',1)[1]
                return mock.Mock(returncode=0,stdout=p.FILES[name]+'\n')
            raise AssertionError(args)
        with mock.patch.object(p,'git',side_effect=git):
            p.fetch_pinned(self.mirror)
        self.assertEqual(calls,2)

    def test_small_staging_budget(self):
        budget=p.staging_budget(self.live,self.mirror)
        self.assertLess(budget,7_000_000)
        with mock.patch.object(p.shutil,'disk_usage',return_value=mock.Mock(free=0)):
            with self.assertRaisesRegex(p.Stop,'storage'):
                p.staging_budget(self.live,self.mirror)

    def test_test_runner_rejects_skips(self):
        out='Ran 158 tests in 1.0s\n\nOK (skipped=2)\n'
        with mock.patch.object(p.subprocess,'run',return_value=mock.Mock(stdout='',stderr=out,returncode=0)), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(p.Stop,'skipped'):
                p.execute_tests(self.live)

    def test_test_runner_accepts_158_without_skips(self):
        out='Ran 158 tests in 1.0s\n\nOK\n'
        buf=io.StringIO()
        with mock.patch.object(p.subprocess,'run',return_value=mock.Mock(stdout='',stderr=out,returncode=0)), \
             contextlib.redirect_stdout(buf):
            p.execute_tests(self.live)
        self.assertIn('G0_REGRESSION_LOCAL: PASS',buf.getvalue())

    def test_t0_original_is_checked_even_when_suite_does_not_fail(self):
        t0 = self.live / 'storico_portafoglio' / 'T0_2026-10-19_0800_KRAKEN_PRO.json'
        def corrupt_synthetic_t0(_stage):
            t0.write_text('{"synthetic_corruption":true}')
        with mock.patch.object(p,'validate_git_mirror'), \
             mock.patch.object(p,'fetch_pinned'), \
             mock.patch.object(p,'execute_tests', side_effect=corrupt_synthetic_t0), \
             mock.patch.object(p,'stage_private'), \
             mock.patch.dict('os.environ',{p.TRUST_PROOF:'a'*24},clear=True), \
             mock.patch('pathlib.Path.home',return_value=self.root), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(p.Stop, 'live source/README/fixture changed'):
                p.preflight(self.mirror,self.live)

    def test_test_runner_does_not_inherit_pythonpath(self):
        calls=[]
        def fake_run(*args, **kwargs):
            calls.append(kwargs['env'])
            return mock.Mock(stdout='',stderr='Ran 158 tests in 0.1s\n\nOK\n',returncode=0)
        with mock.patch.object(p.subprocess, 'run', side_effect=fake_run), \
             mock.patch.dict('os.environ',{'PYTHONPATH':'/tmp/other', 'PYTHONHOME':'/tmp/external'},clear=False), \
             contextlib.redirect_stdout(io.StringIO()):
            p.execute_tests(self.live)
        self.assertNotIn('PYTHONPATH',calls[0]); self.assertNotIn('PYTHONHOME',calls[0])

    def test_failure_still_checks_originals(self):
        # The actual executable is not run against Termux: mock external git/test
        # and demonstrate that a failed check still compares original hashes.
        with mock.patch.object(p,'validate_git_mirror'), \
             mock.patch.object(p,'fetch_pinned'), \
             mock.patch.object(p,'execute_tests',side_effect=p.Stop('synthetic test failed')), \
             mock.patch.object(p,'stage_private'), \
             mock.patch.dict('os.environ',{p.TRUST_PROOF:'a'*24},clear=True), \
             mock.patch('pathlib.Path.home',return_value=self.root), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(p.Stop,'synthetic test failed'):
                p.preflight(self.mirror,self.live)

    def test_failure_and_actual_mutation_is_detected(self):
        def failing(stage):
            (self.live/'serve.py').write_text('# changed by synthetic test\n')
            raise p.Stop('failed test')
        with mock.patch.object(p,'validate_git_mirror'), \
             mock.patch.object(p,'fetch_pinned'), \
             mock.patch.object(p,'execute_tests',side_effect=failing), \
             mock.patch.object(p,'stage_private'), \
             mock.patch.dict('os.environ',{p.TRUST_PROOF:'a'*24},clear=True), \
             mock.patch('pathlib.Path.home',return_value=self.root), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(p.Stop,'live source/README/fixture changed'):
                p.preflight(self.mirror,self.live)

if __name__=='__main__':
    unittest.main(verbosity=2)
