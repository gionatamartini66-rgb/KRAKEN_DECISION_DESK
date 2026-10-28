"""Test locali dell'aggiornatore: non richiedono Termux, Kraken o rete."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'kdd_aggiorna', Path(__file__).parent / 'kdd_aggiorna.py')
kdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kdd)

TEST_BODY = '''import hashlib, pathlib, re, unittest
class TestApp(unittest.TestCase):
    def test_checkpoint(self):
        p=pathlib.Path.cwd()
        h=hashlib.sha256()
        for f in sorted(p.glob("*.py"),key=lambda p:p.name)+[p/"config.json"]:
            if f.exists(): h.update(f.name.encode()+b"\\0"+f.read_bytes()+b"\\0")
        a=re.search(r"<!-- CHECKPOINT_SORGENTI_SHA256: ([a-f0-9]{64}) -->",(p/"README.md").read_text())
        self.assertEqual(a.group(1),h.hexdigest())
'''


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'repo'
        self.live = base / 'KRAKEN_DECISION_DESK_V001'
        self.root.mkdir()
        self.live.mkdir()
        for name in kdd.FILES:
            for directory in (self.root, self.live):
                p = directory / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('# file ' + name + '\n')
        for directory in (self.root, self.live):
            (directory / 'test_decision_desk.py').write_text(TEST_BODY)
            for name in kdd.PACKET_FILES:
                origin = Path(__file__).resolve().parents[1] / name
                if name.endswith('test_kdd_portfolio_4tf.py'):
                    # The updater's synthetic source tree intentionally uses
                    # placeholder application code. Its staging test verifies
                    # packaging only; real E2E runs separately on true KDD.
                    (directory / name).write_text(
                        'import unittest\nclass PackageProbe(unittest.TestCase):\n'
                        '  def test_technical_module_staged(self):\n'
                        '    self.assertTrue(__import__("pathlib").Path("patrimonio_4tf.py").is_file())\n')
                else:
                    (directory / name).write_bytes(origin.read_bytes())
        (self.live / 'config.json').write_text('{}\n')
        sha = kdd.fingerprint(self.live)
        self.old_readme = 'MANUALE LOCALE: DATO PRIVATO\n<!-- CHECKPOINT_SORGENTI_SHA256: ' + sha + ' -->\n'
        (self.live / 'README.md').write_text(self.old_readme)
        (self.root / 'serve.py').write_text('# CHANGE on GitHub\n')
        self.sha = 'a'*40
        # BACKUP ROOT è sempre HOME/.local/share, qui isolato con la mock.

    def test_check_does_not_touch_original(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
        self.assertIn('PRECHECK OK', stream.getvalue())
        self.assertEqual((self.live / 'serve.py').read_text(), '# file serve.py\n')
        self.assertEqual((self.live / 'README.md').read_text(), self.old_readme)

    def test_apply_changes_code_and_updates_private_readme(self):
        home = Path(self.tmp.name) / 'fakehome'
        home.mkdir()
        with patch.object(kdd.Path, 'home', return_value=home), \
             patch('builtins.input', return_value='APPLICA'), \
             contextlib.redirect_stdout(io.StringIO()):
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
        self.assertEqual((self.live / 'serve.py').read_text(), '# CHANGE on GitHub\n')
        self.assertIn('MANUALE LOCALE: DATO PRIVATO', (self.live / 'README.md').read_text())
        self.assertIn('Commit codice (GitHub privato)', (self.live / 'README.md').read_text())
        self.assertIn(self.sha, (self.live / 'README.md').read_text())
        self.assertTrue(list((home / '.local/share/kdd-deploy-backups').glob('*/serve.py')))

    def test_rollback_when_postflight_fails(self):
        home = Path(self.tmp.name) / 'fakehome'
        home.mkdir()
        first = kdd.isolated_test
        seen = {'calls': 0}
        def fail_second(stage):
            seen['calls'] += 1
            if seen['calls'] == 2:
                raise kdd.SafetyError('test successivo KO')
            return first(stage)
        with patch.object(kdd.Path, 'home', return_value=home), \
             patch.object(kdd, 'isolated_test', side_effect=fail_second), \
             patch('builtins.input', return_value='APPLICA'), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(kdd.SafetyError, 'rollback'):
                kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
        self.assertEqual((self.live / 'serve.py').read_text(), '# file serve.py\n')
        self.assertEqual((self.live / 'README.md').read_text(), self.old_readme)

    def test_no_change_is_noop(self):
        (self.root / 'serve.py').write_text((self.live / 'serve.py').read_text())
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
        self.assertIn('già identico', stream.getvalue())

    def test_preflight_sees_private_fixtures_only_in_local_temp(self):
        """Regression: suite locale necessita piano GPT e portafoglio reali;
        sono disponibili nei test ma NON aggiunti al mirror GitHub."""
        sensitive = {
            'portafoglio.json': '{"dummy":"private-portfolio"}',
            'piano_gpt.json': '{"dummy":"private-plan"}',
            'migrazione_attesa.json': '{"dummy":"private-migration"}',
        }
        for name, body in sensitive.items():
            (self.live / name).write_text(body)
            self.assertFalse((self.root / name).exists())
        seen = []

        def observe(stage):
            for name, body in sensitive.items():
                self.assertEqual((stage / name).read_text(), body)
                seen.append(name)

        with patch.object(kdd, 'isolated_test', side_effect=observe), \
             contextlib.redirect_stdout(io.StringIO()):
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
        self.assertEqual(set(seen), set(sensitive))
        for name, body in sensitive.items():
            self.assertEqual((self.live / name).read_text(), body)
            self.assertFalse((self.root / name).exists())

    def test_private_fixture_symlink_is_refused(self):
        (self.live / 'portafoglio.json').symlink_to(self.live / 'config.json')
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(kdd.SafetyError, 'fixture locale symlink'):
                kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)


if __name__ == '__main__':
    unittest.main()
