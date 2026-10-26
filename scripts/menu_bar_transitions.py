"""Bounded transition diagnostics, preserving failed state before any repair."""
import json
import time
from menu_bar_playback import PlaybackServer


def exercise_transitions(case, out, app, native, ipc, engine, server, snapshot,
                         device_id, config, request):
    timeline = []

    def command(args):
        start = time.time()
        answer = PlaybackServer.mpv(ipc, args)
        timeline.append({'start': start, 'end': time.time(), 'command': args, 'result': answer})
        return answer

    def record(phase):
        return snapshot(case + '-' + phase, require_frontmost=False, activate=False)

    def settle(phase):
        time.sleep(3)
        state = record(phase)
        time.sleep(2)
        later = record(phase + '-stable')
        timeline.append({'phase': phase, 'settled': state['mpvState'], 'stable': later['mpvState']})

    def restore():
        # This occurs only after two passive failure-preserving captures.
        command(['set_property', 'fullscreen', False])
        time.sleep(3)

    if case.endswith('legacy-zoom'):
        command(['set_property', 'native-fs', False])
        command(['set_property', 'fullscreen', True])
        time.sleep(3)
        record('legacy-fullscreen-before-zoom')
        start = time.time()
        answer = request(config, 'zoom')
        timeline.append({'start': start, 'end': time.time(), 'nativeMenuCommand': 'zoom', 'result': answer})
        assert answer.get('ok') is True, answer
        settle('legacy-fullscreen-after-zoom')
        restore()
        settle('legacy-zoom-after-explicit-exit')
    else:
        command(['set_property', 'native-fs', True])
        for delay in (0, 0.03, 0.1, 0.25, 0.5):
            name = str(delay).replace('.', '_')
            restore()
            command(['set_property', 'fullscreen', True])
            time.sleep(delay)
            command(['set_property', 'fullscreen', False])
            settle('native-opposed-' + name)
        restore()
        # The Stop route is the real app's browser restoration, not mpv stop.
        command(['set_property', 'fullscreen', True])
        time.sleep(0.05)
        start = time.time()
        answer = request(config, 'stop')
        timeline.append({'start': start, 'end': time.time(), 'nativeMenuCommand': 'stop', 'result': answer})
        assert answer.get('ok') is True, answer
        settle('native-entry-stop-browser')
        restore()
        # Same PID VO destruction during a new native entry; record whether
        # destruction actually occurred rather than inferring it from stop.
        command(['set_property', 'force-window', 'no'])
        command(['set_property', 'fullscreen', True])
        time.sleep(0.05)
        command(['stop'])
        deadline = time.monotonic() + 2
        vo_false = False
        while time.monotonic() < deadline:
            if command(['get_property', 'vo-configured']) is False:
                vo_false = True
                break
            time.sleep(0.05)
        timeline.append({'observedVoConfiguredFalse': vo_false})
        settle('native-entry-teardown')
        if vo_false:
            command(['set_property', 'fullscreen', False])
            command(['set_property', 'force-window', 'yes'])
            server.start_playback(native, ipc, case + '-recreated', device_id=device_id)
            settle('native-entry-recreated-windowed')
    (out / (case + '-transition-timeline.json')).write_text(json.dumps(timeline, indent=2))
    return {'enginePID': engine, 'timeline': timeline, 'exactPublicBody': case.startswith('original-'),
            'notUserCauseUntilWindowedPixelFailure': True}
