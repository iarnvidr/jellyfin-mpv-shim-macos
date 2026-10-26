"""Real browser focus gestures; captures never activate or move the pointer."""
import hashlib
import json
import os
import plistlib
from pathlib import Path
import subprocess
import time


def exercise_browser(out, app, config, probe, engine, host, server, snapshot, request):
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
    assert info['CFBundleShortVersionString'] == '0.2.10', info
    identity = {'bundle': str(app), 'version': info['CFBundleShortVersionString'], 'hostPID': host,
                'enginePID': engine, 'neverEnteredFullscreen': True, 'neverRequestedPlayback': True,
                'archiveSHA256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (out.parents[1] / 'release').glob('*-Apple-Silicon.zip')}}
    (out / 'original-browser-published-identity.json').write_text(json.dumps(identity, indent=2))
    try:
        state = capture('authenticated-home')
        controls('authenticated-home')
        # Move focus by a real mouse event on the visible engine window.
        windows = [w for w in state['jellyfinWindows'] if w.get('kCGWindowOwnerPID') == engine
                   and w.get('kCGWindowLayer') == 0]
        assert windows, state['jellyfinWindows']
        bounds = windows[0]['kCGWindowBounds']
        command(probe, '--click', bounds['X'] + 300, bounds['Y'] + 120)
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
            # Dismiss through a neutral content click before the next gesture.
            command(probe, '--click', bounds['X'] + 110, bounds['Y'] + 90)
            time.sleep(1)
        (out / 'original-browser-context-results.json').write_text(json.dumps(context, indent=2))
        command(probe, '--click', *card)
        time.sleep(3)
        capture('item-details')
        controls('item-details')
        # Finder is opened normally; CmdTab returns through the OS switcher.
        command('/usr/bin/open', '-a', 'Finder')
        time.sleep(2)
        capture('finder-before-cmd-tab')
        command(probe, '--key', 'cmd-tab')
        time.sleep(3)
        capture('cmd-tab-return')
        command(probe, '--click', bounds['X'] + 300, bounds['Y'] + 120)
        time.sleep(2)
        capture('clicked-after-cmd-tab')
        command(probe, '--key', 'cmd-h')
        time.sleep(2)
        capture('hidden-via-keyboard')
        command('/usr/bin/open', '-a', app)
        time.sleep(3)
        capture('launchservices-reopen')
        return {'browser': identity, 'browserContext': context, 'events': len(events)}
    finally:
        (out / 'original-browser-events.json').write_text(json.dumps(events, indent=2))
