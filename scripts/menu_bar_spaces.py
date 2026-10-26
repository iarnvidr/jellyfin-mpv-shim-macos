"""One actual fullscreen Space interleaving on the untouched published app."""
import json
import subprocess
import time
from menu_bar_playback import PlaybackServer


def exercise_spaces(case, out, app, native, ipc, engine, host, server,
                    snapshot, config, request, probe):
    timeline = []
    result = {'hostPID': host, 'enginePID': engine, 'exactPublicApp': True,
              'inProcessObservation': False, 'timeline': timeline}
    path = out / (case + '-spaces-timeline.json')

    def preserve():
        path.write_text(json.dumps(result, indent=2))

    def action(label, callback):
        before = time.time()
        answer = callback()
        timeline.append({'action': label, 'start': before, 'end': time.time(), 'answer': answer})
        preserve()
        return answer

    def shell(*args):
        ran = subprocess.run(list(map(str, args)), capture_output=True, text=True, check=True)
        return {'stdout': ran.stdout, 'stderr': ran.stderr}

    def capture(phase):
        # Moving the pointer does not activate/reopen the application. The
        # capture precedes any subsequent focus repair or state intervention.
        shell(probe, '--pointer', 512, 384)
        state = snapshot(case + '-' + phase, activate=False, require_frontmost=False)
        timeline.append({'capture': phase, 'time': state['time'], 'frontmost': state['frontmost'],
                         'mpv': state.get('mpvState'), 'managedSpaces': state.get('managedSpaces')})
        preserve()
        return state

    def current_space(state):
        return [display.get('Current Space', {}).get('id64',
                   display.get('Current Space', {}).get('ManagedSpaceID'))
                for display in state.get('managedSpaces', [])]

    watch = subprocess.Popen([str(probe), '--watch-spaces', str(out / (case + '-space-events.jsonl'))])
    try:
        # An explicit foreground precondition precedes the actual experiment.
        action('establish-engine-foreground', lambda: shell(probe, engine))
        baseline = capture('windowed-before-space-transition')
        action('native-fs-yes', lambda: PlaybackServer.mpv(ipc, ['set_property', 'native-fs', True]))
        model = request(config, 'state')
        stop_command = model.get('now_playing', {}).get('commands', {}).get('stop')
        result['resolvedStopCommand'] = stop_command
        action('enter-native-fullscreen', lambda: PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', True]))
        time.sleep(3)
        fullscreen = capture('native-fullscreen-created-space')
        action('control-left-to-other-space', lambda: shell(probe, '--key', 'ctrl-left'))
        time.sleep(2)
        other = capture('other-space-before-finder')
        actual_switch = bool(current_space(fullscreen) and current_space(other)
                             and current_space(fullscreen) != current_space(other))
        result['managedSpaceSwitchProven'] = actual_switch
        result['spaceBefore'] = current_space(baseline)
        result['spaceFullscreen'] = current_space(fullscreen)
        result['spaceOther'] = current_space(other)
        if not actual_switch:
            result['limitation'] = 'Control-left did not establish a distinct active Space; no Space interleaving verdict'
            preserve()
            return result
        action('finder-on-other-space', lambda: shell('/usr/bin/open', '-a', 'Finder'))
        time.sleep(2)
        capture('finder-on-other-space')
        action('host-reopen-engine-on-other-space', lambda: shell('/usr/bin/open', '-a', app))
        time.sleep(3)
        capture('host-reopen-while-engine-fullscreen')
        # Verify the opposite shortcut too, rather than treating a sent event
        # as evidence that WindowServer actually changed the active Space.
        action('control-left-before-remote-exit', lambda: shell(probe, '--key', 'ctrl-left'))
        time.sleep(2)
        capture('other-space-before-remote-exit')
        action('control-right-back-to-engine', lambda: shell(probe, '--key', 'ctrl-right'))
        time.sleep(2)
        capture('control-right-returned-space')
        action('control-left-engine-elsewhere', lambda: shell(probe, '--key', 'ctrl-left'))
        time.sleep(2)
        capture('engine-fullscreen-elsewhere-before-exit')
        action('exit-fullscreen-from-other-space',
               lambda: PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', False]))
        time.sleep(3)
        capture('exit-from-other-space-passive')
        time.sleep(2)
        capture('exit-from-other-space-stable')
        # Only after failure-preserving captures, exercise normal app reopen.
        action('reopen-windowed-app', lambda: shell('/usr/bin/open', '-a', app))
        time.sleep(3)
        capture('reopened-windowed-active-space')
        if stop_command:
            response = action('native-stop-to-browser', lambda: request(config, stop_command))
            result['stopAccepted'] = response.get('ok') is True
            time.sleep(3)
            capture('browser-after-space-interleaving')
            time.sleep(2)
            capture('browser-after-space-interleaving-stable')
        else:
            result['stopAccepted'] = False
            result['stopLimitation'] = 'No session-scoped Stop command was available before transition'
        preserve()
        return result
    finally:
        watch.terminate()
        try:
            watch.wait(timeout=3)
        except subprocess.TimeoutExpired:
            watch.kill()
