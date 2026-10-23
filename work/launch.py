"""Finder entry point for the local macOS distribution."""
import multiprocessing
import os
from pathlib import Path
import sys


def launch():
    # App launches must not inherit an ephemeral installer/build temp folder.
    import tempfile
    os.environ['TMPDIR'] = '/tmp'
    tempfile.tempdir = '/tmp'
    resources = Path(sys._MEIPASS)
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    import mac_update
    if len(sys.argv) > 1 and sys.argv[1].startswith('--mac-update-'):
        raise SystemExit(mac_update.worker(sys.argv[1:]))
    managed = (os.environ.get('JELLYFIN_MANAGED_RUNTIME')
               if getattr(sys, '_JELLYFIN_MANAGED', False) else None)
    if not managed and 'stop' not in sys.argv[1:]:
        import runtime_update
        runtime = runtime_update.select_runtime()
        if runtime:
            import json
            manifest = json.loads((runtime / 'manifest.json').read_text())
            python = str(runtime / manifest['python'])
            env = mac_update.clean_child_env()
            for key in list(env):
                if key.startswith(('PYTHON', 'DYLD_')):
                    env.pop(key, None)
            os.execve(python, [python, '-I', str(resources / 'mac_support/managed_launch.py'),
                              str(runtime), str(resources), sys.executable, *sys.argv[1:]], env)
    logs = Path.home() / 'Library/Logs/Jellyfin MPV Shim'
    logs.mkdir(parents=True, exist_ok=True)
    sys.stdout = open(logs / 'launcher.log', 'a', buffering=1)
    sys.stderr = sys.stdout
    if not managed:
        mac_update.select_package(mark_pending='stop' not in sys.argv[1:])
    os.environ['PATH'] = str(resources) + ':/usr/bin:/bin:/usr/sbin:/sbin'
    import jellyfin_mpv_shim
    package = Path(jellyfin_mpv_shim.__file__).parent
    # Upstream's experimental Mac packaging assumes the older py2app layout.
    from jellyfin_mpv_shim import utils
    utils.get_resource = lambda *parts: str(package.joinpath(*parts) if package.joinpath(*parts).exists()
                                           else resources.joinpath('jellyfin_mpv_shim', *parts))
    # The backend is always the copy shipped in this app, even after moving it.
    from jellyfin_mpv_shim.conf import Settings
    original_load = Settings.load

    def load(self, *args, **kwargs):
        result = original_load(self, *args, **kwargs)
        self.apply_cli_override('mpv_ext', True)
        player = resources / 'mpv'
        if managed:
            import json
            manifest = json.loads((Path(managed) / 'manifest.json').read_text())
            player = Path(managed) / manifest['mpv']
        self.apply_cli_override('mpv_ext_path', str(player))
        self.apply_cli_override('enable_gui', True)
        return result

    Settings.load = load
    import local_compat
    local_compat.apply(resources, package)
    from jellyfin_mpv_shim.mpv_shim import main
    main()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    launch()
