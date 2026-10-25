#!/usr/bin/env python3
"""PR20 preview: public-only Chrome demo on localhost:8766, not a KDD deploy.

Load only approved GitHub source blobs and local public Python/vendor sources,
plus a minimal public shortlist extracted from KDD's last market observation,
into a disposable private Termux directory. Never copy raw market snapshots,
config, T0, plans, portfolio, balance snapshots or credentials.
POST and KDD refresh are disabled.
The operational KDD localhost:8765 is not stopped or changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO = 'gionatamartini66-rgb/KRAKEN_DECISION_DESK'
PIN = 'c2ab411d38dfb0c2fee8327f6885e8d3c15b4e01'
APPROVED = {
    'serve.py': '37c33a1e94d65cf67eaf678f4c6a9a5d56b26026',
    'grafico_4h.py': '58cd52991067bebf67f3557c3c3577b707ffe6ea',
}
ASSETS = ('lightweight-charts-5.2.1.js', 'LIGHTWEIGHT_CHARTS_LICENSE.txt',
          'LIGHTWEIGHT_CHARTS_NOTICE.txt')
PORT = 8766

LAUNCH = '''import sys
import urllib.parse
from http.server import ThreadingHTTPServer
import serve
serve.PORT=8766
class PreviewHandler(serve.Handler):
    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == '/':
            if not self.check_host(): return
            self.send_response(302)
            self.send_header('Location','/mercati/spot')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            return
        super().do_GET()
    def do_POST(self):
        self.send_error(405,'Anteprima pubblica: nessun aggiornamento o ordine')
try:
    with ThreadingHTTPServer((serve.HOST, serve.PORT),PreviewHandler) as http:
        print('PREVIEW_G0_OPEN: http://127.0.0.1:8766/mercati/spot',flush=True)
        print('Apri Chrome Android, scegli la coppia, poi CTRL+C in Termux.',flush=True)
        http.serve_forever(poll_interval=0.3)
except KeyboardInterrupt:
    pass
except OSError:
    print('STOP_PREVIEW: porta 8766 non disponibile',file=sys.stderr)
    sys.exit(2)
'''

class Stop(Exception):
    pass


def git(mirror, *args, text=True):
    return subprocess.run(['git','-C',str(mirror),*args],
                          capture_output=True, text=text, check=False,
                          timeout=30)


def read_approved_blob(mirror, path, expected):
    result = git(mirror, 'cat-file','blob', PIN+':'+path, text=False)
    data = result.stdout
    if result.returncode or not data or len(data)>1_500_000:
        raise Stop('manca il sorgente verificato '+path)
    actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if actual != expected:
        raise Stop('sorgente Git diverso dalla versione verificata: '+path)
    return data


def regular(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1_500_000:
        raise Stop('file non conforme alla copia pubblica: '+path.name)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_public(src, dst):
    regular(src)
    dst.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    shutil.copyfile(src,dst)
    dst.chmod(0o600)


def copy_public_selection(live, stage):
    """Extract only the current scanner's public candidate fields, not the report."""
    src = live / 'ultima_rilevazione.json'
    if not src.exists():
        return False
    if src.is_symlink() or not src.is_file() or src.stat().st_size > 3_000_000:
        raise Stop('rilevazione KDD non conforme')
    try:
        original = json.loads(src.read_text(encoding='utf-8'))
    except (ValueError, OSError, UnicodeError):
        raise Stop('rilevazione KDD non leggibile') from None
    if not isinstance(original, dict):
        raise Stop('rilevazione KDD non valida')
    result = {
        'rilevazione_utc': str(original.get('rilevazione_utc') or '')[:40],
        'schede_v02': [],
    }
    cards = original.get('schede_v02')
    if isinstance(cards, list):
        for card in cards[:12]:
            if not isinstance(card, dict):
                continue
            public = {
                key: str(card.get(key) or '')[:300]
                for key in ('token', 'coppia_analisi', 'categoria',
                            'esito', 'perche_selezionato')
            }
            options = card.get('alternative')
            public['alternative'] = []
            if isinstance(options, list):
                for option in options[:12]:
                    if isinstance(option, dict):
                        public['alternative'].append({
                            'pair': str(option.get('pair') or '')[:90],
                            'pair_key': str(option.get('pair_key') or '')[:55],
                        })
            result['schede_v02'].append(public)
    # Only these keys leave the parent process. No portfolio, balances, or T0.
    target = stage / 'ultima_rilevazione.json'
    target.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    target.chmod(0o600)
    return True


