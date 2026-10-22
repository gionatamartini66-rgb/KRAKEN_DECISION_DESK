"""D2-C02: real local Git clones, mock-only proof of updater behavior fixture.

Upstream updater code is checked by a pinned Git blob at real preflight time;
this test fixture is NOT that exact 14-KB upstream file.
"""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('preflight',Path(__file__).with_name('kdd_export_preflight.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class UpdaterSafety(Exception):pass


def command(args,root):
    return subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=7)


def main_only_fixture(root):
    """A behavioral fixture: real git branch command, not a string search."""
    x=command(['git','rev-parse','--show-toplevel'],root)
    if x.returncode or Path(x.stdout.strip()).resolve()!=root:
        raise UpdaterSafety('clone Git non valido')
    x=command(['git','remote','get-url','origin'],root)
    if x.returncode or x.stdout.strip() not in p.REMOTE:
        raise UpdaterSafety('origin non valido')
    x=command(['git','branch','--show-current'],root)
    if x.returncode or x.stdout.strip()!='main':
        raise UpdaterSafety('solo ramo main controllato')
    x=command(['git','status','--porcelain'],root)
    if x.returncode or x.stdout.strip():raise UpdaterSafety('dirty')
    return command(['git','rev-parse','HEAD'],root).stdout.strip()

class PreflightRealGitTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        root=Path(self.t.name)/'repo';root.mkdir()
        def g(*args):
            x=command(['git',*args],root)
            if x.returncode:raise AssertionError((args,x.stderr))
            return x.stdout.strip()
        g('init','--quiet','-b','main')
        g('config','user.name','Test Fixture')
        g('config','user.email','kdd-fixture@example.invalid')
        (root/'README.md').write_text('synthetic\n')
        (root/'scripts').mkdir()
        self.updater=root/'scripts'/'kdd_aggiorna.py'
        self.updater.write_text("# branch.stdout.strip() != 'main'\n# test_kdd_export_public_v001\nprint('fake updater')\n")
        g('add','.')
        g('commit','--quiet','-m','fixture main')
        self.base=g('rev-parse','HEAD')
        # Spoofable remote URL is intentionally text-only (not authenticated).
        g('remote','add','origin',f'https://github.com/{p.REPO}')
        g('switch','--quiet','-c',p.BRANCH)
        (root/'README.md').write_text('experimental\n')
        g('add','.')
        g('commit','--quiet','-m','fixture experiment')
        self.root=root
    def test_fake_updater_comment_strings_cannot_pass_blob_pin(self):
        with self.assertRaisesRegex(p.PreflightStop,'bytes'):
            p.assert_main_only_behavior(self.root,self.updater)
    def test_fake_updater_raises_only_unrelated_error_fails(self):
        def bad(root):raise UpdaterSafety('crash qualsiasi')
        with patch.object(p,'_updater_sha',return_value=p.UPDATER_BLOB_SHA),\
             patch.object(p.runpy,'run_path',return_value={'verified_clone':bad,'SafetyError':UpdaterSafety}):
            with self.assertRaisesRegex(p.PreflightStop,'non causato da main-only'):
                p.assert_main_only_behavior(self.root,self.updater)
    def test_fake_updater_accepts_experiment_fails(self):
        def bad(root):return self.base
        with patch.object(p,'_updater_sha',return_value=p.UPDATER_BLOB_SHA),\
             patch.object(p.runpy,'run_path',return_value={'verified_clone':bad,'SafetyError':UpdaterSafety}):
            with self.assertRaisesRegex(p.PreflightStop,'accetta il ramo sperimentale'):
                p.assert_main_only_behavior(self.root,self.updater)
    def test_real_git_semantics_experiment_rejected_main_accepted(self):
        # In this test only, inject the accurate branch-check behavior as an
        # excerpt fixture; no claim of a byte-identical upstream updater.
        with patch.object(p,'_updater_sha',return_value=p.UPDATER_BLOB_SHA),\
             patch.object(p.runpy,'run_path',return_value={'verified_clone':main_only_fixture,'SafetyError':UpdaterSafety}):
            p.assert_main_only_behavior(self.root,self.updater)
        self.assertEqual(command(['git','branch','--show-current'],self.root).stdout.strip(),p.BRANCH)
        self.assertEqual(command(['git','status','--porcelain'],self.root).stdout.strip(),'')
    def test_worktree_remains_clean_after_checks(self):
        before=command(['git','status','--porcelain'],self.root).stdout
        with patch.object(p,'_updater_sha',return_value=p.UPDATER_BLOB_SHA),\
             patch.object(p.runpy,'run_path',return_value={'verified_clone':main_only_fixture,'SafetyError':UpdaterSafety}):
            p.assert_main_only_behavior(self.root,self.updater)
        self.assertEqual(before,command(['git','status','--porcelain'],self.root).stdout)
        self.assertFalse(list(self.root.glob('**/*backups*')))
    def test_checkpoint_staging_is_synthetic(self):
        with tempfile.TemporaryDirectory() as d:
            h=p.simulate_checkpoint(Path(d))
            self.assertEqual(len(h),64)
            self.assertTrue((Path(d)/'README.md').exists())
    def test_preflight_accepts_no_apply_argument(self):
        with self.assertRaises(SystemExit):p.main(['--apply'])

if __name__=='__main__':unittest.main()