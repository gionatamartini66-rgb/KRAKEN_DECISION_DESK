#!/usr/bin/env python3
"""D2/G2R2 OFFLINE review gate. No deploy functionality, no Termux write.

Requires an existing *clean*, isolated clone on the reviewed experimental branch.
This preflight is not an alias of kdd-aggiorna and never invokes its apply().
"""
from __future__ import annotations
import argparse
import runpy
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO='gionatamartini66-rgb/KRAKEN_DECISION_DESK'
BASE='5c891a073eb4d2360a2e7d3a6740a7c44b6e43d4'
BRANCH='experiments/kdd-drive-public-export-g2r2-20261022'
ALLOWED={
    '.gitignore','kdd_export_public_v001.py',
    'test_kdd_export_public_g2r2.py',
    'scripts/kdd_export_preflight.py',
    'scripts/kdd_publication_lab.py',
    'scripts/test_kdd_export_preflight_g2r2.py',
    'scripts/test_kdd_publication_lab.py',
    'KDD_D2_G2R2_REPORT.md',
}
# Independently acquired at the G2R1 reviewed commit; do not trust a text search.
UPDATER_BLOB_SHA = '408e8f0328d35129021333df0fa9b99e8e8a4bc6'

REMOTE={f'https://github.com/{REPO}',f'https://github.com/{REPO}.git',
        f'git@github.com:{REPO}.git', f'git@github.com:{REPO}',
        f'ssh://git@github.com/{REPO}.git',f'ssh://git@github.com/{REPO}'}

class PreflightStop(Exception):pass