def prepare(live, mirror, stage):
    if not live.is_dir() or live.is_symlink():
        raise Stop('cartella KDD operativa non trovata')
    if not mirror.is_dir() or not (mirror/'.git').is_dir():
        raise Stop('mirror Git non trovato')
    remote=git(mirror,'remote','get-url','origin')
    allowed={f'git@github.com:{REPO}.git',f'git@github.com:{REPO}',
             f'https://github.com/{REPO}.git',f'https://github.com/{REPO}'}
    if remote.returncode or remote.stdout.strip() not in allowed:
        raise Stop('mirror Git inatteso')
    present=git(mirror,'cat-file','-e',PIN+'^{commit}')
    if present.returncode:
        raise Stop('commit verificato assente nel mirror; aggiornare il ramo PR20')
    files=sorted(live.glob('*.py'))
    if not files or any(f.name=='config.json' for f in files):
        raise Stop('sorgenti del KDD non disponibili')
    assets=[live/'vendor'/name for name in ASSETS]
    for f in [*files,*assets]: regular(f)
    originals={str(f):digest(f) for f in [*files,*assets]}
    projected=sum(f.stat().st_size for f in [*files,*assets])+2_000_000
    if shutil.disk_usage(Path.home()).free < projected*2:
        raise Stop('spazio insufficiente per anteprima temporanea')
    for f in files:
        if f.name!='test_decision_desk.py':
            copy_public(f,stage/f.name)
    for name, blob in APPROVED.items():
        destination=stage/name
        destination.write_bytes(read_approved_blob(mirror,name,blob))
        destination.chmod(0o600)
    for f in assets:copy_public(f,stage/'vendor'/f.name)
    copy_public_selection(live, stage)
    # The only JSON is a tiny allowlisted PUBLIC shortlist for display.
    return originals


def main():
    mirror=Path.home()/'kraken-decision-desk'/'KDD_GITHUB_SAFE'
    live=Path.home()/'kraken-decision-desk'/'KRAKEN_DECISION_DESK_V001'
    print('PREVIEW_G0_PIN:',PIN,flush=True)
    print('PROGRAMMA_ORIGINALE: porta 8765 invariata',flush=True)
    with tempfile.TemporaryDirectory(prefix='kdd-pr20-preview-',dir=Path.home()) as tmp:
        stage=Path(tmp)
        stage.chmod(0o700)
        originals=prepare(live,mirror,stage)
        print('COPIA_TEMPORANEA: solo codice pubblico; POST disabilitato',flush=True)
        env=os.environ.copy()
        for key in list(env):
            if (key.startswith(('KRAKEN_','OPENAI_','DEEPSEEK_')) or
                key in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP',
                        'KDD_T0_TRUSTED_PROOF','KDD_T0_TRUSTED_SHA256')):
                env.pop(key,None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONNOUSERSITE']='1'
        try:
            result=subprocess.run([sys.executable,'-B','-u','-c',LAUNCH],
                                  cwd=stage,env=env,check=False)
        except KeyboardInterrupt:
            result=None
        finally:
            changed=[Path(p).name for p,was in originals.items() if digest(Path(p))!=was]
            if changed:
                raise Stop('file originali modificati durante anteprima: '+', '.join(changed))
        print('ANTEPRIMA_TERMINATA / ORIGINALI_INVARIATI',flush=True)
        if result is not None and result.returncode:
            return result.returncode
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (Stop,OSError,subprocess.TimeoutExpired) as e:
        print('STOP_PREVIEW_G0:',e,file=sys.stderr)
        sys.exit(2)
