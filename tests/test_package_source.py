import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_source', ROOT / 'work/package.py')
# Importing the executable packaging module is inappropriate off macOS;
# source archive helpers are tested via its AST-extracted declarations.
import ast
module = ast.parse((ROOT / 'work/package.py').read_text())
selected = [n for n in module.body if isinstance(n, (ast.FunctionDef, ast.Import, ast.ImportFrom))]
namespace = {'__file__': str(ROOT / 'work/package.py'), 'ROOT': ROOT}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / 'work/package.py'), 'exec'), namespace)

class SourceArchive(unittest.TestCase):
    def test_tracks_only_files_and_is_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import subprocess
            subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'scripts').mkdir(); (root/'scripts/build.py').write_text('print(1)\n')
            (root/'.python-version').write_text('3.13\n'); (root/'uv.lock').write_text('lock\n')
            (root/'work').mkdir(); (root/'work/generated').write_text('must omit')
            subprocess.run(['git','-C',str(root),'add','scripts','.python-version','uv.lock'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=test','-c','user.email=test@example.com','commit','-qm','fixture'],check=True)
            with tempfile.TemporaryDirectory() as out:
                a,b=Path(out)/'a.zip',Path(out)/'b.zip'
                fn=namespace['make_source_zip']; fn(a,root); fn(b,root)
                self.assertEqual(a.read_bytes(), b.read_bytes())
                with zipfile.ZipFile(a) as z:
                    names=set(z.namelist())
                    self.assertIn('scripts/build.py',names)
                    self.assertIn('.python-version',names); self.assertIn('uv.lock',names)
                    self.assertNotIn('work/generated',names)
                    self.assertIn('SOURCE-MANIFEST.json',names)

if __name__ == '__main__': unittest.main()