def git(root,*parts):
    result=subprocess.run(['git',*parts],cwd=root,capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise PreflightStop('Verifica Git fallita: '+ ' '.join(parts[:2]))
    return result.stdout.strip()

def _updater_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PreflightStop('Updater assente o symlink')
    contents=path.read_bytes()
    if len(contents)>2_000_000:
        raise PreflightStop('Updater oltre limite')
    return hashlib.sha1(b'blob '+str(len(contents)).encode()+b'\0'+contents).hexdigest()


def assert_main_only_behavior(root: Path, updater_path: Path) -> None:
    """Check real updater semantics on true Git branches, with pinned bytes.

    Only temporary local clones are mutated. In particular never call apply().
    The canonical URL text is not an authentication of the remote provider.
    """
    if _updater_sha(updater_path) != UPDATER_BLOB_SHA:
        raise PreflightStop('Updater bytes non identici al codice main-only verificato')
    ns=runpy.run_path(str(updater_path),run_name='kdd_preflight_readonly_verified')
    verified_clone=ns.get('verified_clone')
    safety_error=ns.get('SafetyError')
    if not callable(verified_clone) or not isinstance(safety_error,type):
        raise PreflightStop('Updater privo di contratto di sicurezza eseguibile')
    try:
        verified_clone(root)
    except safety_error as e:
        if 'solo ramo main controllato' not in str(e):
            raise PreflightStop('Rifiuto sperimentale non causato da main-only') from e
    else:
        raise PreflightStop('Updater accetta il ramo sperimentale: violazione main-only')
    # The same pinned function must *accept* main in a real clean Git clone.
    # A function that just raises SafetyError would otherwise fake a PASS.
    with tempfile.TemporaryDirectory(prefix='kdd-updater-git-test-') as base:
        clone=Path(base)/'test_clone'
        proc=subprocess.run(['git','clone','--quiet','--no-hardlinks',str(root),str(clone)],
                            capture_output=True,text=True,timeout=40)
        if proc.returncode:
            raise PreflightStop('Impossibile costruire clone Git temporaneo')
        proc=subprocess.run(['git','-C',str(clone),'switch','--quiet','-C','main','origin/main'],
                            capture_output=True,text=True,timeout=15)
        if proc.returncode:
            raise PreflightStop('Ramo main non disponibile per controprova')
        proc=subprocess.run(['git','-C',str(clone),'remote','set-url','origin',
                             f'https://github.com/{REPO}'],capture_output=True,text=True,timeout=15)
        if proc.returncode:
            raise PreflightStop('Remote sintetico per il clone temporaneo non impostabile')
        try:
            accepted=verified_clone(clone)
            head=git(clone,'rev-parse','HEAD')
        except (safety_error, OSError, subprocess.TimeoutExpired) as e:
            raise PreflightStop('Updater rifiuta main valido nel clone temporaneo') from e
        if accepted!=head:
            raise PreflightStop('Updater restituisce SHA errato per main')


def verify(root:Path,sha:str):
    if not re.fullmatch('[a-f0-9]{40}',sha):raise PreflightStop('SHA atteso non valido')
    if git(root,'rev-parse','--show-toplevel') != str(root.resolve()):
        raise PreflightStop('Non nel clone isolato')
    if git(root,'remote','get-url','origin') not in REMOTE:
        raise PreflightStop('Remote non canonico')
    if git(root,'branch','--show-current')!=BRANCH:
        raise PreflightStop('Il ramo sperimentale esatto è obbligatorio')
    if git(root,'rev-parse','HEAD')!=sha:
        raise PreflightStop('HEAD non coincide con SHA approvato per il controllo')
    if git(root,'status','--porcelain'):
        raise PreflightStop('Clone non pulito')
    git(root,'merge-base','--is-ancestor',BASE,sha)
    changed=set(git(root,'diff','--name-only',BASE,sha).splitlines())
    if not changed<=ALLOWED or not changed:
        raise PreflightStop('File modificati fuori perimetro')
    # Validate only approved KDD source list and Git allowlist.
    ignore=(root/'.gitignore').read_text()
    for name in ALLOWED:
        if '!/'+name not in ignore:
            raise PreflightStop('File G2R2 mancante nella allowlist Git: '+name)
    assert_main_only_behavior(root,root/'scripts/kdd_aggiorna.py')
    return sorted(changed)

def simulate_checkpoint(stage:Path):
    """Only a SYNTHETIC stand-in; does not validate the Samsung README."""
    (stage/'config.json').write_text('{}\n')
    h=hashlib.sha256()
    for f in sorted(stage.glob('*.py'),key=lambda p:p.name)+[stage/'config.json']:
        if f.exists():h.update(f.name.encode()+b'\0'+f.read_bytes()+b'\0')
    (stage/'README.md').write_text('FIXTURE SOLO PRE-FLIGHT\n'
       '<!-- CHECKPOINT_SORGENTI_SHA256: '+h.hexdigest()+' -->\n')
    assert len(re.findall(r'CHECKPOINT_SORGENTI_SHA256: ([a-f0-9]{64})',
            (stage/'README.md').read_text())) ==1
    return h.hexdigest()

def run(root:Path,sha:str):
    changes=verify(root,sha)
    with tempfile.TemporaryDirectory(prefix='kdd-g2r2-preflight-') as work:
        stage=Path(work)
        stage.chmod(0o700)
        for name in ('kdd_export_public_v001.py','test_kdd_export_public_g2r2.py',
                     'scripts/kdd_export_preflight.py','scripts/kdd_publication_lab.py',
                     'scripts/test_kdd_publication_lab.py',
                     'scripts/test_kdd_export_preflight_g2r2.py'):
            src=root/name
            if src.is_symlink() or not src.is_file() or src.stat().st_size>2_000_000:
                raise PreflightStop('Sorgente test non valido')
            dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dest)
        simulate_checkpoint(stage)
        env=os.environ.copy()
        env.pop('KDD_DRIVE_PUBLIC_EXPORT',None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        done=subprocess.run([sys.executable,'-m','unittest','-q',
                             'test_kdd_export_public_g2r2',
                             'scripts.test_kdd_publication_lab',
                             'scripts.test_kdd_export_preflight_g2r2'],
                            cwd=stage,env=env,capture_output=True,text=True,timeout=90)
        if done.returncode:
            raise PreflightStop('Suite esperimento KO (nessun deploy)')
    return {'commit':sha,'modified_files':changes,'test_result':'PASS_LOCALE_LIMITATO',
            'publisher_sharing':'NO_GO_ARCHITETTURALE',
            'updater_gate':'PIN_BLOB_E_MAIN_ONLY_COMPORTAMENTALE',
            'checkpoint':'SINTETICO_SOLO_STAGING',
            'backup_rollback':'DOCUMENTATI_UPDATER_ESISTENTE_NON_ESEGUITI',
            'operational_deploy':'NON_AUTORIZZATO',
            'origin_authenticity':'NON_DIMOSTRATA_DA_SOLI_GIT_REMOTE_STRING'}

def main(argv=None):
    p=argparse.ArgumentParser(description='G2R2 preflight solo test, NO DEPLOY')
    p.add_argument('--commit',required=True)
    args=p.parse_args(argv)
    try:out=run(Path(__file__).resolve().parents[1],args.commit)
    except (PreflightStop,FileNotFoundError,OSError,subprocess.TimeoutExpired) as exc:
        print('STOP PREFLIGHT:',type(exc).__name__);return 2
    print('PREFLIGHT ESPERIMENTALE PASS:',out)
    return 0
if __name__=='__main__':raise SystemExit(main())