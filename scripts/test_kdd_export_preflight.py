"""Bounded C01 preflight security regressions without a remote or runtime."""
import contextlib,io,importlib.util
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
path=Path(__file__).with_name('kdd_export_preflight.py')
spec=importlib.util.spec_from_file_location('g2r1preflight',path)
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'scripts').mkdir()
        (self.root/'.gitignore').write_text('\n'.join('!/'+n for n in p.ALLOWED)+'\n')
        (self.root/'scripts/kdd_aggiorna.py').write_text("branch.stdout.strip() != 'main'\ntest_kdd_export_public_v001\n")
    def test_wrong_branch_refused(self):
        def f(root,*args):
            if args==('rev-parse','--show-toplevel'):return str(root.resolve())
            if args==('remote','get-url','origin'):return next(iter(p.REMOTE))
            if args==('branch','--show-current'):return 'main'
            return 'a'*40
        with patch.object(p,'git',side_effect=f):
            with self.assertRaisesRegex(p.PreflightStop,'ramo'):p.verify(self.root,'a'*40)
    def test_wrong_commit_refused(self):
        def f(root,*args):
            if args==('rev-parse','--show-toplevel'):return str(root.resolve())
            if args==('remote','get-url','origin'):return next(iter(p.REMOTE))
            if args==('branch','--show-current'):return p.BRANCH
            if args==('rev-parse','HEAD'):return 'b'*40
            return ''
        with patch.object(p,'git',side_effect=f):
            with self.assertRaisesRegex(p.PreflightStop,'HEAD'):p.verify(self.root,'a'*40)
    def test_main_only_rule_required(self):
        def f(root,*args):
            if args==('rev-parse','--show-toplevel'):return str(root.resolve())
            if args==('remote','get-url','origin'):return next(iter(p.REMOTE))
            if args==('branch','--show-current'):return p.BRANCH
            if args==('rev-parse','HEAD'):return 'a'*40
            if args==('status','--porcelain'):return ''
            if args==('diff','--name-only',p.BASE,'a'*40):return 'kdd_export_public_v001.py'
            return ''
        (self.root/'scripts/kdd_aggiorna.py').write_text('print(1)\n')
        with patch.object(p,'git',side_effect=f):
            with self.assertRaisesRegex(p.PreflightStop,'main-only'):p.verify(self.root,'a'*40)
    def test_extra_file_denied(self):
        def f(root,*args):
            if args==('rev-parse','--show-toplevel'):return str(root.resolve())
            if args==('remote','get-url','origin'):return next(iter(p.REMOTE))
            if args==('branch','--show-current'):return p.BRANCH
            if args==('rev-parse','HEAD'):return 'a'*40
            if args==('status','--porcelain'):return ''
            if args==('diff','--name-only',p.BASE,'a'*40):return 'portafoglio.json'
            return ''
        with patch.object(p,'git',side_effect=f):
            with self.assertRaisesRegex(p.PreflightStop,'fuori perimetro'):p.verify(self.root,'a'*40)
    def test_fake_checkpoint_does_not_read_private_files(self):
        (self.root/'kdd_export_public_v001.py').write_text('x=1')
        h=p.simulate_checkpoint(self.root)
        self.assertEqual(len(h),64)
        self.assertIn('FIXTURE SOLO PRE-FLIGHT',(self.root/'README.md').read_text())
        self.assertFalse((self.root/'portafoglio.json').exists())

if __name__=='__main__':unittest.main()