"""Verify and execute the app recovered from each distributable, never re-sign it."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'work'))
from bundle_signing import verify_bundle


def command(*args, **kwargs):
    return subprocess.run(list(map(str,args)),check=True,**kwargs)


def check(app, kind, evidence):
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'extracted-signatures.json').write_text(json.dumps(verify_bundle(app),indent=2)+'\n')
    command(sys.executable,ROOT/'scripts/macos_smoke.py','--app',app,'--evidence',evidence)
    # A contaminated loader environment must not affect the actual application.
    poisoned={**os.environ, 'VK_DRIVER_FILES':'/opt/homebrew/share/vulkan/icd.d/MoltenVK_icd.json',
              'VK_ICD_FILENAMES':'/opt/homebrew/share/vulkan/icd.d/MoltenVK_icd.json',
              'VK_ADD_DRIVER_FILES':'/opt/homebrew/share/vulkan/icd.d/MoltenVK_icd.json',
              'DYLD_LIBRARY_PATH':'/opt/homebrew/lib'}
    command(sys.executable,ROOT/'scripts/macos_smoke.py','--app',app,'--evidence',evidence/'inherited-loaders',env=poisoned)
    print(f'{kind}: explicit signatures, native window, runtime icon, decoded Vulkan playback and inherited-loader isolation passed',flush=True)


def main():
    version=(ROOT/'VERSION').read_text().strip()
    out=ROOT/'outputs'
    evidence=out/'macos-smoke-evidence'
    with tempfile.TemporaryDirectory(prefix='jellyfin-distribution-') as directory:
        temporary=Path(directory)
        extracted=temporary/'zip'; extracted.mkdir()
        command('/usr/bin/ditto','-x','-k',out/f'Jellyfin-Player-{version}-Apple-Silicon.zip',extracted)
        check(extracted/'Jellyfin Player.app','Update ZIP',evidence/'zip')
        mount=temporary/'dmg'; mount.mkdir()
        command('/usr/bin/hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,out/f'Jellyfin-Player-macOS-{version}-Apple-Silicon.dmg')
        try:
            installed=temporary/'installed'/'Jellyfin Player.app'
            installed.parent.mkdir()
            command('/usr/bin/ditto',mount/'Jellyfin Player.app',installed)
            check(installed,'DMG',evidence/'dmg')
        finally:
            command('/usr/bin/hdiutil','detach',mount)


if __name__=='__main__': main()
