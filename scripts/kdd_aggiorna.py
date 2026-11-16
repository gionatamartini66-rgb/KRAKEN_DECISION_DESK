#!/usr/bin/env python3
"""KDD: deployment controllato, solo codice, da clone GitHub a Termux.

Nessuna operazione su Kraken, saldi, T0, dati o credenziali; nessuna scrittura su GitHub.
Esegue i test in una copia TEMPORANEA locale, installa file con sostituzioni
atomiche, riesegue i test e ripristina i sorgenti in caso di fallimento.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from time import monotonic

REPOSITORY = 'gionatamartini66-rgb/KRAKEN_DECISION_DESK'
PY_FILES = (
    'analisi_v02.py', 'binance_reference.py', 'costi_spot.py',
    'decision_desk.py', 'dossier_trade.py', 'flusso_spot.py',
    'grafico_4h.py', 'kdd_candles.py', 'kdd_capital_flow.py', 'kdd_economic_sources.py', 'kdd_economics.py', 'kdd_futures_flow.py',
    'kdd_network_defi.py', 'test_kdd_network_defi.py',
    'kdd_saldi.py', 'kraken_readonly.py',
    'patrimonio_4tf.py',
    'mercati_spot.py', 'piano_gpt.py', 'ricerca_setup.py',
    'serve.py', 'studio_delta.py', 'test_decision_desk.py',
    'test_kdd_candles.py', 'test_kdd_economic_sources.py', 'test_kdd_economics.py', 'test_kdd_futures_flow.py',
    'verifica_piani.py',
)
PACKET_FILES = (
    'scripts/kdd_wallet_packet_g0.py',
    'scripts/kdd_bridge_g2.py', 'scripts/kdd_drive_exchange.py',
    'scripts/test_kdd_drive_exchange.py', 'scripts/test_kdd_bridge_g2.py',
    'scripts/test_kdd_android_transaction_g2.py',
    'scripts/kdd_android_regressions.py',
    'scripts/test_kdd_wallet_packet_g0.py',
    'scripts/test_kdd_portfolio_4tf.py',
    'scripts/test_kdd_funding_book_g2.py',
)
VENDOR_FILES = (
    'vendor/lightweight-charts-5.2.1.js',
    'vendor/LIGHTWEIGHT_CHARTS_LICENSE.txt',
    'vendor/LIGHTWEIGHT_CHARTS_NOTICE.txt',
)
DATA_FILES = ('kdd_project_catalog.json',)
FILES = PY_FILES + DATA_FILES + PACKET_FILES + VENDOR_FILES
README = 'README.md'
CHECKPOINT_RE = re.compile(r'(?m)^<!-- CHECKPOINT_SORGENTI_SHA256: [a-f0-9]{64} -->$')


class SafetyError(RuntimeError):
    pass


def command(args: list[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    # Separate unittest processes need both import roots, in staging AND live.
    # Do not rely on PYTHONPATH set by Termux, CI or an interactive shell.
    env = None
    if args and args[0] == sys.executable:
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join((str(cwd.resolve()),
                                          str((cwd / 'scripts').resolve())))
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True,
                          timeout=timeout, check=False, env=env)


CORE_PREFLIGHT_TIMEOUT = 150
# Direct Samsung preflight: 150.1s STOP; isolated PASS in 146.3s.
# Headroom is specific to this module; other preflight tests stay at 150s.
DECISION_DESK_PREFLIGHT_TIMEOUT = 210
POSTFLIGHT_MAX_TIMEOUT = 300


def postflight_budget(preflight_seconds: float) -> int:
    """Bounded time budget derived from the same module's observed preflight.

    The baseline 150 seconds is unchanged. Up to twice the observed runtime
    plus 20s for post-install process-start/load variation, capped at 300s.
    A stuck test still times out; missing/invalid timings fail closed.
    """
    if (isinstance(preflight_seconds, bool)
            or not isinstance(preflight_seconds, (float, int))
            or not math.isfinite(preflight_seconds)
            or preflight_seconds <= 0):
        raise SafetyError('misura temporale preflight mancante o non valida')
    return min(POSTFLIGHT_MAX_TIMEOUT,
               max(CORE_PREFLIGHT_TIMEOUT, math.ceil(2 * preflight_seconds + 20)))


@contextmanager
def updater_lock():
    """Single updater across clones, --check and --apply; kernel releases on exit.

    Reuse the private KDD state location already checked by capability_preflight.
    The one private lock file carries no portfolio or credentials.
    """
    home = Path.home()
    state = home / '.local' / 'state' / 'kraken-decision-desk'
    for part in (home / '.local', home / '.local' / 'state', state):
        if part.is_symlink():
            raise SafetyError('aggiornatore: directory stato symlink')
        part.mkdir(mode=0o700, exist_ok=True)
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise SafetyError('aggiornatore: directory stato non regolare')
        if part == state and info.st_mode & 0o077:
            raise SafetyError('aggiornatore: directory stato non privata')
    fd = os.open(state / '.kdd-aggiorna.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise SafetyError('aggiornatore: file lock non regolare o non privato')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SafetyError('aggiornatore gia in esecuzione: STOP concorrenza') from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def verified_clone(root: Path) -> str:
    gitdir = command(['git', 'rev-parse', '--show-toplevel'], cwd=root)
    if gitdir.returncode or Path(gitdir.stdout.strip()).resolve() != root:
        raise SafetyError('il programma deve partire dal clone GitHub distinto dal KDD live')
    remote = command(['git', 'remote', 'get-url', 'origin'], cwd=root)
    urls = {
        f'git@github.com:{REPOSITORY}', f'git@github.com:{REPOSITORY}.git',
        f'https://github.com/{REPOSITORY}', f'https://github.com/{REPOSITORY}.git',
        f'ssh://git@github.com/{REPOSITORY}',
        f'ssh://git@github.com/{REPOSITORY}.git',
    }
    if remote.returncode or remote.stdout.strip() not in urls:
        raise SafetyError('origin GitHub non autorizzato')
    branch = command(['git', 'branch', '--show-current'], cwd=root)
    if branch.returncode or branch.stdout.strip() != 'main':
        raise SafetyError('solo ramo main controllato')
    status = command(['git', 'status', '--porcelain'], cwd=root)
    if status.returncode or status.stdout.strip():
        raise SafetyError('clone GitHub con modifiche locali: non aggiornare')
    sha = command(['git', 'rev-parse', 'HEAD'], cwd=root)
    if sha.returncode or not re.fullmatch(r'[a-f0-9]{40}', sha.stdout.strip()):
        raise SafetyError('commit Git non verificabile')
    return sha.stdout.strip()


def verify_sources(root: Path) -> None:
    for name in FILES:
        p = root / name
        if not p.is_file() or p.is_symlink():
            raise SafetyError(f'sorgente assente o symlink: {name}')
        if p.stat().st_size > 2_000_000:
            raise SafetyError(f'sorgente troppo grande: {name}')


def checksum(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(directory: Path) -> str:
    h = hashlib.sha256()
    paths = sorted(directory.glob('*.py'), key=lambda p: p.name)
    paths.append(directory / 'config.json')
    for path in paths:
        if not path.exists():
            continue
        h.update(path.name.encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def rewrite_readme(readme: str, fingerprint_hash: str, sha: str,
                   changed: list[str]) -> str:
    if len(CHECKPOINT_RE.findall(readme)) != 1:
        raise SafetyError('README operativo senza checkpoint unico: fermarsi')
    tag = f'<!-- CHECKPOINT_SORGENTI_SHA256: {fingerprint_hash} -->'
    current = CHECKPOINT_RE.sub(tag, readme)
    if not changed:
        return current
    time_utc = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    log = ('\n\n### Distribuzione controllata KDD — ' + time_utc + '\n'
           + f'Commit codice (GitHub privato): `{sha}`.\n'
           + f'File tecnici aggiornati: {", ".join(changed)}.\n'
           + 'Test isolati e test successivi obbligatori, rollback dei sorgenti '
           + 'previsto in caso di errore. Nessun dato privato trasferito.\n'
           + 'Nota: l\'installazione dei file non riavvia automaticamente '
           + 'il server già in esecuzione.\n')
    return current + log


def write_atomic(dest: Path, data: bytes, mode: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.kdd-next-', dir=dest.parent,
                                         delete=False) as tmp:
            temp_name = Path(tmp.name)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(temp_name, mode if mode is not None else 0o600)
        os.replace(temp_name, dest)
    finally:
        if temp_name is not None:
            temp_name.unlink(missing_ok=True)


def capability_preflight() -> None:
    """Filesystem capabilities before ANY functional test, in disposable Termux state.

    Does not touch KDD live documents, credentials or private outgoing/approvals.
    Tests same-device file/dir fsync, NOFOLLOW, O_EXCL, rename and flock;
    it never assumes os.link exists or that rename is no-replace.
    """
    import fcntl
    import stat
    home = Path.home()
    state = home / '.local' / 'state' / 'kraken-decision-desk'
    for part in (home / '.local', home / '.local' / 'state', state):
        if part.is_symlink():
            raise SafetyError('preflight: percorso stato Termux symlink')
        part.mkdir(mode=0o700, exist_ok=True)
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise SafetyError('preflight: percorso stato non regolare')
        if part == state and info.st_mode & 0o077:
            raise SafetyError('preflight: directory stato non privata')
    try:
        with tempfile.TemporaryDirectory(prefix='.kdd-android-cap-', dir=state) as tmp:
            root=Path(tmp)
            root.chmod(0o700)
            a=root/'a'; b=root/'b'
            essential=('O_EXCL','O_CREAT','O_NOFOLLOW','O_DIRECTORY')
            if not all(hasattr(os, n) for n in essential):
                raise SafetyError('capacita Termux mancanti: O_EXCL/O_NOFOLLOW/O_DIRECTORY')
            # prepare() also relies on dir_fd when opening the original
            # four KDD source files. Verify this capability before import.
            supports=getattr(os,'supports_dir_fd',set())
            if os.open not in supports or os.stat not in supports:
                raise SafetyError('capacita Termux mancante: dir_fd')
            fd=os.open(a,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(b'SYNTHETIC KDD CAPACITY\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                fd=os.open(a,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
                raise SafetyError('O_EXCL non preserva file esistenti')
            symlink=root/'symlink'
            symlink.symlink_to(root/'nonexistent')
            try:
                fd=os.open(symlink,os.O_RDONLY|os.O_NOFOLLOW)
            except OSError:
                pass
            else:
                os.close(fd)
                raise SafetyError('O_NOFOLLOW segue il symlink')
            os.rename(a,b)
            if a.exists() or b.read_bytes()!=b'SYNTHETIC KDD CAPACITY\n':
                raise SafetyError('rename same-directory non verificabile')
            probe_dir=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                probe_file=os.open('b',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=probe_dir)
                try:
                    opened=os.fstat(probe_file)
                    named=os.stat('b',dir_fd=probe_dir,follow_symlinks=False)
                    if (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino):
                        raise SafetyError('dir_fd inode inatteso')
                finally:
                    os.close(probe_file)
            finally:
                os.close(probe_dir)
            dfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                if not stat.S_ISDIR(os.fstat(dfd).st_mode):
                    raise SafetyError('directory non regolare')
                os.fsync(dfd)
            finally:
                os.close(dfd)
            if (stat.S_IMODE(b.stat().st_mode)!=0o600 or
                    stat.S_IMODE(root.stat().st_mode)!=0o700):
                raise SafetyError('permessi privati non rispettati')
            lockfd=os.open(root/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:
                fcntl.flock(lockfd,fcntl.LOCK_EX)
                # Distinct Python child must find the same inode locked.
                script=('import fcntl,os,sys; '
                        'fd=os.open(sys.argv[1],os.O_RDWR); '
                        'ok=False\n'
                        'try:\n fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
                        'except BlockingIOError:\n ok=True\n'
                        'sys.exit(0 if ok else 2)\n')
                proc=subprocess.run([sys.executable,'-B','-c',script,str(root/'lock')],
                                    timeout=12,check=False,capture_output=True)
                if proc.returncode:
                    raise SafetyError('flock fra processi non verificabile')
            finally:
                fcntl.flock(lockfd,fcntl.LOCK_UN)
                os.close(lockfd)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise SafetyError('preflight filesystem Android/Termux FALLITO') from exc


def isolated_test(staging: Path, *, phase: str = 'preflight',
                  reference_times: dict[str, float] | None = None) -> dict[str, float]:
    """Run every mandatory suite, record timings, and keep postflight bounded.

    Both flights use identical test commands. The postflight core timeout is
    derived only from the corresponding successful preflight module duration.
    It cannot run indefinitely and no failure is treated as a slow PASS.
    """
    if phase not in ('preflight', 'postflight'):
        raise SafetyError('fase di verifica non riconosciuta')
    if phase == 'postflight' and not isinstance(reference_times, dict):
        raise SafetyError('misure preflight non disponibili per postflight')
    try:
        capability_preflight()
    except SafetyError as exc:
        raise SafetyError('capability_preflight: ' + str(exc)) from None

    def checked(args: list[str], *, label: str, timeout: int = 120) -> float:
        started = monotonic()
        try:
            proc = command(args, cwd=staging, timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = monotonic() - started
            print(f'{phase} {label}: {elapsed:.1f}s / limite {timeout}s (TIMEOUT)')
            # TimeoutExpired.stdout/stderr can contain local private fixtures.
            raise SafetyError(f'{label}: timeout dopo {timeout} s') from None
        except OSError as exc:
            raise SafetyError(f'{label}: avvio impossibile ({type(exc).__name__}, '
                              f'errno={exc.errno})') from None
        elapsed = monotonic() - started
        print(f'{phase} {label}: {elapsed:.1f}s / limite {timeout}s')
        if proc.returncode:
            # Only approved unittest identifiers, never assertion bodies,
            # filesystem paths or private portfolio contents.
            matches = []
            for line in proc.stderr.splitlines():
                m = re.fullmatch(
                    r'(?:FAIL|ERROR): (test_[A-Za-z0-9_]{1,120}) '
                    r'\(([A-Za-z0-9_.]{1,140})\)', line.strip())
                if m:
                    matches.append(m.group(1))
            suffix = ('test ' + ', '.join(dict.fromkeys(matches[:3]))
                      if matches else f'codice_uscita={proc.returncode}')
            raise SafetyError(f'{label}: {suffix}')
        return elapsed

    core_modules = (
        'test_decision_desk', 'test_kdd_candles', 'test_kdd_economics',
        'test_kdd_economic_sources', 'test_kdd_futures_flow',
        'test_kdd_network_defi',
    )
    measurements: dict[str, float] = {}
    for module in core_modules:
        if phase == 'preflight':
            limit = (DECISION_DESK_PREFLIGHT_TIMEOUT
                     if module == 'test_decision_desk'
                     else CORE_PREFLIGHT_TIMEOUT)
        else:
            limit = postflight_budget(reference_times.get(module))
        measurements[module] = checked(
            [sys.executable, '-m', 'unittest', '-q', module],
            label='suite ' + module, timeout=limit)
    print('Test KDD: OK (tutti i sei moduli obbligatori)')

    packet_test = staging / 'scripts' / 'test_kdd_wallet_packet_g0.py'
    if (not packet_test.is_file()
            or not (staging / 'scripts/test_kdd_portfolio_4tf.py').is_file()
            or not (staging / 'scripts/test_kdd_funding_book_g2.py').is_file()):
        raise SafetyError('test del pacchetto, 4TF o book mancanti nello staging')
    if packet_test.exists():
        for pattern in ('test_kdd_wallet_packet_g0.py',
                        'test_kdd_portfolio_4tf.py',
                        'test_kdd_android_transaction_g2.py',
                        'test_kdd_funding_book_g2.py',
                        'test_kdd_drive_exchange.py'):
            checked([sys.executable, '-B', '-m', 'unittest', 'discover',
                     '-s', 'scripts', '-p', pattern, '-q'],
                    label='regressione ' + pattern)
        checked([sys.executable, '-B', '-c',
                 "import sys; sys.path.insert(0, 'scripts'); "
                 "from scripts.kdd_android_regressions import main; main()"],
                label='invarianti R5 mappati')
        print('Test pacchetto GPT / Android + R5 mappati: OK')
    return measurements



def service_alive() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', 8765), timeout=0.4):
            return True
    except (OSError, TimeoutError):
        return False


def apply(root: Path, live: Path, *, commit_sha: str, dry_run: bool) -> None:
    if not live.is_dir() or not (live / 'decision_desk.py').is_file():
        raise SafetyError('cartella programma KDD live non riconosciuta')
    if not (live / README).is_file() or not (live / 'config.json').is_file():
        raise SafetyError('README o configurazione KDD live mancanti')
    if live.resolve() == root.resolve() or root.resolve().is_relative_to(live.resolve()):
        raise SafetyError('il clone non può essere dentro la cartella live')
    verify_sources(root)
    current = {name: checksum(live / name) for name in FILES}
    changed = [name for name in FILES if current[name] != checksum(root / name)]
    print(f'Commit codice: {commit_sha}')
    print(f'File sorgenti differenti: {len(changed)}')
    for name in changed:
        print('  · ' + name)
    original_readme = (live / README).read_text(encoding='utf-8')
    if len(CHECKPOINT_RE.findall(original_readme)) != 1:
        raise SafetyError('checkpoint locale mancante o duplicato')
    if not changed:
        print('KDD live già identico al codice GitHub: nessun aggiornamento necessario.')
        return

    original_hashes = {name: checksum(live / name) for name in FILES}
    original_hashes['README.md'] = checksum(live / README)
    original_hashes['config.json'] = checksum(live / 'config.json')
    with tempfile.TemporaryDirectory(prefix='.kdd-verifica-', dir=live.parent) as stage_str:
        staging = Path(stage_str)
        staging.chmod(0o700)
        # Copia solo LOCALE: nessun dato viene inviato alla rete.
        # Prende TUTTI i .py residenti per preservare il fingerprint locale,
        # quindi sovrascrive solo i 16 file autorizzati.
        for src in live.glob('*.py'):
            if src.is_symlink():
                raise SafetyError('symlink Python nel programma live: intervento manuale richiesto')
            shutil.copy2(src, staging / src.name)
        # The curated project catalog is executable input to kdd_economics;
        # staging must contain the same version that will be installed.
        for name in PY_FILES + PACKET_FILES + DATA_FILES:
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, dest)
        # Alcuni test legacy verificano LO STATO LOCALE effettivo (piano GPT,
        # portafoglio e migrazione). Il clone GitHub non contiene questi file.
        # Sono copiati esclusivamente NEL TEMPORANEO LOCALE (0700), mai nello
        # staging Git o sulla rete; la cartella viene eliminata a fine prova.
        # Senza queste fixture i test danno falsi negativi e non certificano
        # davvero le regressioni. Non includere readonly.json/chiavi o altri
        # segreti: i test non ne hanno bisogno.
        for name in ('config.json', 'migrazione_attesa.json',
                     'portafoglio.json', 'piano_gpt.json'):
            original = live / name
            if original.is_symlink():
                raise SafetyError(f'fixture locale symlink: {name}')
            if original.is_file():
                shutil.copy2(original, staging / name)
        t0_path = 'storico_portafoglio/T0_2026-10-19_2301_KRAKEN_PRO.json'
        if (live / t0_path).exists():
            (staging / 'storico_portafoglio').mkdir()
            shutil.copy2(live / t0_path, staging / t0_path)
        source_readme = rewrite_readme(original_readme, fingerprint(staging),
                                       commit_sha, changed)
        (staging / README).write_text(source_readme, encoding='utf-8')
        print('Verifica preventiva isolata (programma live intatto)...')
        reference_times = isolated_test(staging)
        if dry_run:
            print('PRECHECK OK — nessuna modifica al programma. Rieseguire con --apply.')
            return
        print('ATTENZIONE: saranno aggiornati solo i file sopra e il checkpoint README.')
        answer = input('Per confermare digita APPLICA: ').strip()
        if answer != 'APPLICA':
            print('Annullato senza modifiche.')
            return
        for name, expected in original_hashes.items():
            if checksum(live / name) != expected:
                raise SafetyError(f'file live cambiato durante la verifica: {name}')
        # Backup privato, non in GitHub. Copiamo i file prima di toccare il live.
        backups = Path.home() / '.local' / 'share' / 'kdd-deploy-backups'
        backups.mkdir(parents=True, exist_ok=True)
        backups.chmod(0o700)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')
        backup = backups / f'{stamp}-{commit_sha[:10]}'
        if backup.exists():
            raise SafetyError('cartella backup già esistente; riprovare fra un secondo')
        backup.mkdir(mode=0o700)
        original_bytes: dict[str, bytes | None] = {}
        for name in changed + [README]:
            old = live / name
            original_bytes[name] = old.read_bytes() if old.exists() else None
            if old.exists():
                dest = backup / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, dest)
        # Apply + postflight. Solo i file in allowlist possono essere sostituiti.
        touched: list[str] = []
        phase = 'sostituzione sorgenti'
        try:
            for name in changed:
                dest = live / name
                if name.startswith('scripts/'):
                    parent = live / 'scripts'
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise SafetyError('directory scripts non regolare')
                    parent.mkdir(mode=0o700, exist_ok=True)
                if dest.is_symlink():
                    raise SafetyError(f'symlink nei file live: {name}')
                mode = (dest.stat().st_mode & 0o777) if dest.exists() else 0o600
                write_atomic(dest, (root / name).read_bytes(), mode)
                touched.append(name)
            write_atomic(live / README, source_readme.encode('utf-8'), 0o600)
            touched.append(README)
            # A source mismatch must stop before repeating the full suite.
            phase = 'integrita dei file installati'
            if fingerprint(live) != fingerprint(staging):
                raise SafetyError('impronta sorgenti postflight discordante')
            print('Verifica dopo la sostituzione...')
            phase = 'test postflight'
            isolated_test(live, phase='postflight', reference_times=reference_times)
            phase = 'integrita dopo test postflight'
            if fingerprint(live) != fingerprint(staging):
                raise SafetyError('impronta sorgenti postflight discordante dopo i test')
        except BaseException as e:
            # Never print exception string for untrusted OSError/TimeoutExpired,
            # which may embed private filesystem paths or captured test data.
            reason = str(e) if isinstance(e, SafetyError) else type(e).__name__
            print(f'ERRORE NEL DEPLOY [{phase}]: {reason}. '
                  'Ripristino i file originali...', file=sys.stderr)
            restore_errors = []
            for name in reversed(touched):
                try:
                    previous = original_bytes[name]
                    if previous is None:
                        (live / name).unlink(missing_ok=True)
                    else:
                        write_atomic(live / name, previous, 0o600)
                except OSError as exc:
                    restore_errors.append(
                        f'{name}: {type(exc).__name__} errno={exc.errno}')
            if restore_errors:
                raise SafetyError('RIPRISTINO INCOMPLETO, non avviare KDD: '
                                  + '; '.join(restore_errors)) from None
            raise SafetyError(f'postflight ({phase}): {reason}; '
                              'rollback sorgenti eseguito') from None
        print('AGGIORNAMENTO KDD COMPLETATO. Backup locale:', backup)
        if service_alive():
            print('IMPORTANTE: server Chrome in esecuzione; la nuova versione '
                  'di serve.py richiederà il suo riavvio controllato.')


def main() -> int:
    ap = argparse.ArgumentParser(description='Aggiornamento sicuro KDD da GitHub privato')
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='Test isolati, non tocca KDD')
    modes.add_argument('--apply', action='store_true', help='Richiede conferma APPLICA')
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    live = Path.home() / 'kraken-decision-desk' / 'KRAKEN_DECISION_DESK_V001'
    try:
        # The same Termux HOME lock is held across tests, install and rollback.
        # A second check/apply cannot race the first; abnormal exit releases it.
        with updater_lock():
            commit_sha = verified_clone(root)
            apply(root, live, commit_sha=commit_sha, dry_run=args.check)
    except (SafetyError, OSError, subprocess.TimeoutExpired) as exc:
        print('STOP SICUREZZA:', exc, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
