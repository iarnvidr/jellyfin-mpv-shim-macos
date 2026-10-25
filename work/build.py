from pathlib import Path
from native_audit import MINIMUM_MACOS
import hashlib, importlib.metadata, json, os, platform, plistlib, shutil, subprocess, sys, urllib.request
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'
NAME='Jellyfin Player'; VERSION=(ROOT/'VERSION').read_text().strip()
LOCK=dict(line.split('=',1) for line in (WORK/'native-dependencies.lock').read_text().splitlines() if line and not line.startswith('#'))
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def command(*a): subprocess.run(a,check=True,env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
def stage(name): print(f'BUILD_STAGE {name}',flush=True)
def apple(tool):
 p=Path('/usr/bin')/tool
 return str(p) if p.exists() else subprocess.check_output(['/usr/bin/xcrun','--find',tool],text=True).strip()
if sys.platform!='darwin' or platform.machine()!='arm64': raise SystemExit('Build on Apple Silicon macOS.')
# Download immutable official mpv-player archive, verify exact bytes, then extract.
stage('acquire mpv')
command(sys.executable,str(WORK/'acquire_mpv.py'))
mpvapp=WORK/'mpv-release/mpv.app'
mpvbin=mpvapp/'Contents/MacOS/mpv'
if not mpvbin.is_file(): raise SystemExit('mpv executable missing')
# Resolve Apple-provided compiler tools explicitly rather than trusting PATH.
clang=apple('clang')
swiftc=apple('swiftc')
sparkle=WORK/'Sparkle-2.10.0.tar.xz'
if not sparkle.exists(): urllib.request.urlretrieve(LOCK['SPARKLE_URL'],sparkle)
if digest(sparkle)!=LOCK['SPARKLE_SHA256']: raise SystemExit('Sparkle SHA-256 mismatch')
command('tar','-xf',str(sparkle),'-C',str(WORK))
stage('compile native components')
command(swiftc,str(WORK/'Updater.swift'),'-o',str(WORK/'Mac Updater'),'-F',str(WORK),'-framework','AppKit','-framework','Sparkle','-Xlinker','-rpath','-Xlinker','@executable_path/../../../../Frameworks')
command(clang,'-c','-fPIC','-fobjc-arc','-fblocks',str(WORK/'NativeScroll.m'),'-o',str(WORK/'NativeScroll.o'))
command(swiftc,'-emit-library',str(WORK/'NativeMenus.swift'),str(WORK/'NativeSettings.swift'),str(WORK/'NativeMedia.swift'),str(WORK/'NativeScroll.o'),'-o',str(WORK/'native-scroll.dylib'),'-framework','Cocoa','-framework','MediaPlayer')
command(swiftc,str(WORK/'StartupAlert.swift'),'-o',str(WORK/'Jellyfin Player Diagnostics'),'-framework','AppKit')
metadata=[]
for d in importlib.metadata.distributions():
 n=d.metadata.get('Name')
 if n and not n.lower().startswith(('pyinstaller','altgraph','macholib')): metadata.extend(['--copy-metadata',n])
stage('PyInstaller')
command(str(ROOT/'.venv/bin/pyinstaller'),'--noconfirm','--clean','--windowed','--onedir','--name',NAME,'--osx-bundle-identifier','org.jellyfin.mpvshim.local','--icon',str(WORK/'source/jellyfin.icns'),'--collect-all','jellyfin_mpv_shim','--collect-all','jellyfin_apiclient_python','--collect-all','python_mpv_jsonipc','--hidden-import','PIL.ImageFont','--add-data',str(WORK/'NativeControls.lua')+':.','--add-binary',str(mpvbin)+':.','--add-binary',str(WORK/'native-scroll.dylib')+':.','--distpath',str(WORK/'dist'),'--workpath',str(WORK/'pyinstaller'),'--specpath',str(WORK),*metadata,str(WORK/'launch.py'))
app=WORK/'dist'/(NAME+'.app')
# A real AppKit process owns the outer application and handles Sparkle's quit
# event. Keep the frozen Python runtime in a background-only nested bundle.
core=app/'Contents/Helpers/Jellyfin Player Core.app/Contents'
core.joinpath('MacOS').mkdir(parents=True)
with (app/'Contents/Info.plist').open('rb') as f: core_info=plistlib.load(f)
core_info.update(CFBundleExecutable='Jellyfin Player Core',CFBundleIdentifier='org.jellyfin.mpvshim.core',
                 CFBundleName='Jellyfin Player Core',CFBundleVersion=VERSION,
                 CFBundleShortVersionString=VERSION,LSBackgroundOnly=True)
core_info.pop('LSUIElement',None)
with (core/'Info.plist').open('wb') as f: plistlib.dump(core_info,f)
shutil.move(app/'Contents/MacOS'/NAME,core/'MacOS/Jellyfin Player Core')
for directory in ('Frameworks','Resources'):
 shutil.move(app/'Contents'/directory,core/directory)
 (app/'Contents'/directory).mkdir()
command(swiftc,str(WORK/'AppHost.swift'),str(WORK/'NativeMenus.swift'),str(WORK/'NativeSettings.swift'),str(WORK/'NativeMedia.swift'),'-o',str(app/'Contents/MacOS'/NAME),'-framework','AppKit','-framework','MediaPlayer')
shutil.copy2(WORK/'native-scroll.dylib',app/'Contents/Frameworks/native-scroll.dylib')
shutil.copy2(WORK/'source/jellyfin.icns',app/'Contents/Resources/jellyfin.icns')
support=app/'Contents/Resources/mac_support'; support.mkdir(parents=True,exist_ok=True)
# The official artifact is a complete app, not a standalone executable: preserve its
# transitive dylibs, MoltenVK, Vulkan ICD resources and config next to the binary.
mpv_dest=app/'Contents/Resources/mpv.app'
shutil.copytree(mpvapp,mpv_dest,symlinks=True,ignore=shutil.ignore_patterns('_CodeSignature','._*','.gitkeep'))
# Brand nested app metadata using the bundled upstream Jellyfin icon.
player_info_path=mpv_dest/'Contents/Info.plist'
with player_info_path.open('rb') as f: player_info=plistlib.load(f)
player_info.update(CFBundleName='Jellyfin Player',CFBundleDisplayName='Jellyfin Player',CFBundleIdentifier='org.jellyfin.mpvshim.player',CFBundleExecutable='mpv',CFBundleIconFile='jellyfin.icns',CFBundleShortVersionString=VERSION,CFBundleVersion=VERSION)
player_info.pop('CFBundleIconName',None)
for key in ('CFBundleDocumentTypes','CFBundleURLTypes','UTImportedTypeDeclarations'): player_info.pop(key,None)
with player_info_path.open('wb') as f: plistlib.dump(player_info,f)
shutil.copy2(WORK/'source/jellyfin.icns',mpv_dest/'Contents/Resources/jellyfin.icns')
# mpv also retains these legacy resource names; none may expose its stock icon.
for icon in (mpv_dest/'Contents/Resources').glob('*.icns'):
 shutil.copy2(WORK/'source/jellyfin.icns',icon)
# PyInstaller's standalone copy is redundant; replace it with a launcher for the
# verified nested application binary so runtime uses its own app resources and rpaths.
# PyInstaller emits the executable into Contents/Frameworks as well as the
# resources destination. Remove both redundant artifacts (whether file or link)
# before signing; never remove the nested app's actual executable.
for standalone in (app/'Contents/Frameworks/mpv', app/'Contents/Resources/mpv',core/'Frameworks/mpv',core/'Resources/mpv'):
 if standalone.is_symlink() or standalone.is_file(): standalone.unlink()
 elif standalone.is_dir(): shutil.rmtree(standalone)
stage('relocate native load commands')
# Relocate actual dependency load commands and dylib install IDs (LC_ID_DYLIB).
install_name_tool=apple('install_name_tool'); otool=apple('otool')
molten=mpv_dest/'Contents/Frameworks/libMoltenVK.dylib'
if not molten.is_file(): raise SystemExit('mpv bundle is missing bundled MoltenVK')
subprocess.run([install_name_tool,'-id','@rpath/libMoltenVK.dylib',str(molten)],check=True)
# Rewrite only real load commands, recursively in the retained original mpv app;
# never treat LC_ID_DYLIB as a dependency or touch a redundant duplicate.
for binary in mpv_dest.rglob('*'):
 if not binary.is_file(): continue
 lines=subprocess.run([otool,'-L',str(binary)],check=True,text=True,capture_output=True).stdout.splitlines()
 for line in lines[1:]:
  match=__import__('re').match(r'^\s*(.+?)\s+\(compatibility version ',line)
  if match and Path(match.group(1)).name=='libMoltenVK.dylib' and match.group(1).startswith('/'):
   subprocess.run([install_name_tool,'-change',match.group(1),'@rpath/libMoltenVK.dylib',str(binary)],check=True)
for binary in (app/'Contents/Frameworks/Sparkle.framework').rglob('*'):
 if not binary.is_file(): continue
 lines=subprocess.run([otool,'-L',str(binary)],check=True,text=True,capture_output=True).stdout.splitlines()
 # For a dylib, line zero is its LC_ID_DYLIB install name, not a load dependency.
 # Executables have a "path:" header, which must never be rewritten either.
 match=__import__('re').match(r'^\s*(.+?)\s+\(compatibility version ',lines[0]) if lines else None
 if match and str(app) in match.group(1):
  subprocess.run([install_name_tool,'-id','@rpath/'+binary.name,str(binary)],check=True)
 for line in lines[1:]:
  match=__import__('re').match(r'^\s*(.+?)\s+\(compatibility version ',line)
  if match and str(app) in match.group(1):
   subprocess.run([install_name_tool,'-change',match.group(1),'@rpath/'+Path(match.group(1)).name,str(binary)],check=True)

for n in ['launch.py','mac_update.py','mac_menu.py','mac_settings.py','mac_volume.py','mac_media.py','NativeControls.lua','local_compat.py','player_runtime.py','mac_single_instance.py','startup.py']:
 if (WORK/n).exists(): shutil.copy2(WORK/n,support/n)
shutil.copy2(WORK/'source/jellyfin.icns',support/'jellyfin.icns'); (app/'Contents/Frameworks/mac_support').symlink_to('../Resources/mac_support')
helper=app/'Contents/Helpers/Mac Updater.app/Contents'; helper.joinpath('MacOS').mkdir(parents=True,exist_ok=True); shutil.copy2(WORK/'Mac Updater',helper/'MacOS/Mac Updater')
with helper.joinpath('Info.plist').open('wb') as f: plistlib.dump({'CFBundleExecutable':'Mac Updater','CFBundleIdentifier':'org.jellyfin.mpvshim.local.updater','CFBundleName':'Jellyfin Player Updates','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSUIElement':True},f)
diagnostics=app/'Contents/Helpers/Jellyfin Player Diagnostics.app/Contents'
diagnostics.joinpath('MacOS').mkdir(parents=True,exist_ok=True)
diagnostics.joinpath('Resources').mkdir()
shutil.copy2(WORK/'Jellyfin Player Diagnostics',diagnostics/'MacOS/Jellyfin Player Diagnostics')
shutil.copy2(WORK/'source/jellyfin.icns',diagnostics/'Resources/jellyfin.icns')
with diagnostics.joinpath('Info.plist').open('wb') as f: plistlib.dump({'CFBundleExecutable':'Jellyfin Player Diagnostics','CFBundleIdentifier':'org.jellyfin.mpvshim.local.diagnostics','CFBundleName':'Jellyfin Player','CFBundleIconFile':'jellyfin.icns','CFBundlePackageType':'APPL','CFBundleVersion':VERSION,'LSUIElement':True},f)
shutil.copytree(WORK/'Sparkle.framework',app/'Contents/Frameworks/Sparkle.framework',symlinks=True)
notices=app/'Contents/Resources/Licenses'; notices.mkdir(exist_ok=True)
# The pinned official release archive contains its complete generic license at ./LICENSE.
# Copy this exact known archive member; do not guess with wildcard matching.
import tarfile
with tarfile.open(sparkle,'r:xz') as archive:
 license_member=archive.extractfile('./LICENSE')
 if license_member is None: raise SystemExit('Pinned Sparkle archive is missing ./LICENSE')
 (notices/'Sparkle-LICENSE.txt').write_bytes(license_member.read())
shutil.copy2(WORK/'source/LICENSE.md',notices/'Jellyfin MPV Shim.txt')
info_path=app/'Contents/Info.plist'
with info_path.open('rb') as f: info=plistlib.load(f)
# Pin the public trust root in tracked configuration; environment overrides are
# accepted only when they match, preventing accidental signing-key mismatches.
public_key=(WORK/'sparkle-public-key.txt').read_text().strip()
import base64
try: public_key_bytes=base64.b64decode(public_key,validate=True)
except Exception as exc: raise SystemExit('Invalid configured Sparkle public key') from exc
if len(public_key_bytes)!=32: raise SystemExit('Sparkle public key must decode to 32 bytes')
env_public_key=os.environ.get('SPARKLE_PUBLIC_ED_KEY')
if env_public_key is not None and env_public_key != public_key: raise SystemExit('SPARKLE_PUBLIC_ED_KEY does not match the configured Sparkle public key')
info.update(CFBundleShortVersionString=VERSION,CFBundleVersion=VERSION,CFBundleName='Jellyfin Player',CFBundleDisplayName='Jellyfin Player',CFBundleExecutable='Jellyfin Player',CFBundleIconFile='jellyfin.icns',LSUIElement=False,LSBackgroundOnly=False,LSMinimumSystemVersion=MINIMUM_MACOS,NSHighResolutionCapable=True,SUFeedURL='https://raw.githubusercontent.com/iarnvidr/jellyfin-mpv-shim-macos/updates/appcast.xml',SUPublicEDKey=public_key)
info.update(NSLocalNetworkUsageDescription='Find and connect to your Jellyfin server on your local network.',
            NSBonjourServices=['_jellyfin._tcp'])
with info_path.open('wb') as f: plistlib.dump(info,f)
# Provenance and inventory are generated before signing; artifact hash is added by packaging.
manifest={'schema':1,'version':VERSION,'python':platform.python_version(),'platform':platform.platform(),'mpv':{'version':LOCK['MPV_VERSION'],'url':LOCK['MPV_URL'],'sha256':LOCK['MPV_SHA256'],'executable':'Contents/Resources/mpv.app/Contents/MacOS/mpv'},'sparkle':{'version':LOCK['SPARKLE_VERSION'],'url':LOCK['SPARKLE_URL'],'sha256':LOCK['SPARKLE_SHA256']},'inputs':{'python_lock_sha256':digest(ROOT/'uv.lock'),'native_lock_sha256':digest(WORK/'native-dependencies.lock')}}
(app/'Contents/Resources/build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
stage('remove external native search paths')
from bundle_signing import is_macho
from native_audit import external_runpaths
for binary in app.rglob('*'):
 if binary.is_symlink() or not binary.is_file() or not is_macho(binary): continue
 load=subprocess.check_output([otool,'-l',str(binary)],text=True)
 for rpath in external_runpaths(load):
  command(install_name_tool,'-delete_rpath',rpath,str(binary))
stage('native audit (timeout 180s)')
try:
 subprocess.run([sys.executable,str(WORK/'native_audit.py'),str(app)],check=True,env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'},timeout=180)
except subprocess.TimeoutExpired as exc:
 raise SystemExit(f'native audit exceeded 180 seconds for {app}') from exc
# Execute a copied bundle at a different path: this is a native dyld/framework-load
# smoke check only, not a GUI or complete-update/relaunch test.
smoke=WORK/'sparkle-helper-smoke.app'
shutil.copytree(app,smoke,symlinks=True)
smoke_helper=smoke/'Contents/Helpers/Mac Updater.app/Contents/MacOS/Mac Updater'
stage('moved-bundle dyld smoke (timeout 30s)')
try: result=subprocess.run([str(smoke_helper),'--dyld-smoke'],text=True,capture_output=True,timeout=30)
except subprocess.TimeoutExpired as exc:
 if exc.pid is not None:
  try: os.kill(exc.pid, __import__('signal').SIGKILL)
  except ProcessLookupError: pass
 raise SystemExit('Sparkle helper moved-app dyld smoke exceeded 30 seconds') from exc
if result.returncode != 0 or 'JELLYFIN_PLAYER_SPARKLE_DYLD_OK' not in result.stdout:
 raise SystemExit(f'Sparkle helper moved-app dyld smoke failed (exit {result.returncode}): {result.stderr}')
smoke.rename(WORK/'sparkle-helper-smoke-complete.app')
stage('sign every native image and nested bundle inside out')
from bundle_signing import sign_bundle
sign_bundle(app)
print('APP_READY',app,flush=True)
