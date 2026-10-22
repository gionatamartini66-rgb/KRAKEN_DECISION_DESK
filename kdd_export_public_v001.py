#!/usr/bin/env python3
"""KDD D2/G2R1: manual public-counter export. No private APIs or trading.

Fail closed on missing directory-descriptor operations, unsafe destinations or
missing exact opt-in. Does not start FolderSync, polling or any network I/O.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat

SCHEMA = 'kdd_public_market_v002'
SOURCE_NAME = 'ultima_rilevazione.json'
OUTPUT_NAME = 'mercato_kdd.json'
ENV_OPT_IN = 'KDD_DRIVE_PUBLIC_EXPORT'
UTC = dt.timezone.utc
MAX_SOURCE_BYTES = 12_000_000
MAX_AGE = dt.timedelta(minutes=45)
CLOCK_TOLERANCE = dt.timedelta(seconds=90)
DEFAULT_DEST = Path('/storage/emulated/0/KDD_TEST_SAMSUNG')
_REQUIRED_FLAGS = ('O_NOFOLLOW', 'O_DIRECTORY', 'O_CLOEXEC')


class ExportError(Exception):
    """Export refused. Never includes the source contents or credentials."""


def parse_utc(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise ExportError('Timestamp KDD non testuale o assente')
    try:
        t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise ExportError('Timestamp KDD malformato') from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ExportError('Timestamp KDD senza fuso')
    return t.astimezone(UTC)


def nonnegative_int(obj: dict, key: str) -> int:
    v = obj.get(key)
    if type(v) is not int or not 0 <= v <= 200_000:
        raise ExportError('Contatore pubblico non valido: ' + key)
    return v


def _opt_in(environ=None) -> None:
    env = os.environ if environ is None else environ
    if env.get(ENV_OPT_IN) != '1':
        raise ExportError('Esportazione disabilitata: opt-in esatto richiesto')


def _safe_directory(absolute: Path) -> int:
    """Anchor each path component at / using O_NOFOLLOW directory descriptors.

    No Path.resolve() checks followed by pathname writes: all further I/O is
    relative to the pinned final descriptor. Unsupported FUSE/Android => STOP.
    """
    if any(not hasattr(os, name) for name in _REQUIRED_FLAGS):
        raise ExportError('Piattaforma priva di primitive anti-symlink')
    if not absolute.is_absolute() or any(p in ('.', '..') for p in absolute.parts):
        raise ExportError('Percorso non assoluto o ambiguo')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current = os.open('/', flags)
    try:
        for part in absolute.parts[1:]:
            try:
                following = os.open(part, flags, dir_fd=current)
            except (OSError, NotImplementedError, TypeError) as e:
                raise ExportError('Directory assente, sostituita o non sicura') from e
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def _pinned_target(dest_dir: Path) -> int:
    # Exact approved address, including ancestors; tests may explicitly patch
    # DEFAULT_DEST in a sealed temporary sandbox, not from CLI/environment.
    if os.fspath(dest_dir) != os.fspath(DEFAULT_DEST):
        raise ExportError('Destinazione diversa dal percorso approvato')
    # The containing directory must not be writable by other POSIX principals.
    # This checks Linux mode bits only; Android FUSE access semantics still
    # require a separate device-level security review before deployment.
    parent = _safe_directory(DEFAULT_DEST.parent)
    try:
        mode = os.fstat(parent).st_mode
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ExportError('Genitore della destinazione scrivibile da terzi')
    finally:
        os.close(parent)
    return _safe_directory(DEFAULT_DEST)


def _assert_anchored(fd: int) -> None:
    """Reject a swapped/moved destination; all publication uses fd-relative I/O."""
    other = _safe_directory(DEFAULT_DEST)
    try:
        a, b = os.fstat(fd), os.fstat(other)
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            raise ExportError('Destinazione sostituita durante la pubblicazione')
        if not stat.S_ISDIR(a.st_mode):
            raise ExportError('Destinazione non directory')
    finally:
        os.close(other)


def _read_source(source_dir: Path) -> dict:
    folder = _safe_directory(Path(source_dir))
    try:
        try:
            fd = os.open(SOURCE_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=folder)
        except (OSError, NotImplementedError, TypeError) as e:
            raise ExportError('Snapshot pubblico assente o symlink') from e
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or not 2 <= before.st_size <= MAX_SOURCE_BYTES:
                raise ExportError('Snapshot pubblico non regolare o oltre limite')
            # Bound the *actual read*, not a separate size check vulnerable to TOCTOU.
            with os.fdopen(os.dup(fd), 'rb') as inp:
                raw = inp.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(fd)
            if (len(raw) > MAX_SOURCE_BYTES or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)):
                raise ExportError('Snapshot variato o superiore al limite')
        finally:
            os.close(fd)
    finally:
        os.close(folder)
    try:
        result = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as e:
        raise ExportError('Snapshot JSON pubblico malformato') from e
    if not isinstance(result, dict):
        raise ExportError('Snapshot pubblico non oggetto JSON')
    return result


def prepare(source_dir: Path, now: dt.datetime | None = None) -> dict:
    now = dt.datetime.now(UTC) if now is None else now
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ExportError('Orologio non UTC-aware')
    now = now.astimezone(UTC)
    obj = _read_source(Path(source_dir))
    captured = parse_utc(obj.get('rilevazione_utc'))
    if captured > now + CLOCK_TOLERANCE:
        raise ExportError('Orario composizione KDD futuro oltre tolleranza')
    age = (now - captured).total_seconds()
    temporal = ('OROLOGIO_INCOERENTE_ENTRO_TOLLERANZA' if age < 0
                else 'OLTRE_45_MINUTI_ALL_EXPORT' if age > MAX_AGE.total_seconds()
                else 'ENTRO_45_MINUTI_ALL_EXPORT')
    return {
        'schema': SCHEMA,
        'tipo': 'mercato_pubblico_non_patrimoniale',
        'provenienza': 'snapshot KDD dichiarato; origine esterna non autenticata',
        'rilevazione_utc': captured.isoformat(timespec='microseconds'),
        'rilevazione_semantica': 'tempo composizione KDD, NON timestamp nativo Kraken',
        'esportazione_utc': now.isoformat(timespec='microseconds'),
        'stato_al_momento_esportazione': temporal,
        'freschezza': 'DA_RICALCOLARE_ALLA_LETTURA',
        'sincronizzazione_utc': None,
        'lettura_gpt_utc': None,
        'n_coppie_multi': nonnegative_int(obj, 'n_coppie_multi'),
        'n_token_multi': nonnegative_int(obj, 'n_token_multi'),
        'ordine_finanziario': False,
        'limiti': 'Nessun saldo, prezzo, ordine, timestamp exchange o garanzia di freschezza al consumo.',
    }


def freshness_at_read(doc: dict, read_utc: dt.datetime) -> dict:
    """Consumer contract. Never rely on archived labels to claim current data."""
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise ExportError('Schema consumer non riconosciuto')
    if not isinstance(read_utc, dt.datetime) or read_utc.tzinfo is None:
        raise ExportError('Tempo lettura non affidabile')
    current = read_utc.astimezone(UTC)
    acquired = parse_utc(doc.get('rilevazione_utc'))
    exported = parse_utc(doc.get('esportazione_utc'))
    if acquired > exported + CLOCK_TOLERANCE or exported > current + CLOCK_TOLERANCE:
        return {'stato': 'OROLOGIO_INCOERENTE', 'eta_secondi': None}
    seconds = (current - acquired).total_seconds()
    if seconds < 0:
        return {'stato': 'OROLOGIO_INCOERENTE', 'eta_secondi': None}
    return {'stato': 'CORRENTE_ALLA_LETTURA' if seconds <= MAX_AGE.total_seconds() else 'SCADUTO_ALLA_LETTURA',
            'eta_secondi': int(seconds)}


def _target_regular_or_absent(dirfd: int) -> None:
    try:
        entry = os.stat(OUTPUT_NAME, dir_fd=dirfd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except (OSError, TypeError, NotImplementedError) as e:
        raise ExportError('Impossibile verificare il file di output') from e
    if not stat.S_ISREG(entry.st_mode):
        raise ExportError('Output esistente non regolare o symlink')


def publish(source_dir: Path, dest_dir: Path, now: dt.datetime | None = None,
            *, environ: dict | None = None) -> dict:
    """One publication with exact opt-in. No pathname-based tempfile/rename."""
    _opt_in(environ)
    if not getattr(os, 'supports_dir_fd', None) or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd or os.rename not in os.supports_dir_fd:
        raise ExportError('Directory descriptor operations unavailable')
    directory = _pinned_target(Path(dest_dir))
    temp = None
    try:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError) as e:
            raise ExportError('Blocco concorrente o filesystem senza locking') from e
        _assert_anchored(directory)
        _target_regular_or_absent(directory)
        try:
            os.fsync(directory)  # test capability BEFORE any file publication
        except OSError as e:
            raise ExportError('Filesystem non garantisce fsync directory') from e
        payload = prepare(source_dir, now)
        # Validate after potentially slow source preparation; do not follow a
        # replacement symlink after validation.
        _assert_anchored(directory)
        temp = '.kdd_market_' + secrets.token_hex(16) + '.tmp'
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        except (OSError, NotImplementedError, TypeError) as e:
            raise ExportError('Impossibile creare temporaneo confinato') from e
        try:
            with os.fdopen(fd, 'wb') as stream:
                blob = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   allow_nan=False, indent=2) + '\n').encode('utf-8')
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            raise
        _assert_anchored(directory)
        _target_regular_or_absent(directory)
        try:
            os.rename(temp, OUTPUT_NAME, src_dir_fd=directory, dst_dir_fd=directory)
            temp = None
            # Fsync the containing directory where supported. A failed fsync
            # cannot undo a completed rename; document operational ambiguity.
            os.fsync(directory)
        except (OSError, NotImplementedError, TypeError) as e:
            raise ExportError('Pubblicazione atomica o fsync non supportata') from e
        _assert_anchored(directory)
        return payload
    finally:
        if temp is not None:
            try:
                os.unlink(temp, dir_fd=directory)
            except OSError:
                pass
        os.close(directory)


def export_if_enabled(source_dir: Path, *, dest_dir: Path = DEFAULT_DEST,
                      environ: dict | None = None) -> dict | None:
    env = os.environ if environ is None else environ
    if env.get(ENV_OPT_IN) != '1':
        return None
    return publish(source_dir, dest_dir, environ=env)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='KDD contatori pubblici: output rigorosamente confinato, opt-in 1.')
    ap.add_argument('--source-dir', type=Path, default=Path.home() / 'kraken-decision-desk' / 'KRAKEN_DECISION_DESK_V001')
    # No --dest-dir: no user-controlled destination path.
    args = ap.parse_args(argv)
    try:
        result = export_if_enabled(args.source_dir)
    except (ExportError, OSError) as e:
        print('STOP EXPORT MERCATO:', type(e).__name__)
        return 1
    if result is None:
        print('EXPORT DISABILITATO: opt-in esatto KDD_DRIVE_PUBLIC_EXPORT=1 richiesto')
        return 1
    print('EXPORT PUBBLICO | origine KDD', result['rilevazione_utc'],
          '| stato: DA_RICALCOLARE_ALLA_LETTURA')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())