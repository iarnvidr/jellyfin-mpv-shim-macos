"""Build a self-contained Apple Silicon app with the upstream icon and player."""
from pathlib import Path
import subprocess
import plistlib
import shutil
import importlib.metadata
import platform
import sys

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
OUT = ROOT / 'outputs'
NAME = 'Jellyfin MPV Shim'
VERSION = (ROOT / 'VERSION').read_text().strip()
if sys.platform != 'darwin' or platform.machine() != 'arm64':
    raise SystemExit('Build on an Apple Silicon Mac with Xcode command line tools.')
if not Path('/opt/homebrew/bin/mpv').is_file():
    raise SystemExit('Install mpv with Homebrew first: brew install mpv')

subprocess.run(['swiftc', str(WORK / 'Updater.swift'), '-o', str(WORK / 'Mac Updater'),
                '-framework', 'AppKit'], check=True)
subprocess.run(['clang', '-dynamiclib', '-fobjc-arc', '-fblocks',
                str(WORK / 'NativeScroll.m'), '-o', str(WORK / 'native-scroll.dylib'),
                '-framework', 'Cocoa'], check=True)
metadata_args = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get('Name')
    if name and not name.startswith(('pyinstaller', 'altgraph', 'macholib')):
        metadata_args.extend(['--copy-metadata', name])
subprocess.run([
    str(WORK / 'build-env/bin/pyinstaller'), '--noconfirm', '--clean',
    '--windowed', '--onedir', '--name', NAME,
    '--osx-bundle-identifier', 'org.jellyfin.mpvshim.local',
    '--icon', str(WORK / 'source/jellyfin.icns'),
    '--collect-all', 'jellyfin_mpv_shim',
    '--collect-all', 'jellyfin_apiclient_python',
    '--collect-all', 'python_mpv_jsonipc',
    '--hidden-import', 'PIL.ImageFont',
    '--add-binary', '/opt/homebrew/bin/mpv:.',
    '--add-binary', str(WORK / 'native-scroll.dylib') + ':.',
    '--distpath', str(WORK / 'dist'),
    '--workpath', str(WORK / 'pyinstaller'),
    '--specpath', str(WORK),
    *metadata_args, str(WORK / 'launch.py'),
], check=True)
app = WORK / 'dist' / (NAME + '.app')
helper = app / 'Contents/Helpers/Mac Updater.app/Contents'
support = app / 'Contents/Resources/mac_support'
support.mkdir(parents=True, exist_ok=True)
for name in ['launch.py', 'mac_update.py', 'local_compat.py', 'runtime_update.py', 'managed_launch.py']:
    shutil.copy2(WORK / name, support / name)
shutil.copy2(WORK / 'source/jellyfin.icns', support / 'jellyfin.icns')
# PyInstaller's Frameworks/Resources cross-link keeps one resource path.
(app / 'Contents/Frameworks/mac_support').symlink_to('../Resources/mac_support')
(helper / 'MacOS').mkdir(parents=True, exist_ok=True)
shutil.copy2(WORK / 'Mac Updater', helper / 'MacOS/Mac Updater')
with (helper / 'Info.plist').open('wb') as f:
    plistlib.dump({'CFBundleExecutable': 'Mac Updater',
                  'CFBundleIdentifier': 'org.jellyfin.mpvshim.local.updater',
                  'CFBundleName': 'Jellyfin Updates', 'CFBundlePackageType': 'APPL',
                  'CFBundleVersion': '1', 'LSUIElement': True,
                  'NSHighResolutionCapable': True}, f)
plist = app / 'Contents/Info.plist'
with plist.open('rb') as f:
    info = plistlib.load(f)
info.update(CFBundleShortVersionString=VERSION, CFBundleVersion=VERSION,
            NSHighResolutionCapable=True,
            NSLocalNetworkUsageDescription='Discover and connect to your Jellyfin server.',
            NSBonjourServices=['_jellyfin._tcp'],
            CFBundleDisplayName=NAME)
with plist.open('wb') as f:
    plistlib.dump(info, f)
licenses = app / 'Contents/Resources/Licenses'
licenses.mkdir(exist_ok=True)
shutil.copy2(WORK / 'source/LICENSE.md', licenses / 'Jellyfin MPV Shim.txt')
subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
print('APP_READY', app, flush=True)
