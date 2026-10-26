"""Ephemeral CI preference/pointer controls, always restoring original values."""
import json
import plistlib
import subprocess
import time
from menu_bar_playback import PlaybackServer


def exercise_preferences(out, app, ipc, config, request, snapshot, probe):
    keys = ('_HIHideMenuBar', 'AppleMenuBarVisibleInFullscreen')
    raw = subprocess.run(['defaults', 'export', '-g', '-'], check=True, capture_output=True).stdout
    original = plistlib.loads(raw)
    saved = {key: {'present': key in original, 'value': original.get(key)} for key in keys}
    (out / 'preferences-original.json').write_text(json.dumps(saved, indent=2))

    def restart_ui():
        # A successful defaults write is not evidence of live behavior. Finder
        # pointer controls below establish whether the preference took effect.
        for name in ('Dock', 'SystemUIServer'):
            subprocess.run(['killall', name], check=False, capture_output=True)
        time.sleep(3)

    def move_and_capture(prefix):
        for label, point in [('in-window', (512, 384)), ('top-edge', (512, 0))]:
            subprocess.run([str(probe), '--pointer', *map(str, point)], check=True)
            time.sleep(2)
            snapshot(prefix + '-' + label)

    try:
        for hide in (False, True):
            for visible_fs in (False, True):
                prefix = f'pref-autohide-{int(hide)}-fullscreen-menu-{int(visible_fs)}'
                values = dict(zip(keys, (hide, visible_fs)))
                for key, value in values.items():
                    subprocess.run(['defaults', 'write', '-g', key, '-bool', str(value).lower()], check=True)
                restart_ui()
                (out / f'{prefix}-requested.json').write_text(json.dumps(values, indent=2))
                subprocess.run(['open', '-a', 'Finder'], check=True)
                time.sleep(2)
                move_and_capture(prefix + '-finder-windowed')
                subprocess.run(['open', '-a', str(app)], check=True)
                time.sleep(3)
                move_and_capture(prefix + '-jellyfin-windowed')
                if not PlaybackServer.mpv(ipc, ['get_property', 'fullscreen']):
                    assert request(config, 'fullscreen').get('ok') is True
                    time.sleep(3)
                move_and_capture(prefix + '-jellyfin-fullscreen')
                assert request(config, 'fullscreen').get('ok') is True
                time.sleep(3)
                move_and_capture(prefix + '-jellyfin-after-fullscreen')
    finally:
        for key, value in saved.items():
            if value['present']:
                subprocess.run(['defaults', 'write', '-g', key, '-bool', str(bool(value['value'])).lower()], check=True)
            else:
                subprocess.run(['defaults', 'delete', '-g', key], check=False, capture_output=True)
        restart_ui()
        restored = plistlib.loads(subprocess.run(['defaults', 'export', '-g', '-'], check=True, capture_output=True).stdout)
        actual = {key: {'present': key in restored, 'value': restored.get(key)} for key in keys}
        (out / 'preferences-restored.json').write_text(json.dumps(actual, indent=2))
        assert actual == saved, 'Ephemeral runner preferences were not restored'
        subprocess.run(['open', '-a', str(app)], check=True)
        subprocess.run([str(probe), '--pointer', '512', '384'], check=True)
        time.sleep(3)
