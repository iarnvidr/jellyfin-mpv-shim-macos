"""Populate the pinned shader assets before installing the upstream package."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PINS = {
    'work/source': '7e9fd292459358dde12f054c24f79642ab5ec98f',
    'vendor/default-shader-pack': '9ab0195ece699680b422ec5bb2216d45e14c82b1',
}


def prepare():
    for path, expected in PINS.items():
        checkout = ROOT / path
        if not (checkout / '.git').exists():
            raise SystemExit('Run git submodule update --init --recursive first.')
        actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != expected:
            raise SystemExit(f'{path}: expected {expected}, got {actual}; update pins deliberately.')
    destination = ROOT / 'work/source/jellyfin_mpv_shim/default_shader_pack'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(ROOT / 'vendor/default-shader-pack', destination,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'))
    print('Pinned upstream and shader sources ready.')


if __name__ == '__main__':
    prepare()
