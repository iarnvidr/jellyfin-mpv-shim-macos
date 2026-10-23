"""Check Python syntax and the actual integration contract with pinned upstream."""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
for directory in ('work', 'scripts'):
    for path in (ROOT / directory).glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
sys.path.insert(0, str(ROOT / 'work'))
import local_compat
import jellyfin_mpv_shim

local_compat.verify(Path(jellyfin_mpv_shim.__file__).parent)
print('Python syntax and pinned upstream integration contract passed.')
