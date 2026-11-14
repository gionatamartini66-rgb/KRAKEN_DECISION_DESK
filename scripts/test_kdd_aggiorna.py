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
            (directory / 'test_kdd_candles.py').write_text(
                'import unittest, pathlib\n'
                'class CandlesStaging(unittest.TestCase):\n'
                ' def test_module_present(self):\n'
                '  self.assertTrue(pathlib.Path("kdd_candles.py").is_file())\n'
            )
            (directory / 'test_kdd_economics.py').write_text(
                'import unittest, pathlib\n'
                'class EconomicStaging(unittest.TestCase):\n'
                ' def test_module_present(self):\n'
                '  self.assertTrue(pathlib.Path("kdd_economics.py").is_file())\n'
            )
            for name in kdd.PACKET_FILES:
                origin = Path(__file__).resolve().parents[1] / name
                # This updater fixture contains placeholder application modules;
                # package probes here test staging, while the real packet and
                # candlestick suites execute on genuine source in CI/preflight.
                if name.endswith('kdd_android_regressions.py'):
                    # The real updater executes this runner as an importable
                    # module, with both cwd and scripts/ available.
                    (directory / name).write_text('def main():\n    return None\n')
                elif name.endswith(('test_kdd_portfolio_4tf.py', 'test_kdd_bridge_g2.py', 'test_kdd_android_transaction_g2.py', 'test_kdd_drive_exchange.py', 'test_kdd_funding_book_g2.py', 'test_kdd_wallet_packet_g0.py')):
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

    def test_capability_preflight_failure_stops_before_any_functional_check(self):
        with patch.object(kdd,'capability_preflight',
                          side_effect=kdd.SafetyError('CAPACITY STOP')):
            with self.assertRaisesRegex(kdd.SafetyError,'CAPACITY STOP'):
                kdd.isolated_test(self.root)
        self.assertEqual((self.live/'README.md').read_text(),self.old_readme)

    def test_preflight_real_synthetic_file_flags_and_lock(self):
        with contextlib.redirect_stdout(io.StringIO()):
            kdd.capability_preflight()

    def test_preflight_truly_rejects_missing_os_nofollow(self):
        # Unlike a mock of the entire preflight, this removes the ACTUAL
        # capability and requires the preflight's own missing-flag guard.
        flag=kdd.os.O_NOFOLLOW
        try:
            del kdd.os.O_NOFOLLOW
            with self.assertRaisesRegex(kdd.SafetyError, 'capacita'):
                kdd.capability_preflight()
        finally:
            kdd.os.O_NOFOLLOW=flag


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
        private = home / '.local' / 'state' / 'kraken-decision-desk' / 'bridge' / 'outgoing'
        private.mkdir(parents=True, mode=0o700)
        (home / '.local' / 'state' / 'kraken-decision-desk').chmod(0o700)
        synthetic = private / '.pending-rollback-synthetic.json'
        evidence = b'G2 SYNTHETIC STATE MUST SURVIVE CODE ROLLBACK'
        synthetic.write_bytes(evidence)
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
        self.assertEqual(synthetic.read_bytes(), evidence)


    def test_rt42_deploy_01_missing_live_candles_check_and_apply_backup(self):
        name = "kdd_candles.py"
        self.assertIn(name, kdd.PY_FILES)
        self.assertIn("test_kdd_candles.py", kdd.PY_FILES)
        (self.live / name).unlink()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
        self.assertIn(name, output.getvalue())
        self.assertIn("PRECHECK OK", output.getvalue())
        self.assertFalse((self.live / name).exists())
        home = Path(self.tmp.name) / "isolated-home"
        home.mkdir()
        with patch.object(kdd.Path, "home", return_value=home), \
             patch("builtins.input", return_value="APPLICA"), \
             contextlib.redirect_stdout(io.StringIO()):
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
        self.assertEqual((self.live / name).read_bytes(),
                         (self.root / name).read_bytes())
        backups=list((home / ".local/share/kdd-deploy-backups").glob("*"))
        self.assertEqual(len(backups),1)
        self.assertFalse((backups[0] / name).exists(),
                         "A new module must not have invented prior backup bytes")

    def test_rt42_deploy_01_rollback_removes_new_candles_and_restores_old(self):
        name="kdd_candles.py"
        for existed in (False, True):
            with self.subTest(existed=existed):
                if existed:
                    (self.live/name).write_text("# old module\\n")
                else:
                    (self.live/name).unlink(missing_ok=True)
                old=(self.live/name).read_bytes() if existed else None
                home=Path(self.tmp.name)/("home-old" if existed else "home-new")
                home.mkdir()
                real=kdd.isolated_test
                calls=0
                def fail_post(stage):
                    nonlocal calls
                    calls+=1
                    if calls==2:
                        raise kdd.SafetyError("synthetic postflight failure")
                    return real(stage)
                with patch.object(kdd.Path,"home",return_value=home), \
                     patch.object(kdd,"isolated_test",side_effect=fail_post), \
                     patch("builtins.input",return_value="APPLICA"), \
                     contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(kdd.SafetyError,"rollback"):
                        kdd.apply(self.root,self.live,commit_sha=self.sha,dry_run=False)
                self.assertEqual((self.live/name).read_bytes() if existed else None,old)
                self.assertEqual((self.live/"README.md").read_text(),self.old_readme)
                backups=list((home/".local/share/kdd-deploy-backups").glob("*"))
                self.assertEqual(len(backups),1)
                self.assertEqual((backups[0]/name).read_bytes() if existed else None,old)


    def test_kdd17_capital_flow_missing_or_stale_stage_and_install(self):
        """The real new producer is importable from the updater's private stage."""
        name = 'kdd_capital_flow.py'
        self.assertIn(name, kdd.PY_FILES)
        self.assertIn(name, kdd.FILES)
        # Genuine module, not the placeholder created by synthetic setUp.
        source = (Path(__file__).resolve().parents[1] / name).read_bytes()
        (self.root / name).write_bytes(source)
        for existed in (False, True):
            with self.subTest(previous_file_existed=existed):
                old = b'# prior on-chain version\n' if existed else None
                if old is None:
                    (self.live / name).unlink(missing_ok=True)
                else:
                    (self.live / name).write_bytes(old)
                seen = []
                def inspect_stage(stage):
                    self.assertEqual((stage / name).read_bytes(), source)
                    spec = importlib.util.spec_from_file_location(
                        'kdd_capital_flow_deploy_probe', stage / name)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self.assertTrue(callable(module.collect))
                    self.assertTrue(callable(module.at_read))
                    seen.append(stage)
                with patch.object(kdd, 'isolated_test', side_effect=inspect_stage), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
                self.assertIn(name, output.getvalue())
                self.assertIn('PRECHECK OK', output.getvalue())
                self.assertEqual((self.live / name).read_bytes() if existed else None, old)
                self.assertEqual(len(seen), 1)
                home = Path(self.tmp.name) / ('capital-old-home' if existed else 'capital-new-home')
                home.mkdir()
                with patch.object(kdd.Path, 'home', return_value=home), \
                     patch.object(kdd, 'isolated_test', side_effect=inspect_stage), \
                     patch('builtins.input', return_value='APPLICA'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
                self.assertEqual((self.live / name).read_bytes(), source)
                self.assertEqual(len(seen), 3)  # check, preflight, postflight
                backup = list((home / '.local/share/kdd-deploy-backups').glob('*'))
                self.assertEqual(len(backup), 1)
                self.assertEqual((backup[0] / name).read_bytes() if existed else None, old)
                self.assertEqual((self.live / 'config.json').read_text(), '{}\n')
                self.assertIn('MANUALE LOCALE: DATO PRIVATO',
                              (self.live / 'README.md').read_text())

    def test_kdd17_capital_flow_rollback_old_or_absent(self):
        """Failure after replacement restores old bytes or removes new module."""
        name = 'kdd_capital_flow.py'
        source = (Path(__file__).resolve().parents[1] / name).read_bytes()
        (self.root / name).write_bytes(source)
        for existed in (False, True):
            with self.subTest(previous_file_existed=existed):
                old = b'# prior module bytes\n' if existed else None
                if old is None:
                    (self.live / name).unlink(missing_ok=True)
                else:
                    (self.live / name).write_bytes(old)
                home = Path(self.tmp.name) / ('capital-rollback-old' if existed
                                             else 'capital-rollback-new')
                home.mkdir()
                attempts = [0]
                def fail_postflight(stage):
                    attempts[0] += 1
                    if attempts[0] == 2:
                        self.assertEqual((stage / name).read_bytes(), source)
                        raise kdd.SafetyError('synthetic postflight failed')
                    self.assertEqual((stage / name).read_bytes(), source)
                with patch.object(kdd.Path, 'home', return_value=home), \
                     patch.object(kdd, 'isolated_test', side_effect=fail_postflight), \
                     patch('builtins.input', return_value='APPLICA'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(kdd.SafetyError, 'rollback'):
                        kdd.apply(self.root, self.live,
                                  commit_sha=self.sha, dry_run=False)
                self.assertEqual(attempts[0], 2)
                self.assertEqual((self.live / name).read_bytes() if existed else None, old)
                self.assertEqual((self.live / 'README.md').read_text(), self.old_readme)
                self.assertEqual((self.live / 'config.json').read_text(), '{}\n')
                backup = list((home / '.local/share/kdd-deploy-backups').glob('*'))
                self.assertEqual(len(backup), 1)
                self.assertEqual((backup[0] / name).read_bytes() if existed else None, old)


    def test_new_catalog_is_present_in_preflight_and_installed(self):
        """New JSON data must be tested, not just copied after preflight."""
        name = "kdd_project_catalog.json"
        payload = '{"schema":"kdd-project-catalog-v001","projects":{}}\n'
        (self.root / name).write_text(payload)
        (self.live / name).unlink()
        observed = []
        def inspect_stage(stage):
            self.assertEqual((stage / name).read_text(), payload)
            observed.append(stage)
        with patch.object(kdd, 'isolated_test', side_effect=inspect_stage), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
        self.assertIn('PRECHECK OK', out.getvalue())
        self.assertEqual(len(observed), 1)
        self.assertFalse((self.live / name).exists())
        home = Path(self.tmp.name) / 'catalog-install-home'
        home.mkdir()
        with patch.object(kdd.Path, 'home', return_value=home), \
             patch.object(kdd, 'isolated_test', side_effect=inspect_stage), \
             patch('builtins.input', return_value='APPLICA'), \
             contextlib.redirect_stdout(io.StringIO()):
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=False)
        self.assertEqual((self.live / name).read_text(), payload)
        self.assertEqual(len(observed), 3)
        self.assertEqual((self.live / 'README.md').is_file(), True)

    def test_r5_runner_resolves_both_import_roots_without_pythonpath(self):
        """Exercise the actual R5 launcher on a clean subprocess environment."""
        import os
        import subprocess
        real_command = kdd.command
        r5_seen = []
        def subprocess_with_clean_r5_environment(args, *, cwd, timeout=120):
            if any('kdd_android_regressions' in str(arg) for arg in args):
                r5_seen.append(tuple(args))
                env = os.environ.copy()
                env.pop('PYTHONPATH', None)
                return subprocess.run(args, cwd=cwd, text=True,
                                      capture_output=True, timeout=timeout, env=env)
            return real_command(args, cwd=cwd, timeout=timeout)
        with patch.object(kdd, 'capability_preflight'), \
             patch.object(kdd, 'command', side_effect=subprocess_with_clean_r5_environment), \
             contextlib.redirect_stdout(io.StringIO()):
            # apply() prepares the README fingerprint and private fixtures;
            # testing isolated_test(self.root) skips that required preparation.
            kdd.apply(self.root, self.live, commit_sha=self.sha, dry_run=True)
        self.assertEqual(len(r5_seen), 1)
        self.assertIn('from scripts.kdd_android_regressions import main',
                      ' '.join(r5_seen[0]))

    def test_issue43_economic_module_staged_prepost_and_rollback(self):
        name="kdd_economics.py"
        self.assertIn(name,kdd.PY_FILES)
        self.assertIn("test_kdd_economics.py",kdd.PY_FILES)
        self.assertIn("kdd_project_catalog.json", kdd.DATA_FILES)
        self.assertIn("kdd_project_catalog.json", kdd.FILES)
        self.assertIn(name,kdd.FILES)
        (self.live/name).unlink()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            kdd.apply(self.root,self.live,commit_sha=self.sha,dry_run=True)
        self.assertIn(name,output.getvalue())
        self.assertIn("PRECHECK OK",output.getvalue())
        self.assertFalse((self.live/name).exists())
        home=Path(self.tmp.name)/"issue43-home"
        home.mkdir()
        original=kdd.isolated_test
        count=0
        def fail_post(stage):
            nonlocal count
            count+=1
            if count==2:
                raise kdd.SafetyError("synthetic postflight")
            return original(stage)
        with patch.object(kdd.Path,"home",return_value=home), \
             patch.object(kdd,"isolated_test",side_effect=fail_post), \
             patch("builtins.input",return_value="APPLICA"), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(kdd.SafetyError,"rollback"):
                kdd.apply(self.root,self.live,commit_sha=self.sha,dry_run=False)
        self.assertFalse((self.live/name).exists())
        self.assertEqual((self.live/"README.md").read_text(),self.old_readme)

    def test_rt42_deploy_01_candles_suite_executed_by_runner(self):
        import subprocess
        commands=[]
        def capture(args, *, cwd, timeout=120):
            commands.append(tuple(args))
            return subprocess.CompletedProcess(args,0,"","OK")
        with patch.object(kdd,"capability_preflight"), \
             patch.object(kdd,"command",side_effect=capture):
            kdd.isolated_test(self.root)
        self.assertTrue(any("test_kdd_candles" in args for args in commands))
        self.assertTrue(any("test_kdd_economics" in args for args in commands))
    def test_rt1_f4_book_test_is_deployed_and_executed_in_pre_and_postflight(self):
        import subprocess
        name = "scripts/test_kdd_funding_book_g2.py"
        self.assertIn(name, kdd.PACKET_FILES)
        self.assertIn(name, kdd.FILES)
        self.assertTrue((self.root / name).is_file())
        actual = []
        def capture(args, *, cwd, timeout=120):
            actual.append((tuple(args), str(cwd)))
            return subprocess.CompletedProcess(args, 0, "", "OK")
        with patch.object(kdd, "capability_preflight"), \
             patch.object(kdd, "command", side_effect=capture):
            kdd.isolated_test(self.root)
        self.assertTrue(any(
            "test_kdd_funding_book_g2.py" in args
            for args, _ in actual), actual)

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
