"""Actual second-display fullscreen/return/removal with passive all-screen PNGs."""
import json
import hashlib
import plistlib
from pathlib import Path
import subprocess
import time
import os
from menu_bar_playback import wait_for


def exercise_topology(case, out, app, config, probe, engine, server, snapshot, request,
                      ipc, prior_sessions, device_id):
    native = out / case / 'native-menus'
    archives = list((out.parents[1] / 'release').glob('*-Apple-Silicon.zip'))
    assert len(archives) == 1, archives
    identity = {'archive': archives[0].name, 'sha256': hashlib.sha256(archives[0].read_bytes()).hexdigest(),
                'bundle': str(app), 'version': plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']}
    identity['source_build_run'] = os.environ.get('JELLYFIN_MENU_PROOF_APP_BUILD_RUN_ID') or None
    identity['source'] = 'Unreleasedcandidatebuild' if identity['source_build_run'] else 'Publishedrelease'
    (out / (case + '-public-identity.json')).write_text(json.dumps(identity, indent=2))
    display_out = out / (case + '-display')
    display_out.mkdir()
    events = []
    known_menu_window = None

    def command(*args):
        result = subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)
        events.append({'time': time.time(), 'command': [str(a) for a in args], 'stdout': result.stdout})
        return result

    def observer():
        path = out / (case + '-in-process.jsonl')
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def capture(phase):
        nonlocal known_menu_window
        name = case + '-' + phase
        state = snapshot(name, activate=False)
        records = observer()
        assert records, 'Read-only Lua-loaded AppKit observer did not record state'
        # No activation or pointer movement is performed by capture.
        state['readOnlyAppKitObservation'] = records[-1]
        surface_helper = out / 'trace-menu-display'
        if surface_helper.exists():
            surface = json.loads(command(surface_helper, *([known_menu_window] if known_menu_window else [])).stdout)
            if phase == 'vertical-browser-retina-primary':
                primary = next(s for s in surface['displays'] if s['main'])
                menu = next((w for w in primary['overlappingWindows'] if w['menuLevelMatch']), None)
                assert menu, surface
                known_menu_window = menu['number']
                surface = json.loads(command(surface_helper, known_menu_window).stdout)
            state['displaySurfaceObservation'] = surface
        dock_pid = subprocess.check_output(['/usr/bin/pgrep', '-x', 'Dock'], text=True).strip()
        state['dockAXControls'] = json.loads(command(probe, '--controls', dock_pid).stdout)
        state['publishedDiagnosticRecords'] = {}
        for role in ('host', 'engine'):
            path = Path.home() / 'Library/Logs/Jellyfin Player/menu-state' / (role + '.json')
            if path.exists():
                state['publishedDiagnosticRecords'][role] = json.loads(path.read_text())
        (out / (name + '.json')).write_text(json.dumps(state, indent=2))
        for index, screen in enumerate(state['screens'], 1):
            command('/usr/sbin/screencapture', '-x', '-D', index, out / f'{name}-display-{index}.png')
        events.append({'time': time.time(), 'phase': phase, 'displayCount': len(state['screens']),
                       'fullscreen': state.get('mpvState', {}).get('fullscreen'),
                       'presentationOptions': records[-1]['presentationOptions'],
                       'systemPresentationOptions': records[-1]['systemPresentationOptions']})
        (out / (case + '-topology-events.json')).write_text(json.dumps(events, indent=2))
        return state

    def move(x, y):
        command(probe, '--drag-window', engine, x, y)
        time.sleep(2)
        # Deliberate pointer-away action, recorded separately from capture.
        command(probe, '--pointer', x + 300, y + 220)
        time.sleep(.5)

    assert server.mpv(ipc, ['get_property', 'user-data/menu-proof-observer-loaded']) is True
    command(probe, '--pointer', 500, 400)
    capture('browser-before-second-display')
    helper = out / 'probe-virtual-display'
    log = (display_out / 'helper.log').open('w')
    vertical = os.environ.get('JELLYFIN_MENU_PROOF_VERTICAL') == '1'
    display = subprocess.Popen([str(helper), str(display_out), '900'] + (['vertical'] if vertical else []), stdout=log, stderr=subprocess.STDOUT)
    try:
        def created():
            path = display_out / 'after.json'
            return json.loads(path.read_text()) if path.exists() else None
        capability = wait_for('actual second display creation', created, seconds=25)
        assert capability['qualifiedSecondHiDPI'], capability
        if vertical:
            import re
            def rect(value):
                return [float(n) for n in re.findall(r'-?\d+(?:\.\d+)?', value)]
            primary = next((s for s in capability['screens'] if rect(s['frame']) == [0, 0, 1512, 982] and s['scale'] == 2), None)
            upper = next((s for s in capability['screens'] if rect(s['frame']) == [-175, 982, 1920, 1200] and s['scale'] == 1), None)
            qualified = primary is not None and upper is not None and len(capability['screens']) == 2
            capture('vertical-capability-readback')
            if not qualified or not capability['displaysHaveSeparateSpaces']:
                return {'verticalGeometryQualified': qualified, 'separateSpacesEffective': capability['displaysHaveSeparateSpaces'],
                        'capability': capability, 'status': 'Stopped at capability; exact topology/separate Spaces unavailable'}
            command('/usr/bin/open', display_out)
            time.sleep(3)
            capture('vertical-finder-control')
            command('/usr/bin/open', '-a', app)
            time.sleep(2)
            move(112, 73)
            capture('vertical-browser-retina-primary')
            prevention = os.environ.get('JELLYFIN_MENU_PROOF_POLICY_PREVENTION') == '1'
            if prevention:
                server.mpv(ipc, ['script-message', 'menu-proof-regular-once'])
                time.sleep(2)
                capture('vertical-regular-before-fullscreen')
            assert request(config, 'fullscreen').get('ok') is True
            time.sleep(5)
            capture('vertical-browser-native-fullscreen')
            command('/usr/bin/open', '-a', 'Finder')
            time.sleep(3)
            capture('vertical-finder-after-fullscreen')
            command('/usr/bin/open', '-a', app)
            time.sleep(3)
            capture('vertical-browser-reopen-fullscreen')
            assert request(config, 'fullscreen').get('ok') is True
            time.sleep(5)
            before_recovery = capture('vertical-browser-windowed-return')
            if prevention:
                time.sleep(4)
                later = capture('vertical-prevention-windowed-later')
                return {'verticalGeometryQualified': True, 'capability': capability, 'publicApp': identity,
                        'policySetterResult': server.mpv(ipc, ['get_property', 'user-data/menu-proof-policy-result']),
                        'policyAfterOriginalSequence': before_recovery['readOnlyAppKitObservation']['policy'],
                        'policyLater': later['readOnlyAppKitObservation']['policy'],
                        'status': 'Single regularsetter BEFORE matchedFS/Finder/reopen/exit sequence; qualification depends on policy0remaining effective',
                        'warning': 'If branding reverts0→1 this doesnotqualify as stable-regularprevention'}
            if os.environ.get('JELLYFIN_MENU_PROOF_POLICY_RECOVERY') == '1' or os.environ.get('JELLYFIN_MENU_PROOF_MENU_RECOVERY') == '1':
                # Require a fresh real pixel-positive BEFORE intervention.
                def pixels(phase):
                    path = out / f'{case}-{phase}-display-1.png'
                    return json.loads(command(out / 'read-menu-pixels', '--pixels-only', path).stdout)
                initial_pixels = pixels('vertical-browser-retina-primary')
                failed_pixels = pixels('vertical-browser-windowed-return')
                assert initial_pixels['menuBandNonBlack'] > 10000, initial_pixels
                assert failed_pixels['menuBandNonBlack'] == 0, failed_pixels
                assert before_recovery['mpvState']['fullscreen'] is False
                time.sleep(4)
                settled = capture('vertical-before-policy-recovery-settled')
                assert pixels('vertical-before-policy-recovery-settled')['menuBandNonBlack'] == 0
                assert settled['readOnlyAppKitObservation']['policy'] == 1
                if os.environ.get('JELLYFIN_MENU_PROOF_MENU_RECOVERY') == '1':
                    server.mpv(ipc, ['script-message', 'menu-proof-reassign-once'])
                    time.sleep(2)
                    same = capture('vertical-after-same-menu-reassign')
                    time.sleep(4)
                    same_later = capture('vertical-after-same-menu-reassign-later')
                    assert same_later['readOnlyAppKitObservation']['policy'] == 1
                    assert same_later['readOnlyAppKitObservation']['mainMenuAddress'] == settled['readOnlyAppKitObservation']['mainMenuAddress']
                    same_pixels = pixels('vertical-after-same-menu-reassign-later')
                    result = {'verticalGeometryQualified': True, 'capability': capability, 'publicApp': identity,
                              'freshPixelPositiveBeforeIntervention': True, 'samePointerPixels': same_pixels,
                              'samePointerPolicy': same_later['readOnlyAppKitObservation']['policy'],
                              'menuIdentityBefore': settled['readOnlyAppKitObservation']['mainMenuAddress'],
                              'menuIdentityAfterSamePointer': same_later['readOnlyAppKitObservation']['mainMenuAddress']}
                    if same_pixels['menuBandNonBlack'] == 0:
                        # Same still-failed state; one COPY-only assignment next.
                        server.mpv(ipc, ['script-message', 'menu-proof-copy-once'])
                        time.sleep(2)
                        copied = capture('vertical-after-menu-copy')
                        time.sleep(4)
                        copied_later = capture('vertical-after-menu-copy-later')
                        assert copied_later['readOnlyAppKitObservation']['policy'] == 1
                        assert copied_later['readOnlyAppKitObservation']['mainMenuAddress'] != settled['readOnlyAppKitObservation']['mainMenuAddress']
                        result.update(copyPixels=pixels('vertical-after-menu-copy-later'),
                                      menuIdentityAfterCopy=copied_later['readOnlyAppKitObservation']['mainMenuAddress'])
                    result['interventions'] = 'SamepointermainMenureassign only; IFstillblack copycurrentmainMenureassign only. Policy1retained, noactivation/fullscreen/presentationwrites.'
                    return result
                # SINGLE mutation: regular policy, same app/menu/window objects.
                server.mpv(ipc, ['script-message', 'menu-proof-regular-once'])
                time.sleep(2)
                after = capture('vertical-after-policy-regular')
                time.sleep(4)
                later = capture('vertical-after-policy-regular-later')
                return {'verticalGeometryQualified': True, 'capability': capability, 'publicApp': identity,
                        'freshPixelPositiveBeforeIntervention': True,
                        'policySetterResult': server.mpv(ipc, ['get_property', 'user-data/menu-proof-policy-result']),
                        'policyAfter': after['readOnlyAppKitObservation']['policy'],
                        'policyLater': later['readOnlyAppKitObservation']['policy'],
                        'menuIdentityBefore': settled['readOnlyAppKitObservation']['mainMenuAddress'],
                        'menuIdentityAfter': after['readOnlyAppKitObservation']['mainMenuAddress'],
                        'pixelsAfter': pixels('vertical-after-policy-regular'),
                        'pixelsLater': pixels('vertical-after-policy-regular-later'),
                        'intervention': 'ExactlyoneexplicitmainthreadactivationPolicyregularsetter; no menu/fullscreen/presentationwrites',
                        'status': 'Recovery comparator completed; inspect rawall-display pixels and state, no productionfix inferred'}
            if os.environ.get('JELLYFIN_MENU_PROOF_STOP_AT_RETURN') == '1':
                time.sleep(4)
                final = capture('vertical-windowed-return-later')
                return {'verticalGeometryQualified': True, 'capability': capability, 'appIdentity': identity,
                        'finalAppKit': final['readOnlyAppKitObservation'],
                        'status': 'Stopped aftermatchednativeFS/Finder/normalreopen/exit; no recoveryinterventions or laterupperdrag'}
            move(0, -1100)
            capture('vertical-browser-upper-display')
            move(112, 73)
            final = capture('vertical-browser-retina-return')
            return {'verticalGeometryQualified': True, 'capability': capability, 'publicApp': identity,
                    'finalAppKit': final['readOnlyAppKitObservation'],
                    'status': 'Completed browser-only native Space/layout transitions; inspect actual managedSpaceIDs and pixels',
                    'limits': 'VirtualsafeArea0; physicalnotch/top32inset cannotmatch; own/effective sampled read-only'}
        screens = capability['screens']
        secondary = next(s for s in screens if s['scale'] == 2)
        # Obtain actual CG bounds, not Cocoa's bottom-left frame coordinates.
        # The virtual display is arranged at the right edge of the primary.
        x = next(d for d in capability['displays'] if d['id'] == secondary['id'])['bounds']
        import re
        numbers = [float(n) for n in re.findall(r'-?\d+(?:\.\d+)?', x)]
        target_x, target_y = numbers[0] + 50, numbers[1] + 100
        capture('browser-after-second-display')
        command('/usr/bin/open', '-a', 'Finder')
        time.sleep(2)
        capture('finder-two-displays-control')
        command('/usr/bin/open', '-a', app)
        time.sleep(2)
        move(target_x, target_y)
        state = capture('browser-on-hidpi')
        assert any(w.get('kCGWindowOwnerPID') == engine and w.get('kCGWindowBounds', {}).get('X', 0) >= numbers[0]
                   for w in state['jellyfinWindows']), state['jellyfinWindows']
        server.start_playback(native, ipc, case, prior_sessions, device_id=device_id)
        move(target_x, target_y)
        capture('playing-on-hidpi')
        assert request(config, 'fullscreen').get('ok') is True
        time.sleep(5)
        full = capture('normal-fullscreen-on-hidpi')
        assert full['mpvState']['fullscreen'] is True
        assert any(w.get('kCGWindowOwnerPID') == engine and
                   w.get('kCGWindowBounds', {}).get('X', 0) >= numbers[0] and
                   w.get('kCGWindowBounds', {}).get('Width', 0) >= numbers[2] - 2
                   for w in full['jellyfinWindows']), full['jellyfinWindows']
        assert request(config, 'fullscreen').get('ok') is True
        time.sleep(4)
        capture('normal-windowed-on-hidpi')
        move(50, 100)
        capture('moved-back-to-primary')
        move(target_x, target_y)
        assert request(config, 'fullscreen').get('ok') is True
        time.sleep(5)
        before = capture('fullscreen-before-removal')
        assert before['mpvState']['fullscreen'] is True
        assert any(w.get('kCGWindowOwnerPID') == engine and
                   w.get('kCGWindowBounds', {}).get('X', 0) >= numbers[0] and
                   w.get('kCGWindowBounds', {}).get('Width', 0) >= numbers[2] - 2
                   for w in before['jellyfinWindows']), before['jellyfinWindows']
        (display_out / 'remove-request').touch()
        wait_for('actual virtual display removal', lambda: (display_out / 'removed.json').exists(), seconds=15)
        time.sleep(2)
        removed = capture('display-removed-while-fullscreen')
        assert len(removed['screens']) == 1, removed['screens']
        if server.mpv(ipc, ['get_property', 'fullscreen']):
            assert request(config, 'fullscreen').get('ok') is True
        time.sleep(5)
        exited = capture('windowed-after-display-removal')
        if exited['mpvState']['fullscreen'] is False:
            move(50, 100)
            capture('windowed-moved-primary-after-removal')
        model = request(config, 'state')
        stop = model.get('now_playing', {}).get('commands', {}).get('stop')
        if stop:
            assert request(config, stop).get('ok') is True
        time.sleep(3)
        browser = capture('browser-after-display-removal')
        return {'qualifiedSecondHiDPI': True, 'capability': capability,
                'publicApp': identity,
                'windowedAfterRemoval': exited['mpvState']['fullscreen'] is False,
                'browserAfterRemoval': browser['mpvState']['fullscreen'] is False,
                'observer': 'Read-only Objective-C library loaded through profile Lua; original app archive unchanged',
                'finalAppKit': browser['readOnlyAppKitObservation']}
    finally:
        (display_out / 'remove-request').touch()
        display.terminate()
        display.wait(timeout=10)
        log.close()
