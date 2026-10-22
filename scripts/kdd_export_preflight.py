#!/usr/bin/env python3
"""D2/G2R1 OFFLINE review gate. No deploy functionality, no Termux write.

Requires an existing *clean*, isolated clone on the reviewed experimental branch.
This preflight is not an alias of kdd-aggiorna and never invokes its apply().
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO='gionatamartini66-rgb/KRAKEN_DECISION_DESK'
BASE='a62ac221491494754577dca7e8fd19e1b39f8955'
BRANCH='experiments/kdd-drive-public-export-g2r1-20261022'
ALLOWED={
    '.gitignore','kdd_export_public_v001.py','test_kdd_export_public_v001.py',
    'test_kdd_export_public_g2r1.py','scripts/kdd_export_preflight.py',
    'scripts/test_kdd_export_preflight.py','KDD_D2_G2R1_REPORT.md',
}
REMOTE={f'https://github.com/{REPO}',f'https://github.com/{REPO}.git',
        f'git@github.com:{REPO}.git', f'git@github.com:{REPO}',
        f'ssh://git@github.com/{REPO}.git',f'ssh://git@github.com/{REPO}'}

class PreflightStop(Exception):pass

def git(root,*parts):
    result=subprocess.run(['git',*parts],cwd=root,capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise PreflightStop('Verifica Git fallita: '+ ' '.join(parts[:2]))
    return result.stdout.strip()

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
            raise PreflightStop('File G2R1 mancante nella allowlist Git: '+name)
    updater=(root/'scripts/kdd_aggiorna.py').read_text()
    ast.parse(updater)
    if "branch.stdout.strip() != 'main'" not in updater:
        raise PreflightStop('La regola main-only dell updater non è preservata')
    if 'test_kdd_export_public_v001' not in updater:
        raise PreflightStop('Regressioni originali non previste dal normale preflight')
    if (root/'scripts/kdd_aggiorna.py').is_symlink():
        raise PreflightStop('Updater non regolare')
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
    with tempfile.TemporaryDirectory(prefix='kdd-g2r1-preflight-') as work:
        stage=Path(work)
        stage.chmod(0o700)
        for name in ('kdd_export_public_v001.py','test_kdd_export_public_v001.py',
                     'test_kdd_export_public_g2r1.py'):
            src=root/name
            if src.is_symlink() or not src.is_file() or src.stat().st_size>2_000_000:
                raise PreflightStop('Sorgente test non valido')
            shutil.copy2(src,stage/name)
        simulate_checkpoint(stage)
        env=os.environ.copy()
        env.pop('KDD_DRIVE_PUBLIC_EXPORT',None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        done=subprocess.run([sys.executable,'-m','unittest','-q',
                             'test_kdd_export_public_v001','test_kdd_export_public_g2r1'],
                            cwd=stage,env=env,capture_output=True,text=True,timeout=90)
        if done.returncode:
            raise PreflightStop('Suite esperimento KO (nessun deploy)')
    return {'commit':sha,'modified_files':changes,'test_result':'PASS',
            'checkpoint':'SINTETICO_SOLO_STAGING',
            'backup_rollback':'DOCUMENTATI_UPDATER_ESISTENTE_NON_ESEGUITI',
            'operational_deploy':'NON_AUTORIZZATO'}

def main(argv=None):
    p=argparse.ArgumentParser(description='G2R1 preflight solo test, NO DEPLOY')
    p.add_argument('--commit',required=True)
    args=p.parse_args(argv)
    try:out=run(Path(__file__).resolve().parents[1],args.commit)
    except (PreflightStop,FileNotFoundError,OSError,subprocess.TimeoutExpired) as exc:
        print('STOP PREFLIGHT:',type(exc).__name__);return 2
    print('PREFLIGHT ESPERIMENTALE PASS:',out)
    return 0
if __name__=='__main__':raise SystemExit(main())