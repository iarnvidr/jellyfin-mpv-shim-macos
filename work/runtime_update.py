"""Download and switch complete, prebuilt Python/mpv application runtimes."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile
from packaging.version import Version

ROOT = Path.home() / 'Library/Application Support/Jellyfin MPV Shim/Runtimes'
STATE = ROOT / 'state.json'
_healthy = False


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    os.replace(temporary, STATE)


def path_for(identifier):
    if not re.fullmatch('[a-f0-9]{32}', str(identifier)):
        raise ValueError('Invalid runtime identifier.')
    return ROOT / 'versions' / identifier


def active_manifest():
    try:
        active = read_state().get('active')
        return json.loads((path_for(active) / 'manifest.json').read_text()) if active else {}
    except (OSError, ValueError):
        return {}


def select_runtime():
    state = read_state()
    owner_alive = False
    if state.get('owner_pid'):
        try:
            os.kill(state['owner_pid'], 0)
            owner_alive = True
        except ProcessLookupError:
            pass
    if state.get('pending'):
        pending = state['pending']
        alive = False
        if isinstance(pending, int) and not isinstance(pending, bool):
            try:
                os.kill(pending, 0)
                alive = True
            except ProcessLookupError:
                pass
        if not alive and not owner_alive:
            state['active'] = state.get('previous')
            state['pending'] = False
            save_state(state)
    if state.get('active'):
        runtime = path_for(state['active'])
        if not (runtime / 'manifest.json').is_file():
            raise ValueError('The active runtime is incomplete.')
        if not state.get('pending') and not owner_alive:
            state['pending'] = os.getpid()
            save_state(state)
        return runtime
    return None


def mark_healthy():
    global _healthy
    if _healthy:
        return
    state = read_state()
    managed = os.environ.get('JELLYFIN_MANAGED_RUNTIME')
    is_active_app = managed and Path(managed).name == state.get('active')
    if state.get('pending') == os.getpid() or is_active_app:
        state['pending'] = False
        state['owner_pid'] = os.getpid()
        save_state(state)
    _healthy = True


def request_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Jellyfin-Mac-Runtime-Updater/1'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def releases():
    urls = ['https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest',
            'https://api.github.com/repos/mpv-player/mpv/releases/latest',
            'https://pypi.org/pypi/jellyfin-mpv-shim/json']
    with ThreadPoolExecutor(max_workers=3) as pool:
        python, mpv, app = list(pool.map(request_json, urls))
    candidates = []
    for asset in python.get('assets', []):
        match = re.fullmatch(r'cpython-(3\.\d+\.\d+)\+\d+-aarch64-apple-darwin-install_only_stripped\.tar\.gz', asset['name'])
        if match and Version(match[1]) >= Version('3.13'):
            candidates.append((Version(match[1]), asset))
    if not candidates:
        raise ValueError('No compatible prebuilt Python runtime is available.')
    python_version, python_asset = max(candidates, key=lambda item: item[0])
    macos = int(subprocess.check_output(['sw_vers', '-productVersion'], text=True).split('.')[0])
    candidates = []
    for asset in mpv.get('assets', []):
        match = re.fullmatch(r'mpv-v(\d+\.\d+\.\d+)-macos-(\d+)-arm\.zip', asset['name'])
        if match and int(match[2]) <= macos:
            candidates.append((int(match[2]), match[1], asset))
    if not candidates or mpv.get('prerelease'):
        raise ValueError('No compatible stable mpv build is available.')
    _, mpv_version, mpv_asset = max(candidates, key=lambda item: item[0])
    return {'python_version': str(python_version), 'python_build': python['tag_name'],
            'python_asset': python_asset, 'mpv_version': mpv_version, 'mpv_asset': mpv_asset,
            'app_version': app['info']['version']}


def check():
    import mac_update
    latest = releases()
    current = active_manifest()
    changes = []
    if Version(latest['app_version']) > Version(mac_update.current_version()):
        changes.append('Jellyfin MPV Shim ' + latest['app_version'])
    if not current or Version(latest['python_version']) > Version(current['python_version']) or latest['python_build'] != current.get('python_build'):
        changes.append('Python ' + latest['python_version'])
    if not current or Version(latest['mpv_version']) > Version(current['mpv_version']):
        changes.append('mpv ' + latest['mpv_version'])
    return {'status': 'available' if changes else 'current', 'current': mac_update.current_version(),
            'latest': latest['app_version'], 'components': ', '.join(changes),
            'runtime': 'Python %s · mpv %s' % (current.get('python_version', 'bundled'), current.get('mpv_version', 'bundled'))}


def download(asset, target, owner):
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/' + owner + '/releases/download/'):
        raise ValueError('The runtime download source is invalid.')
    expected = asset.get('digest', '')
    if not re.fullmatch('sha256:[a-f0-9]{64}', expected):
        raise ValueError('This runtime has no published SHA-256 checksum.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Jellyfin-Mac-Runtime-Updater/1'})
    digest = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(request, timeout=90) as response, target.open('wb') as output:
        while data := response.read(1024 * 1024):
            count += len(data)
            if count > 512 * 1024 * 1024:
                raise ValueError('The runtime download is too large.')
            output.write(data)
            digest.update(data)
    if 'sha256:' + digest.hexdigest() != expected:
        raise ValueError('The runtime download failed checksum verification.')


def unzip(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 2 * 1024 ** 3:
            raise ValueError('The player archive is too large.')
        for item in z.infolist():
            target = destination / item.filename
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Invalid player archive path.')
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = item.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                link = z.read(item).decode()
                if not (target.parent / link).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Invalid player archive link.')
                target.symlink_to(link)
            else:
                with z.open(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(mode & 0o777 or 0o644)


def brand_player(player, resources):
    """Keep the downloaded player's macOS identity consistent with the launcher."""
    bundle = player.parents[2]
    plist = bundle / 'Contents/Info.plist'
    with plist.open('rb') as stream:
        info = plistlib.load(stream)
    info.update(CFBundleName='Jellyfin MPV Shim',
                CFBundleDisplayName='Jellyfin MPV Shim',
                CFBundleIdentifier='org.jellyfin.mpvshim.player',
                CFBundleIconFile='icon.icns')
    info.pop('CFBundleIconName', None)
    # This private player is launched by the shim, not a general file/URL handler.
    for key in ['CFBundleDocumentTypes', 'CFBundleURLTypes', 'UTImportedTypeDeclarations']:
        info.pop(key, None)
    shutil.copy2(resources / 'mac_support/jellyfin.icns', bundle / 'Contents/Resources/icon.icns')
    with plist.open('wb') as stream:
        plistlib.dump(info, stream)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)],
                   check=True, capture_output=True, timeout=60)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)],
                   check=True, capture_output=True, timeout=30)


