"""Fetch and verify the official mpv-player macOS 15 arm64 release archive."""
from pathlib import Path
import hashlib, urllib.request, zipfile, os, tempfile, shutil
ROOT=Path(__file__).resolve().parent
LOCK=dict(line.split('=',1) for line in (ROOT/'native-dependencies.lock').read_text().splitlines() if line and not line.startswith('#'))
path=ROOT.parent/LOCK['MPV_ARCHIVE'] if LOCK.get('MPV_ARCHIVE') else ROOT/'mpv-release.zip'
request=urllib.request.Request(LOCK['MPV_URL'],headers={'User-Agent':'jellyfin-mpv-shim-build'})
if LOCK.get('MPV_ARCHIVE') or os.environ.get('MPV_ACQUIRE_OFFLINE') == '1':
 if not path.is_file(): raise SystemExit(f'offline archive missing: {path}')
else:
 with urllib.request.urlopen(request,timeout=120) as response, path.open('wb') as out:
  while chunk:=response.read(1024*1024): out.write(chunk)
digest=hashlib.sha256(path.read_bytes()).hexdigest()
if digest!=LOCK['MPV_SHA256']: raise SystemExit(f'mpv archive SHA-256 mismatch: {digest}')
import io, tarfile
with zipfile.ZipFile(path) as archive:
 payload=archive.read('mpv.tar.gz')
shutil.rmtree(ROOT/'mpv-release',ignore_errors=True)
with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
 members=archive.getmembers()
 for member in members:
  target=(ROOT/'mpv-release'/member.name).resolve()
  if not target.is_relative_to((ROOT/'mpv-release').resolve()): raise SystemExit(f'unsafe archive path: {member.name}')
 candidates=[m.name for m in members if m.name.endswith('/mpv') or m.name=='mpv']
 if not candidates: raise SystemExit('official mpv archive missing mpv executable')
 archive.extractall(ROOT/'mpv-release',members=members)
print('verified',path,digest,'mpv paths:',candidates)
