"""Versioned, verified application-code updates for the local Mac wrapper."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from email.parser import BytesParser
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path.home() / 'Library/Application Support/Jellyfin MPV Shim/Updates'
STATE = ROOT / 'state.json'
PYPI = 'https://pypi.org/pypi/jellyfin-mpv-shim/json'
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


def version_path(version):
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', str(version)):
        raise ValueError('Unsupported release version.')
    return ROOT / 'versions' / str(version)


def select_package(mark_pending=True):
    state = read_state()
    if mark_pending and state.get('pending'):
        # An update that never rendered its first screen gets rolled back.
        state['active'] = state.get('previous')
        state['pending'] = False
        save_state(state)
    active = state.get('active')
    if active:
        package = version_path(active)
        if (package / 'jellyfin_mpv_shim').is_dir():
            sys.path.insert(0, str(package))
            if mark_pending:
                state['pending'] = True
                save_state(state)


def mark_healthy():
    if getattr(sys, '_JELLYFIN_MANAGED', False):
        import runtime_update
        runtime_update.mark_healthy()
    global _healthy
    if _healthy:
        return
    state = read_state()
    if state.get('pending'):
        state['pending'] = False
        save_state(state)
    _healthy = True


def request_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Jellyfin-MPV-Shim-Mac-Updater/1'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def current_version():
    import runtime_update
    managed = runtime_update.active_manifest()
    if managed:
        return managed['app_version']
    from jellyfin_mpv_shim.constants import CLIENT_VERSION
    return CLIENT_VERSION


def check():
    import runtime_update
    return runtime_update.check()


def validate_dependencies(metadata):
    python_requirement = metadata.get('Requires-Python')
    if python_requirement and Version('.'.join(map(str, sys.version_info[:3]))) not in SpecifierSet(python_requirement):
        raise ValueError('This release needs a newer Python runtime. Install a newer Mac package.')
    for value in metadata.get_all('Requires-Dist', []):
        requirement = Requirement(value)
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError('This release needs a new component (%s). Install a newer Mac package.' % requirement.name)
        if installed not in requirement.specifier:
            raise ValueError('This release needs a newer %s. Install a newer Mac package.' % requirement.name)


def install(version, *, allow_current=False):
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another update is already being installed.')
        import runtime_update
        return runtime_update.install(version)


def _install(version, *, allow_current=False):
    destination = version_path(version)
    if not allow_current and Version(version) <= Version(current_version()):
        raise ValueError('That release is already installed.')
    release = request_json('https://pypi.org/pypi/jellyfin-mpv-shim/%s/json' % version)
    wheel = next((f for f in release['urls'] if f['filename'].endswith('py3-none-any.whl') and not f.get('yanked')), None)
    if not wheel or not wheel['url'].startswith('https://files.pythonhosted.org/'):
        raise ValueError('No compatible application update was published.')
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='download-', dir=ROOT) as temporary:
        stage = Path(temporary)
        req = urllib.request.Request(wheel['url'], headers={'User-Agent': 'Jellyfin-MPV-Shim-Mac-Updater/1'})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != wheel['digests']['sha256']:
            raise ValueError('Update verification failed; the current app was kept.')
        archive = stage / 'release.whl'
        archive.write_bytes(data)
        unpacked = stage / 'package'
        with zipfile.ZipFile(archive) as z:
            if sum(i.file_size for i in z.infolist()) > 200 * 1024 * 1024:
                raise ValueError('The update archive is too large.')
            for item in z.infolist():
                p = Path(item.filename)
                if p.is_absolute() or '..' in p.parts or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Invalid update archive.')
            metadata_name = next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
            metadata = BytesParser().parsebytes(z.read(metadata_name))
            if metadata['Name'].replace('_', '-').lower() != 'jellyfin-mpv-shim' or Version(metadata['Version']) != Version(version):
                raise ValueError('The update does not match the requested release.')
            validate_dependencies(metadata)
            z.extractall(unpacked)
        verify = subprocess.run([sys.executable, '--mac-update-verify', str(unpacked)],
                                capture_output=True, text=True, timeout=45)
        if verify.returncode:
            raise ValueError('This release is incompatible with the Mac wrapper. Your current app was kept.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # Never overwrite the active version while it is running.
            if read_state().get('active') == version:
                return {'status': 'installed', 'version': version}
            shutil.rmtree(destination)
        shutil.move(str(unpacked), destination)
    state = read_state()
    save_state({'active': version, 'previous': state.get('active'), 'pending': False})
    return {'status': 'installed', 'version': version}


def show_updater():
    resources = Path(sys._MEIPASS)
    helper = Path(sys.executable).parent.parent / 'Helpers/Mac Updater.app/Contents/MacOS/Mac Updater'
    subprocess.Popen([str(helper), sys.executable, str(os.getpid())],
                     start_new_session=True, env=clean_child_env())


def clean_child_env():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith('_PYI_') or name == '_MEIPASS2':
            env.pop(name, None)
    return env


def worker(args):
    try:
        if args[0] == '--mac-update-check':
            select_package(mark_pending=False)
            result = check()
        elif args[0] == '--mac-update-verify':
            sys.path.insert(0, args[1])
            import local_compat
            local_compat.verify(Path(args[1]) / 'jellyfin_mpv_shim')
            result = {'status': 'verified'}
        elif args[0] == '--mac-update-install':
            select_package(mark_pending=False)
            result = install(args[1])
        else:
            raise ValueError('Unknown updater command.')
        print(json.dumps(result), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), flush=True)
        return 1
