"""Create symlink-preserving DMG, Sparkle archive, source archive, and checksums."""
from pathlib import Path
import hashlib, json, shutil, subprocess, sys, zipfile
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'; VERSION=(ROOT/'VERSION').read_text().strip()
if sys.platform!='darwin': raise SystemExit('Packaging release artifacts requires macOS and Apple tools.')
app=WORK/'dist/Jellyfin MPV Shim.app'
if not app.is_dir(): raise SystemExit(f'Missing built app: {app}')
OUT.mkdir(exist_ok=True); stage=WORK/'installer'; stage.mkdir(exist_ok=True)
if (stage/app.name).exists(): shutil.rmtree(stage/app.name)
subprocess.run(['ditto',str(app),str(stage/app.name)],check=True)
if not (stage/'Applications').exists(): (stage/'Applications').symlink_to('/Applications',target_is_directory=True)
dmg=OUT/f'Jellyfin-MPV-Shim-macOS-{VERSION}-Apple-Silicon.dmg'
subprocess.run(['hdiutil','create','-volname','Jellyfin MPV Shim','-srcfolder',str(stage),'-format','UDZO','-ov',str(dmg)],check=True)
archive=OUT/f'Jellyfin-MPV-Shim-{VERSION}-Apple-Silicon.zip'
if archive.exists(): archive.unlink()
subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
source=OUT/f'Jellyfin-MPV-Shim-{VERSION}-Source.zip'
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for base in [ROOT/'work',ROOT/'vendor/default-shader-pack']:
  for p in sorted(base.rglob('*')):
   if p.is_file() and '.git' not in p.parts and not any(x in p.parts for x in ('.venv','dist','pyinstaller','installer')): z.write(p,p.relative_to(ROOT))
 for p in [ROOT/'VERSION',ROOT/'LICENSE.md',ROOT/'THIRD_PARTY.md',ROOT/'pyproject.toml',ROOT/'uv.lock',ROOT/'docs/PLAN-0.2.0.md']:
  if p.is_file(): z.write(p,p.relative_to(ROOT))
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True); subprocess.run(['hdiutil','verify',str(dmg)],check=True)
manifest=app/'Contents/Resources/build-manifest.json'
if not manifest.is_file(): raise SystemExit('Missing in-app build manifest')
# Hash the finalized signed app tree as an inventory alongside artifacts.
bundle_inventory=OUT/f'Jellyfin-MPV-Shim-{VERSION}-Bundle-Inventory.json'
inventory=[]
for p in sorted(app.rglob('*')):
 if p.is_symlink(): inventory.append({'path':str(p.relative_to(app)),'symlink':str(p.readlink())})
 elif p.is_file(): inventory.append({'path':str(p.relative_to(app)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
bundle_inventory.write_text(json.dumps(inventory,indent=2)+'\\n')
files=[dmg,archive,source,manifest,bundle_inventory]
(OUT/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
print(json.dumps({'dmg':str(dmg),'update_archive':str(archive),'source':str(source),'checksums':str(OUT/'SHA256SUMS')}))
