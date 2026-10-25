"""Launch the native Sparkle UI; all update transport/install work belongs to Sparkle."""
from pathlib import Path
import json
import os
import subprocess
import sys


def main_bundle(executable=None):
    import plistlib
    for parent in Path(executable or sys.executable).resolve().parents:
        if parent.suffix != '.app':
            continue
        try:
            info = plistlib.loads((parent / 'Contents/Info.plist').read_bytes())
            if info.get('CFBundleIdentifier') == 'org.jellyfin.mpvshim.local':
                return parent
        except (OSError, ValueError):
            continue
    return None

def current_version():
    import plistlib
    app = main_bundle()
    if app is None:
        return 'unknown'
    try:
        with (app / 'Contents/Info.plist').open('rb') as stream:
            return str(plistlib.load(stream).get('CFBundleShortVersionString', 'unknown'))
    except (OSError, ValueError, AttributeError):
        return 'unknown'


def check():
    """Compatibility status; update discovery is performed by the Sparkle helper."""
    return {'status': 'unavailable', 'current': current_version(),
            'message': 'Use Check for Updates to open Sparkle.'}


def show_updater():
    """Open packaged Sparkle helper, passing the containing app as application bundle."""
    host = int(os.environ.get('JELLYFIN_PLAYER_HOST_PID', '0'))
    if host > 1:
        import signal
        os.kill(host, signal.SIGALRM)
        return
    app = main_bundle()
    if app is None:
        raise RuntimeError('Cannot locate the main application bundle for Sparkle.')
    helper = app / 'Contents/Helpers/Mac Updater.app/Contents/MacOS/Mac Updater'
    if not helper.is_file():
        raise RuntimeError('The Sparkle updater helper is missing from this application.')
    subprocess.Popen([str(helper), str(app)], start_new_session=True, env=clean_child_env())


def clean_child_env():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith('_PYI_') or name == '_MEIPASS2':
            env.pop(name, None)
    return env


def worker(args):
    """Retain only a fail-closed compatibility response; never fetch or install code."""
    message = 'Component updates are retired; install a complete signed Mac app release.'
    print(json.dumps({'status': 'error', 'message': message}), flush=True)
    return 1
