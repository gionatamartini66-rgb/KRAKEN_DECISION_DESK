import importlib.util, tempfile, unittest, sys, os, pathlib, subprocess, time, http.client, signal, json
from unittest import mock
from pathlib import Path
spec=importlib.util.spec_from_file_location('preview',str(Path(__file__).with_name('kdd_pr20_preview_samsung_g0.py')))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class TestPreview(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.base=Path(self.t.name)
  self.live=self.base/'live'; self.live.mkdir()
  self.mirror=self.base/'mirror'; (self.mirror/'.git').mkdir(parents=True)
  for name in ('decision_desk.py','serve.py','grafico_4h.py','piano_gpt.py','test_decision_desk.py'):
   (self.live/name).write_text('SINTETICO=True\n')
  (self.live/'config.json').write_text('{"PRIVATE_SYNTHETIC":true}')
  (self.live/'portafoglio.json').write_text('{"PRIVATE_SYNTHETIC":true}')
  (self.live/'storico_portafoglio').mkdir()
  (self.live/'storico_portafoglio'/'T0.json').write_text('PRIVATE_SYNTHETIC')
  (self.live/'ultima_rilevazione.json').write_text(json.dumps({
    'rilevazione_utc':'2026-10-25T12:00:00+00:00',
    'saldo_refresh':{'secret':'PRIVATE_SYNTHETIC_NOT_FOR_PREVIEW'},
    'schede_v02':[{'token':'ADA','coppia_analisi':'ADA/USDT',
       'categoria':'consolidamento','esito':'RIESAME MIRATO',
       'perche_selezionato':'Controlla volumi', 'sintesi':'Serve chiusura oraria',
       'evidenze':['Volumi sopra la media'],'criticita':['Spread non verificato'],
       'quantita_privata':'PRIVATE_SYNTHETIC_NOT_FOR_PREVIEW',
       'alternative':[{'pair':'ADA/USDT','pair_key':'ADAUSDT',
          'prezzo_eur':0.13}]}]
  },ensure_ascii=False))
  (self.live/'vendor').mkdir()
  for a in p.ASSETS:(self.live/'vendor'/a).write_text('synthetic vendor')
 def tearDown(self):self.t.cleanup()
 def test_compile_launcher(self):compile(p.LAUNCH,'<launch>','exec')
 def test_prepare_omits_all_private_material(self):
  def git(repo,*a,**kw):
   return mock.Mock(returncode=0,stdout=f'git@github.com:{p.REPO}.git')
  stage=self.base/'stage';stage.mkdir()
  with mock.patch.object(p,'git',side_effect=git), mock.patch.object(p,'read_approved_blob',return_value=b'# public synthetic\n'):
   hashes=p.prepare(self.live,self.mirror,stage)
  self.assertEqual({x.name for x in stage.iterdir()},{'decision_desk.py','serve.py','grafico_4h.py','piano_gpt.py','vendor','ultima_rilevazione.json'})
  self.assertEqual((stage/'serve.py').read_bytes(),b'# public synthetic\n')
  self.assertEqual(hashes[str(self.live/'serve.py')],p.digest(self.live/'serve.py'))
  safe=json.loads((stage/'ultima_rilevazione.json').read_text())
  self.assertEqual(set(safe),{'rilevazione_utc','schede_v02'})
  self.assertEqual(safe['schede_v02'][0]['alternative'],
                   [{'pair':'ADA/USDT','pair_key':'ADAUSDT'}])
  self.assertEqual(safe['schede_v02'][0]['evidenze'],['Volumi sopra la media'])
  self.assertEqual(safe['schede_v02'][0]['criticita'],['Spread non verificato'])
  self.assertEqual(safe['schede_v02'][0]['sintesi'],'Serve chiusura oraria')
  self.assertNotIn('PRIVATE_SYNTHETIC_NOT_FOR_PREVIEW',
                   (stage/'ultima_rilevazione.json').read_text())
  self.assertFalse((stage/'config.json').exists())
  self.assertFalse((stage/'portafoglio.json').exists())
 def test_missing_public_snapshot_keeps_preview_usable(self):
  (self.live/'ultima_rilevazione.json').unlink()
  with mock.patch.object(p,'git',return_value=mock.Mock(returncode=0,stdout='git@github.com:'+p.REPO+'.git')), \
       mock.patch.object(p,'read_approved_blob',return_value=b'# public synthetic\\n'):
   stage=self.base/'stage';stage.mkdir()
   p.prepare(self.live,self.mirror,stage)
  self.assertFalse((stage/'ultima_rilevazione.json').exists())

 def test_bad_mirror_blocks(self):
  with self.assertRaisesRegex(p.Stop,'mirror'):
   p.prepare(self.live,self.base/'absent',self.base)
 def test_unavailable_reviewed_pin_blocks(self):
  def git(repo,*a,**kw):
   if a[:2]==('remote','get-url'):return mock.Mock(returncode=0,stdout=f'git@github.com:{p.REPO}.git')
   return mock.Mock(returncode=1,stdout='')
  with mock.patch.object(p,'git',side_effect=git),self.assertRaisesRegex(p.Stop,'commit verificato assente'):
   p.prepare(self.live,self.mirror,self.base)
 def test_wrong_blob_refused(self):
  x=b'raw source'
  with mock.patch.object(p,'git',return_value=mock.Mock(returncode=0,stdout=x)):
   with self.assertRaisesRegex(p.Stop,'diverso'):p.read_approved_blob(self.mirror,'serve.py','0000000000000000000000000000000000000000')
 def test_http_preview_disables_post(self):
  stage=self.base/'stage';stage.mkdir()
  (stage/'serve.py').write_text('''from http.server import BaseHTTPRequestHandler\nHOST='127.0.0.1'\nPORT=8765\nclass Handler(BaseHTTPRequestHandler):\n def check_host(self): return self.headers.get('Host')==f'{HOST}:{PORT}'\n def do_GET(self):\n  self.send_response(200);self.end_headers();self.wfile.write(b'PUBLIC ONLY')\n def do_POST(self): raise AssertionError('original POST invoked')\n def log_message(self,*args): pass\n''')
  proc=subprocess.Popen([sys.executable,'-B','-u','-c',p.LAUNCH],cwd=stage,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   for j in range(35):
    try:
     h=http.client.HTTPConnection('127.0.0.1',8766,timeout=1)
     h.request('GET','/mercati/spot');r=h.getresponse();data=r.read();h.close()
     if r.status==200:break
    except OSError:time.sleep(0.1)
   else:self.fail('preview did not bind')
   self.assertEqual(data,b'PUBLIC ONLY')
   h=http.client.HTTPConnection('127.0.0.1',8766,timeout=1)
   h.request('POST','/aggiorna');r=h.getresponse();r.read();h.close()
   self.assertEqual(r.status,405)
   h=http.client.HTTPConnection('127.0.0.1',8766,timeout=1)
   h.request('GET','/');r=h.getresponse();r.read();h.close()
   self.assertEqual(r.status,302)
   self.assertEqual(r.getheader('Location'),'/mercati/spot')
  finally:
   proc.send_signal(signal.SIGINT)
   try: proc.communicate(timeout=3)
   except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=3)

if __name__=='__main__':unittest.main(verbosity=2)
