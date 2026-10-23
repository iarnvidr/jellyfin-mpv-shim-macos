from pathlib import Path
import subprocess
import shutil
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT = ROOT / 'outputs'
VERSION = (ROOT / 'VERSION').read_text().strip()
if sys.platform != 'darwin':
    raise SystemExit('DMG packaging requires macOS.')
OUT.mkdir(exist_ok=True)
app = WORK / 'dist/Jellyfin MPV Shim.app'
stage = WORK / 'installer'
stage.mkdir(exist_ok=True)
if (stage / app.name).exists():
    shutil.rmtree(stage / app.name)
subprocess.run(['ditto', str(app), str(stage / app.name)], check=True)
if not (stage / 'Applications').exists():
    (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
(stage / 'Read Me.txt').write_text(f'Jellyfin MPV Shim macOS wrapper {VERSION} — Apple Silicon\n\n'
    'Drag Jellyfin MPV Shim to Applications, then open it.\n'
    'Python and mpv are included; no terminal setup is required.\n\n'
    'Enter your Jellyfin server address and sign in, or use Quick Connect.\n'
    'This local build is ad-hoc signed, not Apple notarized.\n'
    'Built and verified on macOS 27, Apple Silicon. Other versions are untested.\n'
    'Settings > General > Check for Updates installs components, not the Mac wrapper.\n'
    'Runtime activation/rollback is experimental; see the repository handoff.\n'
    'The updater includes prebuilt Python, stable mpv and Python dependencies.\n'
    'This is an unofficial local Mac package.\n\n'
    'Upstream: https://github.com/jellyfin/jellyfin-mpv-shim/tree/v3.1.0\n'
    'License: GPL-3.0-or-later. See Contents/Resources/Licenses inside the app.\n')
dmg = OUT / f'Jellyfin-MPV-Shim-macOS-{VERSION}-Apple-Silicon.dmg'
subprocess.run(['hdiutil', 'create', '-volname', 'Jellyfin MPV Shim',
    '-srcfolder', str(stage), '-format', 'UDZO', '-ov', str(dmg)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
print(json.dumps({'installer': str(dmg), 'bytes': dmg.stat().st_size}))
