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
    managed = None
    logs = Path.home() / 'Library/Logs/Jellyfin MPV Shim'
    logs.mkdir(parents=True, exist_ok=True)
    sys.stdout = open(logs / 'launcher.log', 'a', buffering=1)
    sys.stderr = sys.stdout
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
