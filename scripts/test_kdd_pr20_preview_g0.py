import importlib.util, tempfile, unittest, sys, os, pathlib, subprocess, time, http.client, signal
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
  self.assertEqual({x.name for x in stage.iterdir()},{'decision_desk.py','serve.py','grafico_4h.py','piano_gpt.py','vendor'})
  self.assertEqual((stage/'serve.py').read_bytes(),b'# public synthetic\n')
  self.assertEqual(hashes[str(self.live/'serve.py')],p.digest(self.live/'serve.py'))
  self.assertFalse(any(stage.rglob('*.json')))
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
