"""Create symlink-preserving DMG, Sparkle archive, source archive, and checksums."""
from pathlib import Path
import hashlib, json, re, shutil, subprocess, sys, zipfile, os
ROOT=Path(__file__).resolve().parent.parent; WORK=ROOT/'work'; OUT=ROOT/'outputs'; VERSION=(ROOT/'VERSION').read_text().strip()


def source_files(root=ROOT):
    """Return tracked repository and recursively pinned submodule files only."""
    def git(cwd, *args):
        return subprocess.check_output(['git', '-C', str(cwd), *args])
    files = {}
    revisions = {}
    def add_repo(repo, prefix=''):
        commit = git(repo, 'rev-parse', 'HEAD').decode().strip()
        revisions[prefix or '.'] = commit
        entries = git(repo, 'ls-files', '-z').decode().split('\0')
        for name in filter(None, entries):
            path = repo / name
            if path.is_file() and not path.is_symlink():
                files[prefix + name] = path
        for line in git(repo, 'ls-files', '--stage', '-z').decode().split('\0'):
            if not line: continue
            meta, name = line.split('\t', 1)
            mode, oid, stage = meta.split()
            if mode != '160000' or stage != '0': continue
            sub = repo / name
            actual = git(sub, 'rev-parse', 'HEAD').decode().strip()
            if actual != oid: raise RuntimeError(f'submodule revision mismatch: {name}: expected {oid}, got {actual}')
            add_repo(sub, prefix + name + '/')
        return commit
    # The top-level source tree may itself be a worktree without a .git dir;
    # Git resolves the linked worktree's metadata correctly from its root.
    add_repo(root)
    return files, revisions


def make_source_zip(destination, root=ROOT):
    files, revisions = source_files(root)
    digest = hashlib.sha256()
    # Deterministic zip metadata and content-derived provenance manifest.
    for name, path in sorted(files.items()):
        digest.update(name.encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    provenance = json.dumps({'repository_revisions': revisions, 'files_sha256': digest.hexdigest(),
                             'files': sorted(files)}, indent=2, sort_keys=True) + '\n'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo('SOURCE-MANIFEST.json', (1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, provenance.encode())
    return revisions, digest.hexdigest()

if sys.platform!='darwin': raise SystemExit('Packaging release artifacts requires macOS and Apple tools.')
def apple(tool):
 p=Path('/usr/bin')/tool
 return str(p) if p.exists() else subprocess.check_output(['/usr/bin/xcrun','--find',tool],text=True).strip()
def run(tool,*args):
 command=[apple(tool),*map(str,args)]
 env={**os.environ,'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'}
 if tool!='hdiutil': return subprocess.run(command,check=True,env=env)
 # DiskImages can briefly retain its device/file lock after creating an image
 # on hosted runners. Retry only the documented busy errors, never corruption.
 import time
 for attempt in range(3):
  result=subprocess.run(command,env=env,capture_output=True,text=True)
  print(result.stdout,end=''); print(result.stderr,end='',file=sys.stderr)
  if result.returncode==0: return result
  if attempt==2 or not any(message in result.stderr for message in ('Resource busy','Resource temporarily unavailable')):
   result.check_returncode()
  time.sleep(2*(attempt+1))
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
source_revision, source_digest = make_source_zip(source)

from bundle_signing import verify_bundle
signature_audit=OUT/f'Jellyfin-Player-{VERSION}-Signatures.json'
signature_audit.write_text(json.dumps(verify_bundle(app),indent=2)+'\n')
run('hdiutil','verify',str(dmg))
manifest=app/'Contents/Resources/build-manifest.json'
if not manifest.is_file(): raise SystemExit('Missing in-app build manifest')
def verify_manifest(path):
    try: data=json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as e: raise SystemExit(f'Invalid build manifest {path}: {e}')
    required={'schema','version','python','platform','mpv','sparkle','inputs'}
    if not isinstance(data,dict) or set(data) != required: raise SystemExit(f'Invalid build manifest schema: {path}')
    if data['schema'] != 1 or data['version'] != VERSION: raise SystemExit(f'Build manifest version/schema mismatch: {path}')
    for component in ('mpv','sparkle'):
        item=data.get(component)
        if not isinstance(item,dict) or not isinstance(item.get('version'),str) or not isinstance(item.get('url'),str) or not re.fullmatch(r'[0-9a-f]{64}',str(item.get('sha256',''))): raise SystemExit(f'Invalid {component} manifest pin: {path}')
    if data['mpv'].get('executable') != 'Contents/Resources/mpv.app/Contents/MacOS/mpv': raise SystemExit(f'Invalid mpv manifest executable: {path}')
    inputs=data.get('inputs')
    if not isinstance(inputs,dict) or any(not re.fullmatch(r'[0-9a-f]{64}',str(inputs.get(k,''))) for k in ('python_lock_sha256','native_lock_sha256')): raise SystemExit(f'Invalid manifest input hashes: {path}')
    return data
verify_manifest(manifest)
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
verify_manifest(manifest_copy)
files=[dmg,archive,source,manifest_copy,bundle_inventory,audit,signature_audit]
(OUT/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
print(json.dumps({'dmg':str(dmg),'update_archive':str(archive),'source':str(source),'manifest':str(manifest_copy),'native_audit':str(audit),'inventory':str(bundle_inventory),'checksums':str(OUT/'SHA256SUMS')}))
