from pathlib import Path
import hashlib, importlib.metadata, json, os, platform, plistlib, shutil, subprocess, sys, urllib.request
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'
NAME='Jellyfin MPV Shim'; VERSION=(ROOT/'VERSION').read_text().strip()
LOCK=dict(line.split('=',1) for line in (WORK/'native-dependencies.lock').read_text().splitlines() if line and not line.startswith('#'))
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def command(*a): subprocess.run(a,check=True)
if sys.platform!='darwin' or platform.machine()!='arm64': raise SystemExit('Build on Apple Silicon macOS.')
# Fetch through Homebrew rather than urllib: GHCR requires an anonymous
# OCI bearer-token challenge, which urllib does not implement. Homebrew's
# bottle downloader handles that public registry flow. Verify the exact
# cached artifact against the reviewed lock before installation.
formula=json.loads(urllib.request.urlopen(LOCK['MPV_SOURCE']).read())
bottle=formula['bottle']['stable']['files']['arm64_sequoia']
if bottle['sha256']!=LOCK['MPV_ARCHIVE_SHA256'] or formula['versions']['stable'] not in LOCK['MPV_REVISION']: raise SystemExit('mpv formula provenance changed')
command('brew','fetch','--force','--bottle-tag=arm64_sequoia','--retry','mpv')
mpv=Path(subprocess.check_output(['brew','--cache','--bottle','mpv'],text=True).strip())
if not mpv.is_file(): raise SystemExit(f'mpv bottle missing from Homebrew cache: {mpv}')
if digest(mpv)!=LOCK['MPV_ARCHIVE_SHA256']: raise SystemExit('mpv bottle hash mismatch')
command('brew','install','mpv')
mpvbin=Path(subprocess.check_output(['brew','--prefix','mpv'],text=True).strip())/'bin/mpv'
if not mpvbin.is_file(): raise SystemExit('mpv executable missing')
sparkle=WORK/'Sparkle-2.10.0.tar.xz'
if not sparkle.exists(): urllib.request.urlretrieve(LOCK['SPARKLE_URL'],sparkle)
if digest(sparkle)!=LOCK['SPARKLE_SHA256']: raise SystemExit('Sparkle SHA-256 mismatch')
command('tar','-xf',str(sparkle),'-C',str(WORK))
command('swiftc',str(WORK/'Updater.swift'),'-o',str(WORK/'Mac Updater'),'-F',str(WORK),'-framework','AppKit','-framework','Sparkle','-Xlinker','-rpath','-Xlinker','@executable_path/../../../Frameworks')
command('clang','-dynamiclib','-fobjc-arc','-fblocks',str(WORK/'NativeScroll.m'),'-o',str(WORK/'native-scroll.dylib'),'-framework','Cocoa')
metadata=[]
for d in importlib.metadata.distributions():
 n=d.metadata.get('Name')
 if n and not n.lower().startswith(('pyinstaller','altgraph','macholib')): metadata.extend(['--copy-metadata',n])
command(str(ROOT/'.venv/bin/pyinstaller'),'--noconfirm','--clean','--windowed','--onedir','--name',NAME,'--osx-bundle-identifier','org.jellyfin.mpvshim.local','--icon',str(WORK/'source/jellyfin.icns'),'--collect-all','jellyfin_mpv_shim','--collect-all','jellyfin_apiclient_python','--collect-all','python_mpv_jsonipc','--hidden-import','PIL.ImageFont','--add-binary',str(mpvbin)+':.','--add-binary',str(WORK/'native-scroll.dylib')+':.','--distpath',str(WORK/'dist'),'--workpath',str(WORK/'pyinstaller'),'--specpath',str(WORK),*metadata,str(WORK/'launch.py'))
app=WORK/'dist'/(NAME+'.app'); support=app/'Contents/Resources/mac_support'; support.mkdir(parents=True,exist_ok=True)
for n in ['launch.py','mac_update.py','local_compat.py','runtime_update.py','managed_launch.py']:
 if (WORK/n).exists(): shutil.copy2(WORK/n,support/n)
shutil.copy2(WORK/'source/jellyfin.icns',support/'jellyfin.icns'); (app/'Contents/Frameworks/mac_support').symlink_to('../Resources/mac_support')
helper=app/'Contents/Helpers/Mac Updater.app/Contents'; helper.joinpath('MacOS').mkdir(parents=True,exist_ok=True); shutil.copy2(WORK/'Mac Updater',helper/'MacOS/Mac Updater')
with helper.joinpath('Info.plist').open('wb') as f: plistlib.dump({'CFBundleExecutable':'Mac Updater','CFBundleIdentifier':'org.jellyfin.mpvshim.local.updater','CFBundleName':'Jellyfin Updates','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSUIElement':True},f)
shutil.copytree(WORK/'Sparkle.framework',app/'Contents/Frameworks/Sparkle.framework',symlinks=True)
notices=app/'Contents/Resources/Licenses'; notices.mkdir(exist_ok=True)
for c in WORK.glob('*Sparkle*'):
 if c.is_file() and any(k in c.name.lower() for k in ('license','notice','readme')): shutil.copy2(c,notices/c.name)
shutil.copy2(WORK/'source/LICENSE.md',notices/'Jellyfin MPV Shim.txt')
info_path=app/'Contents/Info.plist'
with info_path.open('rb') as f: info=plistlib.load(f)
info.update(CFBundleShortVersionString=VERSION,CFBundleVersion=VERSION,CFBundleDisplayName=NAME,LSMinimumSystemVersion='15.0',NSHighResolutionCapable=True,SUFeedURL='https://raw.githubusercontent.com/iarnvidr/jellyfin-mpv-shim-macos/updates/appcast.xml',SUPublicEDKey=os.environ.get('SPARKLE_PUBLIC_ED_KEY',''))
with info_path.open('wb') as f: plistlib.dump(info,f)
subprocess.run([sys.executable,str(WORK/'native_audit.py'),str(app)],check=True)
command('codesign','--force','--deep','--sign','-',str(app)); print('APP_READY',app,flush=True)
