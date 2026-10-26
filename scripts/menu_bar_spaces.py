"""Actual Finder-window Space interleaving on the untouched public package."""
import json
import subprocess
import time
from menu_bar_playback import PlaybackServer


def exercise_spaces(case, out, app, native, ipc, engine, host, server,
                    snapshot, config, request, probe):
    timeline = []
    result = {'hostPID': host, 'enginePID': engine, 'exactPublicApp': True,
              'inProcessObservation': False, 'timeline': timeline,
              'spaceRoute': 'reopen-existing-Finder-window-no-keyboard-shortcuts'}
    path = out / (case + '-spaces-timeline.json')
    anchor = out / 'space-finder-anchor'
    anchor.mkdir()

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
        shell(probe, '--pointer', 512, 384)
        state = snapshot(case + '-' + phase, activate=False, require_frontmost=False)
        timeline.append({'capture': phase, 'time': state['time'], 'frontmost': state['frontmost'],
                         'mpv': state.get('mpvState'), 'managedSpaces': state.get('managedSpaces'),
                         'finderWindows': state.get('finderWindows')})
        preserve()
        return state

    def current_space(state):
        return [display.get('Current Space', {}).get('id64',
                   display.get('Current Space', {}).get('ManagedSpaceID'))
                for display in state.get('managedSpaces', [])]

    def finder_anchor_visible(state):
        return (state['frontmost'].get('bundle') == 'com.apple.finder'
                and any(window.get('kCGWindowName') == anchor.name
                        and window.get('kCGWindowLayer') == 0
                        and window.get('kCGWindowAlpha', 0) > 0
                        for window in state.get('finderWindows', [])))

    def show_finder_anchor(label):
        action(label, lambda: shell('/usr/bin/open', '-a', 'Finder', anchor))
        time.sleep(3)
        return capture(label)

    desktop = show_finder_anchor('finder-anchor-on-initial-desktop')
    result['finderWindowPrepared'] = finder_anchor_visible(desktop)
    if not result['finderWindowPrepared']:
        result['limitation'] = 'A foreground visible named Finder window was not established before fullscreen'
        preserve()
        return result
    action('establish-engine-foreground', lambda: shell(probe, engine))
    baseline = capture('windowed-before-space-transition')
    if baseline['frontmost'].get('pid') != engine:
        result['limitation'] = 'The engine did not become foreground before the Space experiment'
        preserve()
        return result
    action('native-fs-yes', lambda: PlaybackServer.mpv(ipc, ['set_property', 'native-fs', True]))
    model = request(config, 'state')
    stop_command = model.get('now_playing', {}).get('commands', {}).get('stop')
    result['resolvedStopCommand'] = stop_command
    action('enter-native-fullscreen', lambda: PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', True]))
    time.sleep(3)
    fullscreen = capture('native-fullscreen-created-space')
    other = show_finder_anchor('finder-existing-window-on-other-space')
    actual_switch = bool(current_space(fullscreen) and current_space(other)
                         and current_space(fullscreen) != current_space(other)
                         and finder_anchor_visible(other))
    result.update(managedSpaceSwitchProven=actual_switch, spaceBefore=current_space(baseline),
                  spaceFullscreen=current_space(fullscreen), spaceOther=current_space(other))
    if not actual_switch:
        result['limitation'] = 'Existing Finder window did not establish a distinct active Space with foreground visible window'
        preserve()
        return result
    action('host-reopen-while-engine-on-other-space', lambda: shell('/usr/bin/open', '-a', app))
    time.sleep(3)
    capture('host-reopen-while-engine-fullscreen')
    other_again = show_finder_anchor('finder-before-remote-fullscreen-exit')
    if current_space(other_again) == current_space(fullscreen) or not finder_anchor_visible(other_again):
        result['limitation'] = 'Second Finder activation did not establish engine-on-other-Space precondition'
        preserve()
        return result
    action('exit-fullscreen-from-other-space',
           lambda: PlaybackServer.mpv(ipc, ['set_property', 'fullscreen', False]))
    time.sleep(3)
    capture('exit-from-other-space-passive')
    time.sleep(2)
    capture('exit-from-other-space-stable')
    action('reopen-windowed-app-after-passive-captures', lambda: shell('/usr/bin/open', '-a', app))
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
        result['stopLimitation'] = 'No session-scoped Stop command available before transition'
    preserve()
    return result
