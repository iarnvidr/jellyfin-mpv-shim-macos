"""Real browser focus gestures; captures never activate or move the pointer."""
import hashlib
import json
import os
import plistlib
from pathlib import Path
import subprocess
import time


def exercise_browser(out, app, config, probe, engine, host, server, snapshot, request,
                     ipc, prior_sessions, device_id):
    events = []

    def command(*args):
        result = subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)
        events.append({'time': time.time(), 'command': [str(a) for a in args], 'stdout': result.stdout})
        return result

    def capture(phase):
        state = snapshot('original-browser-' + phase, require_frontmost=False, activate=False)
        assert state['mpvState']['fullscreen'] is False, state['mpvState']
        return state

    def controls(phase):
        data = json.loads(command(probe, '--controls', engine).stdout)
        (out / f'original-browser-{phase}-controls.json').write_text(json.dumps(data, indent=2))
        return data['controls']

    with (app / 'Contents/Info.plist').open('rb') as file:
        info = plistlib.load(file)
    archives = list((out.parents[1] / 'release').glob('*-Apple-Silicon.zip'))
    assert len(archives) == 1, archives
    assert archives[0].name == 'Jellyfin-Player-' + info['CFBundleShortVersionString'] + '-Apple-Silicon.zip', info
    identity = {'bundle': str(app), 'version': info['CFBundleShortVersionString'], 'hostPID': host,
                'enginePID': engine, 'neverEnteredFullscreen': True, 'browserControlsBeforeAnyPlayback': True,
                'archiveSHA256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in archives}}
    (out / 'original-browser-published-identity.json').write_text(json.dumps(identity, indent=2))
    try:
        state = capture('authenticated-home')
        controls('authenticated-home')
        # Move focus by a real mouse event on the visible engine window.
        windows = [w for w in state['jellyfinWindows'] if w.get('kCGWindowOwnerPID') == engine
                   and w.get('kCGWindowLayer') == 0]
        assert windows, state['jellyfinWindows']
        bounds = windows[0]['kCGWindowBounds']
        command(probe, '--click', bounds['X'] + 8, bounds['Y'] + 300)
        time.sleep(2)
        capture('after-real-window-click')
        # Select the actual indexed item from the accessible browser card.
        nodes = controls('before-item-click')
        candidates = [n for n in nodes if n.get('bounds') and n.get('id')
                      and server.item['Name'] in ' '.join(str(n.get(k, '')) for k in ('title', 'description', 'value'))
                      and n.get('role') in ('AXButton', 'AXGroup', 'AXImage')]
        if not candidates:
            # Home may initially show library tiles; enter the actual library.
            libraries = [n for n in nodes if n.get('bounds') and n.get('id') and
                         'Proof' in ' '.join(str(n.get(k, '')) for k in ('title', 'description', 'value'))]
            assert libraries, 'No real library/item card; see saved AX controls'
            x, y, width, height = libraries[0]['bounds']
            command(probe, '--click', x + width / 2, y + height / 2)
            time.sleep(3)
            capture('library')
            nodes = controls('library')
            candidates = [n for n in nodes if n.get('bounds') and n.get('id') and
                          server.item['Name'] in ' '.join(str(n.get(k, '')) for k in ('title', 'description', 'value'))]
        assert candidates, 'No actual movie card; see saved AX controls'
        x, y, width, height = candidates[0]['bounds']
        card = (x + width / 2, y + height / 2)
        context = {}
        for gesture in ('right', 'control'):
            command(probe, '--click', *card, gesture)
            time.sleep(2)
            capture('card-' + gesture + '-click')
            menu_nodes = controls('card-' + gesture + '-click')
            context[gesture] = any(n.get('id', '').startswith('tilemenu') for n in menu_nodes)
            if os.environ.get('JELLYFIN_MENU_REQUIRE_BROWSER_CONTEXT') == '1':
                assert context[gesture], f'{gesture}: browser card context menu absent'
            if gesture == 'control' and context[gesture]:
                favorite = next(n for n in menu_nodes if n.get('id', '').startswith('tilemenu')
                                and 'Add to favorites' in (n.get('title', '') + n.get('description', '')))
                fx, fy, fw, fh = favorite['bounds']
                command(probe, '--click', fx + fw / 2, fy + fh / 2)
                from menu_bar_playback import wait_for
                actual = wait_for('favorite action persisted on real server', lambda: next((item for item in
                    server.api('GET', '/Items?userId=' + server.user_id + '&ids=' + server.item['Id'])['Items']
                    if item.get('UserData', {}).get('IsFavorite')), None), seconds=15)
                (out / 'original-browser-context-action-server-item.json').write_text(json.dumps(actual, indent=2))
            # Dismiss through a neutral content click before the next gesture.
            command(probe, '--click', bounds['X'] + 110, bounds['Y'] + 90)
            time.sleep(1)
        (out / 'original-browser-context-results.json').write_text(json.dumps(context, indent=2))
        current = controls('after-context-actions')
        card_node = next(n for n in current if n.get('id') == candidates[0]['id'])
        x, y, width, height = card_node['bounds']
        # Avoid the hover play chip at the artwork centre.
        command(probe, '--click', x + 15, y + 15)
        time.sleep(3)
        capture('item-details')
        detail_nodes = controls('item-details')
        assert any(n.get('id') == 'nav-back' for n in detail_nodes), 'Card click did not navigate to item details'
        back = next(n for n in detail_nodes if n.get('id') == 'nav-back')
        x, y, width, height = back['bounds']
        command(probe, '--click', x + width / 2, y + height / 2, 'right')
        time.sleep(2)
        capture('navigation-history-right-click')
        history_nodes = controls('navigation-history-right-click')
        history = any(n.get('id', '').startswith('historymenu') for n in history_nodes)
        if os.environ.get('JELLYFIN_MENU_REQUIRE_BROWSER_CONTEXT') == '1':
            assert history, 'Browser navigation context callback did not open history'
        command(probe, '--click', bounds['X'] + 15, bounds['Y'] + 100)
        time.sleep(1)
        search = next(n for n in controls('before-textbox-context') if n.get('id') == 'nav-search')
        x, y, width, height = search['bounds']
        command(probe, '--click', x + min(width / 2, 50), y + height / 2, 'right')
        time.sleep(2)
        capture('textbox-right-click')
        controls('textbox-right-click')
        command(probe, '--click', bounds['X'] + 15, bounds['Y'] + 100)
        time.sleep(1)
        # Finder is opened normally; CmdTab returns through the OS switcher.
        command('/usr/bin/open', '-a', 'Finder')
        time.sleep(2)
        capture('finder-before-cmd-tab')
        command(probe, '--key', 'cmd-tab')
        time.sleep(3)
        capture('cmd-tab-return')
        command(probe, '--click', bounds['X'] + 8, bounds['Y'] + 300)
        time.sleep(2)
        capture('clicked-after-cmd-tab')
        command(probe, '--key', 'cmd-h')
        time.sleep(2)
        capture('hidden-via-keyboard')
        command('/usr/bin/open', '-a', app)
        time.sleep(3)
        capture('launchservices-reopen')
        # Browser controls are complete before the first playback request.
        server.start_playback(out / 'original-browser/native-menus', ipc,
                              'original-browser-first-playback', prior_sessions, device_id=device_id)
        capture('first-real-playback')
        video = {}
        for gesture in ('right', 'control', 'right-still', 'control-still'):
            if gesture.endswith('-still'):
                # No move event is posted after the HUD's hide interval.
                command(probe, '--pointer', bounds['X'] + 400, bounds['Y'] + 300)
                time.sleep(5)
                capture('video-before-bare-' + gesture)
            was_paused = server.mpv(ipc, ['get_property', 'pause'])
            command(probe, '--click', bounds['X'] + 400, bounds['Y'] + 300, gesture)
            time.sleep(2)
            capture('video-' + gesture + '-click')
            nodes = controls('video-' + gesture + '-click')
            menus = [n for n in nodes if ':option:' in n.get('id', '') or n.get('role') in ('AXMenu', 'AXMenuItem')]
            # AXMenuBar's regular app menus are intentionally retained; popup
            # items here are the independently exported renderer context menu.
            menus = [n for n in menus if ':option:' in n.get('id', '') or
                     (n.get('bounds') and n['bounds'][2] > 0 and n['bounds'][3] > 0
                      and n['bounds'][1] >= bounds['Y'])]
            model = server.mpv(ipc, ['get_property', 'user-data/jellyfin-accessibility'])
            video[gesture] = {'contextControls': menus,
                              'browserContextEnabled': model.get('browserContextEnabled') if isinstance(model, dict) else None,
                              'pauseUnchanged': server.mpv(ipc, ['get_property', 'pause']) == was_paused}
            assert not menus, f'{gesture}: video context menu appeared'
            assert video[gesture]['pauseUnchanged'], f'{gesture}: video gesture changed pause state'
        (out / 'original-browser-video-context-results.json').write_text(json.dumps(video, indent=2))
        state = request(config, 'state')
        stop = state['now_playing']['commands']['stop']
        assert request(config, stop).get('ok') is True
        time.sleep(3)
        capture('returned-to-browser')
        nodes = controls('returned-to-browser')
        home = next(n for n in nodes if n.get('id') == 'nav-home')
        x, y, width, height = home['bounds']
        command(probe, '--click', x + width / 2, y + height / 2)
        time.sleep(2)
        nodes = controls('returned-home')
        card_node = next(n for n in nodes if n.get('id') and n.get('bounds') and
                         n.get('role') == 'AXButton' and server.item['Name'] in n.get('description', ''))
        x, y, width, height = card_node['bounds']
        command(probe, '--click', x + 15, y + 15, 'right')
        time.sleep(2)
        capture('returned-browser-right-click')
        nodes = controls('returned-browser-right-click')
        returned = any(n.get('id', '').startswith('tilemenu') for n in nodes)
        if os.environ.get('JELLYFIN_MENU_REQUIRE_BROWSER_CONTEXT') == '1':
            assert returned, 'Browser context menu not restored after video playback'
        return {'browser': identity, 'browserContext': context,
                'historyContext': history, 'videoContextAbsent': True,
                'returnedBrowserContext': returned, 'events': len(events)}
    finally:
        (out / 'original-browser-events.json').write_text(json.dumps(events, indent=2))
