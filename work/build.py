from pathlib import Path
import hashlib, importlib.metadata, os, platform, plistlib, shutil, subprocess, sys, urllib.request
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'
NAME='Jellyfin MPV Shim'; VERSION=(ROOT/'VERSION').read_text().strip()
LOCK=dict(line.split('=',1) for line in (WORK/'native-dependencies.lock').read_text().splitlines() if line and not line.startswith('#'))
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def command(*a): subprocess.run(a,check=True,env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
def apple(tool):
 p=Path('/usr/bin')/tool
 return str(p) if p.exists() else subprocess.check_output(['/usr/bin/xcrun','--find',tool],text=True).strip()
if sys.platform!='darwin' or platform.machine()!='arm64': raise SystemExit('Build on Apple Silicon macOS.')
# Download immutable official mpv-player archive, verify exact bytes, then extract.
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
command(swiftc,str(WORK/'Updater.swift'),'-o',str(WORK/'Mac Updater'),'-F',str(WORK),'-framework','AppKit','-framework','Sparkle','-Xlinker','-rpath','-Xlinker','@executable_path/../../../Frameworks')
command(clang,'-dynamiclib','-fobjc-arc','-fblocks',str(WORK/'NativeScroll.m'),'-o',str(WORK/'native-scroll.dylib'),'-framework','Cocoa')
metadata=[]
for d in importlib.metadata.distributions():
 n=d.metadata.get('Name')
 if n and not n.lower().startswith(('pyinstaller','altgraph','macholib')): metadata.extend(['--copy-metadata',n])
command(str(ROOT/'.venv/bin/pyinstaller'),'--noconfirm','--clean','--windowed','--onedir','--name',NAME,'--osx-bundle-identifier','org.jellyfin.mpvshim.local','--icon',str(WORK/'source/jellyfin.icns'),'--collect-all','jellyfin_mpv_shim','--collect-all','jellyfin_apiclient_python','--collect-all','python_mpv_jsonipc','--hidden-import','PIL.ImageFont','--add-binary',str(mpvbin)+':.','--add-binary',str(WORK/'native-scroll.dylib')+':.','--distpath',str(WORK/'dist'),'--workpath',str(WORK/'pyinstaller'),'--specpath',str(WORK),*metadata,str(WORK/'launch.py'))
app=WORK/'dist'/(NAME+'.app'); support=app/'Contents/Resources/mac_support'; support.mkdir(parents=True,exist_ok=True)
# The official artifact is a complete app, not a standalone executable: preserve its
# transitive dylibs, MoltenVK, Vulkan ICD resources and config next to the binary.
mpv_dest=app/'Contents/Resources/mpv.app'
shutil.copytree(mpvapp,mpv_dest,symlinks=True,ignore=shutil.ignore_patterns('_CodeSignature','._*','.gitkeep'))
# PyInstaller's standalone copy is redundant; replace it with a launcher for the
# verified nested application binary so runtime uses its own app resources and rpaths.
standalone=app/'Contents/Resources/mpv'
standalone.unlink(missing_ok=True)
standalone.symlink_to('mpv.app/Contents/MacOS/mpv')
# Relocate actual dependency load commands and dylib install IDs (LC_ID_DYLIB).
install_name_tool=apple('install_name_tool'); otool=apple('otool')
molten=mpv_dest/'Contents/Frameworks/libMoltenVK.dylib'
if not molten.is_file(): raise SystemExit('mpv bundle is missing bundled MoltenVK')
subprocess.run([install_name_tool,'-change',str(Path('/opt')/'homebrew/opt/molten-vk/lib/libMoltenVK.dylib'),'@rpath/libMoltenVK.dylib',str(molten)],check=True)
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
# Provenance and inventory are generated before signing; artifact hash is added by packaging.
manifest={'schema':1,'version':VERSION,'python':platform.python_version(),'platform':platform.platform(),'mpv':{'version':LOCK['MPV_VERSION'],'url':LOCK['MPV_URL'],'sha256':LOCK['MPV_SHA256'],'executable':'Contents/Resources/mpv.app/Contents/MacOS/mpv'},'sparkle':{'version':LOCK['SPARKLE_VERSION'],'url':LOCK['SPARKLE_URL'],'sha256':LOCK['SPARKLE_SHA256']},'inputs':{'python_lock_sha256':digest(ROOT/'uv.lock'),'native_lock_sha256':digest(WORK/'native-dependencies.lock')}}
(app/'Contents/Resources/build-manifest.json').write_text(__import__('json').dumps(manifest,indent=2)+'\\n')
subprocess.run([sys.executable,str(WORK/'native_audit.py'),str(app)],check=True,env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
command(apple('codesign'),'--force','--deep','--sign','-',str(app)); print('APP_READY',app,flush=True)
