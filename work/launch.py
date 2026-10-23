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
    # Frozen app executable lives in Contents/MacOS; mpv is retained in its own
    # nested app bundle so dyld sees that bundle's Frameworks and rpaths.
    executable = Path(sys.executable).resolve()
    bundle_contents = next((p for p in executable.parents if p.name == 'Contents'), None)
    app_contents = bundle_contents or resources.parent.parent
    player = app_contents / 'Resources/mpv.app/Contents/MacOS/mpv'
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    import mac_update
    if len(sys.argv) > 1 and sys.argv[1].startswith('--mac-update-'):
        raise SystemExit(mac_update.worker(sys.argv[1:]))
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
        self.apply_cli_override('mpv_ext_path', str(player))
        self.apply_cli_override('enable_gui', True)
        self.apply_cli_override('close_to_tray', False)
        self.apply_cli_override('allow_background', False)
        self.apply_cli_override('start_minimized', False)
        return result

    Settings.load = load
    import mac_single_instance
    import startup
    guard_class = mac_single_instance.install(executable, activation_check=lambda: startup.WINDOW_ACTIVATION)
    try:
        from jellyfin_mpv_shim.args import get_args
        if 'stop' not in get_args().command:
            guard = guard_class()
            if not guard.acquire():
                return
            from jellyfin_mpv_shim import single_instance
            single_instance.SingleInstance = lambda: guard
        # Settings.load can migrate/save before upstream acquires its guard.
        # Own the shared profile first, including the renderer cache writes.
        import local_compat
        local_compat.apply(resources, package)
        from jellyfin_mpv_shim.mpv_shim import main
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        import startup
        report, message = startup.write_report(error, app_contents.parent, player, logs)
        startup.show_error(app_contents.parent, report, message)
        raise SystemExit(1)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    launch()
