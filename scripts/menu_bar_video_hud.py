"""Bounded actual shown-HUD context gestures, supplementing bare-video proof."""
import json
import subprocess
import time
from menu_bar_playback import wait_for


def exercise_video_hud(out, config, probe, engine, server, snapshot, request, ipc,
                       prior_sessions, device_id):
    server.start_playback(out / 'original-browser/native-menus', ipc,
                          'shown-hud', prior_sessions, device_id=device_id)
    assert request(config, 'zoom').get('ok') is True
    time.sleep(2)
    state = snapshot('shown-hud-window-fitted', activate=False)
    window = next(w for w in state['jellyfinWindows'] if w.get('kCGWindowOwnerPID') == engine
                  and w.get('kCGWindowLayer') == 0)['kCGWindowBounds']
    # The real HUD summon command is the same supported entry used by remote
    # navigation. It creates the actual scene; no render/state is substituted.
    server.mpv(ipc, ['script-message', 'mpvtk-hud-summon', 'nav'])

    def observation():
        return server.mpv(ipc, ['get_property', 'user-data/mpvtk/observe'])

    def shown():
        observed = observation()
        return observed if observed.get('phud_shown') else None

    wait_for('actual HUD scene shown', shown, seconds=15)
    records = {}
    for gesture in ('right', 'control'):
        controls = json.loads(subprocess.run([str(probe), '--controls', str(engine)], check=True,
                                            capture_output=True, text=True).stdout)
        (out / f'shown-hud-{gesture}-before-controls.json').write_text(json.dumps(controls, indent=2))
        play = next(node for node in controls['controls'] if node.get('id') == 'hud-pp')
        x, y, width, height = play['bounds']
        assert 0 <= x < state['displayBounds']['width'] and 0 <= y < state['displayBounds']['height'], play
        paused = server.mpv(ipc, ['get_property', 'pause'])
        subprocess.run([str(probe), '--click', str(x + width / 2), str(y + height / 2), gesture], check=True)
        time.sleep(1)
        observed = observation()
        model = server.mpv(ipc, ['get_property', 'user-data/jellyfin-accessibility'])
        screenshot = snapshot('shown-hud-' + gesture + '-click', activate=False)
        records[gesture] = {'renderer': observed, 'accessibility': model,
                            'pauseUnchanged': paused == server.mpv(ipc, ['get_property', 'pause'])}
        (out / 'shown-hud-gesture-results.json').write_text(json.dumps(records, indent=2))
        assert observed['phud_mode'] is True and observed['phud_shown'] is True, observed
        assert model['browserContextEnabled'] is False and not observed['menu_open'], model
        assert records[gesture]['pauseUnchanged'], gesture
        assert screenshot['mpvState']['fullscreen'] is False
        assert not any(':option:' in n.get('id', '') for n in model['nodes']), model
    (out / 'shown-hud-gesture-results.json').write_text(json.dumps(records, indent=2))
    return {'shownHUDContextAbsent': True, 'window': window}
