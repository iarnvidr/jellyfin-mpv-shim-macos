import ast, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ManifestTests(unittest.TestCase):
 def test_generated_manifest_json_uses_real_newline(self):
  source=(ROOT/'work/build.py').read_text()
  self.assertIn("json.dumps(manifest,indent=2)+'\\n'",source)
  self.assertNotIn("+'\\\\n'",source)
 def test_packaging_verifier_rejects_malformed_manifest(self):
  tree=ast.parse((ROOT/'work/package.py').read_text())
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify_manifest')
  ns={'json':json,'re':__import__('re'),'VERSION':'1.2.3','Path':Path,'SystemExit':SystemExit}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'<manifest verifier>','exec'),ns)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'manifest.json'
   p.write_text('{\\n')
   with self.assertRaises(SystemExit): ns['verify_manifest'](p)
   p.write_text(json.dumps({'schema':1,'version':'1.2.3','python':'3','platform':'p','mpv':{'version':'x','url':'u','sha256':'0'*64,'executable':'Contents/Resources/mpv.app/Contents/MacOS/mpv'},'sparkle':{'version':'x','url':'u','sha256':'1'*64},'inputs':{'python_lock_sha256':'2'*64,'native_lock_sha256':'3'*64}})+ '\n')
   self.assertEqual(ns['verify_manifest'](p)['version'],'1.2.3')
