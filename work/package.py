"""Create symlink-preserving DMG, Sparkle archive, source archive, and checksums."""
from pathlib import Path
import hashlib, json, shutil, subprocess, sys, zipfile, os
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'; VERSION=(ROOT/'VERSION').read_text().strip()
if sys.platform!='darwin': raise SystemExit('Packaging release artifacts requires macOS and Apple tools.')
def apple(tool):
 p=Path('/usr/bin')/tool
 return str(p) if p.exists() else subprocess.check_output(['/usr/bin/xcrun','--find',tool],text=True).strip()
def run(tool,*args): subprocess.run([apple(tool),*map(str,args)],check=True,env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
app=WORK/'dist/Jellyfin Player.app'
if not app.is_dir(): raise SystemExit(f'Missing built app: {app}')
OUT.mkdir(exist_ok=True); stage=WORK/'installer'; stage.mkdir(exist_ok=True)
if (stage/app.name).exists(): shutil.rmtree(stage/app.name)
run('ditto',str(app),str(stage/app.name))
if not (stage/'Applications').exists(): (stage/'Applications').symlink_to('/Applications',target_is_directory=True)
dmg=OUT/f'Jellyfin-Player-macOS-{VERSION}-Apple-Silicon.dmg'
run('hdiutil','create','-volname','Jellyfin Player','-srcfolder',str(stage),'-format','UDZO','-ov',str(dmg))
archive=OUT/f'Jellyfin-Player-{VERSION}-Apple-Silicon.zip'
if archive.exists(): archive.unlink()
run('ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive))
source=OUT/f'Jellyfin-Player-{VERSION}-Source.zip'
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for base in [ROOT/'work',ROOT/'vendor/default-shader-pack']:
  for p in sorted(base.rglob('*')):
   if p.is_file() and '.git' not in p.parts and not any(x in p.parts for x in ('.venv','dist','pyinstaller','installer')): z.write(p,p.relative_to(ROOT))
 for p in [ROOT/'VERSION',ROOT/'LICENSE.md',ROOT/'THIRD_PARTY.md',ROOT/'pyproject.toml',ROOT/'uv.lock',ROOT/'docs/MPV-PROVENANCE-0.2.0.md']:
  if p.is_file(): z.write(p,p.relative_to(ROOT))
run('codesign','--verify','--deep','--strict',str(app)); run('hdiutil','verify',str(dmg))
manifest=app/'Contents/Resources/build-manifest.json'
if not manifest.is_file(): raise SystemExit('Missing in-app build manifest')
# Emit auditable native-binary inventory from the exact signed app. The
# architecture/deployment/load-closure audit is retained as a release artifact.
audit=OUT/f'Jellyfin-Player-{VERSION}-Native-Audit.json'
subprocess.run([sys.executable,str(WORK/'native_audit.py'),str(app)],check=True,stdout=audit.open('w'),env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
# Include actual vendor notices/source pointers in the source ZIP, not claims of
# completeness. Source inputs are exact pinned checkouts.
# Hash the finalized signed app tree as an inventory alongside artifacts.
bundle_inventory=OUT/f'Jellyfin-Player-{VERSION}-Bundle-Inventory.json'
inventory=[]
for p in sorted(app.rglob('*')):
 if p.is_symlink(): inventory.append({'path':str(p.relative_to(app)),'symlink':str(p.readlink())})
 elif p.is_file(): inventory.append({'path':str(p.relative_to(app)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
bundle_inventory.write_text(json.dumps(inventory,indent=2)+'\n')
# Stable, explicit names make the CI artifact glob fail closed and keep manifest
# distinct from the copy embedded in the app bundle.
manifest_copy=OUT/f'Jellyfin-Player-{VERSION}-Build-Manifest.json'
shutil.copy2(manifest,manifest_copy)
files=[dmg,archive,source,manifest_copy,bundle_inventory,audit]
(OUT/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
print(json.dumps({'dmg':str(dmg),'update_archive':str(archive),'source':str(source),'manifest':str(manifest_copy),'native_audit':str(audit),'inventory':str(bundle_inventory),'checksums':str(OUT/'SHA256SUMS')}))
