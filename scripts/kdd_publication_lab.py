"""OFFLINE TEST-ONLY transaction model. NEVER imported by the KDD exporter.

All files live inside an internally created TemporaryDirectory. This is a
state-machine probe, NOT a publisher suitable for Android shared storage.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

NON_PUBBLICATO='NON_PUBBLICATO'
PUBBLICATO_CONFERMATO='PUBBLICATO_CONFERMATO'
PUBBLICAZIONE_INCERTA='PUBBLICAZIONE_INCERTA'
ERRORE_PRIMA_DELLA_PUBBLICAZIONE='ERRORE_PRIMA_DELLA_PUBBLICAZIONE'

@dataclass(frozen=True)
class Result:
    stato: str
    osservata_pubblicazione: bool
    errore: str | None
    dir_spostata: bool


def simulate(*, fail_stage: str | None=None, move_before_rename=False,
             callback: Callable[[Path,Path],None] | None=None) -> Result:
    """Only static fixture, no user paths, no APIs. Deliberately reproduces rename risk."""
    with tempfile.TemporaryDirectory(prefix='kdd-D2-G2R2-LAB-') as t:
        base=Path(t)
        d=base/'target'; d.mkdir()
        moved=base/'moved'
        name='mercato_kdd.json'
        tmp='.kdd-fixture.tmp'
        installed=False
        try:
            # No input can choose a path outside the private synthetic sandbox.
            with (d/tmp).open('x',encoding='utf8') as f:
                json.dump({'schema':'FIXTURE_TEST_ONLY','count':1},f)
                f.flush()
                if fail_stage=='fsync_file': raise OSError('synthetic fsync file')
                os.fsync(f.fileno())
            dirfd=os.open(d,os.O_RDONLY|os.O_DIRECTORY)
            try:
                if fail_stage=='fsync_pre': raise OSError('synthetic fsync pre')
                os.fsync(dirfd)
                if callback is not None: callback(d,moved)
                if move_before_rename:
                    d.rename(moved)
                if fail_stage=='rename': raise OSError('synthetic rename')
                os.rename(tmp,name,src_dir_fd=dirfd,dst_dir_fd=dirfd)
                installed=True
                if fail_stage=='fsync_post': raise OSError('synthetic fsync post')
                os.fsync(dirfd)
                confirmed=True
            finally:
                os.close(dirfd)
        except OSError as e:
            return Result(PUBBLICAZIONE_INCERTA if installed or fail_stage=='rename' else ERRORE_PRIMA_DELLA_PUBBLICAZIONE,
                          installed, str(e).split('synthetic ')[-1], moved.exists())
        return Result(PUBBLICATO_CONFERMATO if confirmed else NON_PUBBLICATO,
                      installed,None,moved.exists())