"""Bounded public-IPC mechanism probes; these do not establish a user trigger."""
import json
import subprocess
import time
from menu_bar_playback import PlaybackServer


def exercise_mechanism(case, out, app, native, ipc, engine, server, snapshot, device_id):
    def mpv(command):
        return PlaybackServer.mpv(ipc, command)

    def record(phase):
        return snapshot(case + '-' + phase, require_frontmost=False, activate=False)

    def fullscreen(value):
        mpv(['set_property', 'fullscreen', value])
        time.sleep(4)

    result = {'enginePID': engine, 'mechanismOnly': True, 'actualUserRouteEstablished': False}
    if 'switch-' in case:
        initial = 'legacy-to-native' not in case
        mpv(['set_property', 'native-fs', initial])
        fullscreen(True)
        record('before-option-change')
        mpv(['set_property', 'native-fs', not initial])
        result['nativeFsBefore'] = initial
        result['nativeFsAfter'] = mpv(['get_property', 'native-fs'])
        record('option-changed-while-fullscreen')
        fullscreen(False)
        record('exit-request-settled')
        # Idempotent second false request cannot accidentally enter fullscreen.
        fullscreen(False)
        record('second-exit-request-settled')
        # The current session owns its exit, but a subsequent entry must sample
        # the updated option rather than freezing the original mechanism.
        fullscreen(True)
        next_entry = record('next-entry-uses-updated-mode')
        ax_windows = [window for window in next_entry['jellyfinAXWindows']
                      if window['pid'] == engine]
        assert ax_windows, 'No external AX window observed for next entry'
        assert any(window.get('AXFullScreen') is True for window in ax_windows) is (not initial), \
            'Next entry did not use the updated fullscreen mechanism'
        fullscreen(False)
        record('next-entry-exit')
    elif 'intent-' in case:
        mpv(['set_property', 'native-fs', case.endswith('native')])
        fullscreen(True)
        record('intentional-fullscreen')
        fullscreen(False)
        record('intentional-windowed')
    else:
        mpv(['set_property', 'native-fs', False])
        fullscreen('fullscreen-vo' in case)
        record('before-vo-teardown')
        original_force = mpv(['get_property', 'force-window'])
        mpv(['set_property', 'force-window', 'no'])
        mpv(['stop'])
        deadline = time.monotonic() + 3
        observed_false = False
        while time.monotonic() < deadline:
            if mpv(['get_property', 'vo-configured']) is False:
                observed_false = True
                break
            time.sleep(0.02)
        result['observedVoConfiguredFalse'] = observed_false
        record('after-teardown-attempt')
        if observed_false:
            mpv(['set_property', 'fullscreen', False])
            mpv(['set_property', 'force-window', 'yes'])
            # Actual server cast recreates decoded playback, with the same
            # engine PID and full Now Playing/advancing-video requirements.
            server.start_playback(native, ipc, case + '-recreated', device_id=device_id)
            record('vo-recreated-windowed')
        else:
            result['interpretation'] = 'App retained/recreated VO; requested destruction was not proven'
            mpv(['set_property', 'force-window', original_force])
            fullscreen(False)
    result['finalFullscreen'] = mpv(['get_property', 'fullscreen'])
    result['finalVoConfigured'] = mpv(['get_property', 'vo-configured'])
    result['finalNativeFs'] = mpv(['get_property', 'native-fs'])
    record('final-passive')
    subprocess.run(['open', '-a', 'Finder'], check=True)
    time.sleep(2)
    record('finder-control')
    subprocess.run(['open', '-a', str(app)], check=True)
    time.sleep(3)
    record('actual-app-reopen')
    (out / f'{case}-mechanism.json').write_text(json.dumps(result, indent=2))
    return result