def verify(runtime, resources):
    manifest = json.loads((runtime / 'manifest.json').read_text())
    python = runtime / manifest['python']
    mpv = runtime / manifest['mpv']
    actual = subprocess.check_output([str(python), '-I', '-c', 'import platform; print(platform.python_version())'], text=True, timeout=20).strip()
    if actual != manifest['python_version']:
        raise ValueError('The Python runtime did not match its release.')
    player = subprocess.check_output([str(mpv), '--no-config', '--version'], text=True, timeout=20)
    if 'mpv v' + manifest['mpv_version'] not in player:
        raise ValueError('The player did not match its release.')
    bootstrap = resources / 'mac_support/managed_launch.py'
    result = subprocess.run([str(python), '-I', str(bootstrap), '--verify-runtime', str(runtime), str(resources)],
                            capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise ValueError('The new runtime failed its application compatibility check: ' + result.stderr[-500:])


def install(version):
    import certifi
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another runtime update is already being installed.')
        latest = releases()
        # Resolve once for an internally consistent update, including deps.
        if Version(version) > Version(latest['app_version']):
            raise ValueError('That application release is no longer available.')
        resources = Path(sys._MEIPASS)
        identifier = uuid.uuid4().hex
        target = path_for(identifier)
        with tempfile.TemporaryDirectory(prefix='prepare-', dir=ROOT) as temporary:
            stage = Path(temporary)
            python_archive = stage / 'python.tar.gz'
            mpv_archive = stage / 'mpv.zip'
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(download, latest['python_asset'], python_archive, 'astral-sh/python-build-standalone'),
                        pool.submit(download, latest['mpv_asset'], mpv_archive, 'mpv-player/mpv')]
                for job in jobs:
                    job.result()
            runtime = stage / 'runtime'
            runtime.mkdir()
            with tarfile.open(python_archive) as archive:
                if sum(item.size for item in archive.getmembers()) > 2 * 1024 ** 3:
                    raise ValueError('The Python archive is too large.')
                archive.extractall(runtime, filter='data')
            unzip(mpv_archive, runtime / 'player')
            nested = runtime / 'player/mpv.tar.gz'
            if nested.is_file():
                with tarfile.open(nested) as archive:
                    if sum(item.size for item in archive.getmembers()) > 2 * 1024 ** 3:
                        raise ValueError('The player archive is too large.')
                    archive.extractall(runtime / 'player', filter='data')
                nested.unlink()
            python = runtime / 'python/bin/python3'
            players = list((runtime / 'player').rglob('mpv.app/Contents/MacOS/mpv'))
            if len(players) != 1:
                raise ValueError('The player archive has an unexpected layout.')
            player = players[0]
            brand_player(player, resources)
            packages = runtime / 'packages'
            pip = subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--isolated', '--no-input',
                '--only-binary=:all:', '--index-url', 'https://pypi.org/simple', '--cert', certifi.where(),
                '--target', str(packages), 'jellyfin-mpv-shim==' + latest['app_version'], 'packaging'],
                capture_output=True, text=True, timeout=300)
            if pip.returncode:
                raise ValueError('Compatible prebuilt dependencies are not available yet. Your working version was kept. ' + pip.stderr[-400:])
            manifest = {key: latest[key] for key in ['app_version', 'python_version', 'python_build', 'mpv_version']}
            manifest.update(python='python/bin/python3', mpv=str(player.relative_to(runtime)),
                            python_digest=latest['python_asset']['digest'], mpv_digest=latest['mpv_asset']['digest'])
            (runtime / 'manifest.json').write_text(json.dumps(manifest))
            verify(runtime, resources)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(runtime, target)
            try:
                verify(target, resources)
            except Exception:
                shutil.rmtree(target)
                raise
        state = read_state()
        save_state({'active': identifier, 'previous': state.get('active'), 'pending': False})
        return {'status': 'installed', 'version': manifest['app_version'],
                'runtime': 'Python %s · mpv %s' % (manifest['python_version'], manifest['mpv_version'])}
