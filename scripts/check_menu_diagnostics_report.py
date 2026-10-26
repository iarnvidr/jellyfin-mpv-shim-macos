"""Independent clipboard/report contract checks for native menu diagnostics."""
import argparse
import json
import math
from pathlib import Path
import uuid


def fields(value, allowed, required=None):
    assert isinstance(value, dict), 'Expected an object'
    assert set(value) <= set(allowed), 'Unknown field: ' + ','.join(sorted(set(value) - set(allowed)))
    assert set(required or []) <= set(value), 'Required field absent'


def number(value):
    assert type(value) in (int, float) and math.isfinite(value), 'Expected a finite number'


def integer(value, minimum=None):
    assert type(value) is int, 'Expected integer rather than Boolean/string'
    assert minimum is None or value >= minimum, 'Integer out of bounds'


def boolean(value):
    assert type(value) is bool, 'Expected Boolean'


def vector(value, length):
    assert isinstance(value, list) and len(value) == length, 'Invalid geometry array'
    for component in value:
        number(component)


def state(value):
    allowed = {'requestedPresentation', 'effectivePresentation', 'menuBarVisibleReported', 'mainMenuItemCount',
               'activationPolicy', 'active', 'hidden', 'frontmostPID', 'osVersion', 'osBuild', 'engineProperties',
               'windows', 'windowsOmitted', 'screens', 'screensOmitted', 'mouse', 'preferences'}
    fields(value, allowed, allowed)
    for key in ('requestedPresentation', 'effectivePresentation', 'mainMenuItemCount', 'frontmostPID',
                'windowsOmitted', 'screensOmitted'):
        integer(value[key], 0)
    integer(value['activationPolicy'])
    for key in ('menuBarVisibleReported', 'active', 'hidden'):
        boolean(value[key])
    vector(value['osVersion'], 3)
    assert isinstance(value['osBuild'], str) and len(value['osBuild']) < 64
    assert all(char.isascii() and (char.isalnum() or char == '.') for char in value['osBuild'])
    fields(value['engineProperties'], {'status'}, {'status'})
    assert value['engineProperties']['status'] == 'unavailable'
    vector(value['mouse'], 2)
    assert isinstance(value['windows'], list) and len(value['windows']) <= 8
    for window in value['windows']:
        keys = {'number', 'frame', 'styleMask', 'screenDisplayID', 'level', 'onActiveSpace',
                'visible', 'key', 'main', 'miniaturized', 'zoomed'}
        fields(window, keys, keys)
        for key in ('number', 'styleMask', 'screenDisplayID', 'level'):
            integer(window[key])
        for key in ('onActiveSpace', 'visible', 'key', 'main', 'miniaturized', 'zoomed'):
            boolean(window[key])
        vector(window['frame'], 4)
    assert isinstance(value['screens'], list) and len(value['screens']) <= 8
    for screen in value['screens']:
        keys = {'displayID', 'frame', 'visibleFrame', 'scale', 'safeArea'}
        fields(screen, keys, keys)
        integer(screen['displayID'], 0)
        for key in ('frame', 'visibleFrame', 'safeArea'):
            vector(screen[key], 4)
        number(screen['scale'])
    fields(value['preferences'], {'_HIHideMenuBar', 'AppleMenuBarVisibleInFullscreen'},
           {'_HIHideMenuBar', 'AppleMenuBarVisibleInFullscreen'})
    for preference in value['preferences'].values():
        fields(preference, {'type', 'value'}, {'type'})
        assert preference['type'] in ('missing', 'unsupported', 'number', 'boolean')
        if preference['type'] == 'number':
            number(preference['value'])
        elif preference['type'] == 'boolean':
            boolean(preference['value'])
        else:
            assert set(preference) == {'type'}


def document(value, cutoff):
    keys = {'schema', 'identity', 'lastObservedMonotonic', 'history', 'initial', 'totalTransitions',
            'omittedTransitions', 'clipboardOmittedTransitions'}
    fields(value, keys, {'schema', 'identity', 'lastObservedMonotonic', 'history', 'initial', 'totalTransitions'})
    assert value['schema'] == 1
    identity = value['identity']
    keys = {'role', 'pid', 'hostPID', 'corePID', 'sessionID', 'roleVersion', 'processLaunchTime'}
    fields(identity, keys, keys)
    assert identity['role'] in ('host', 'engine')
    for key in ('pid', 'hostPID', 'corePID'):
        integer(identity[key], 2)
    uuid.UUID(identity['sessionID'])
    assert isinstance(identity['roleVersion'], str) and len(identity['roleVersion']) <= 64
    assert all(char.isascii() and (char.isalnum() or char in '.-_') for char in identity['roleVersion'])
    number(identity['processLaunchTime'])
    number(value['lastObservedMonotonic'])
    integer(value['totalTransitions'], 1)
    assert isinstance(value['history'], list) and len(value['history']) <= 8
    entries = [value['initial']] + value['history']
    for entry in entries:
        fields(entry, {'monotonic', 'wallTime', 'reason', 'state'}, {'monotonic', 'wallTime', 'reason', 'state'})
        number(entry['monotonic'])
        number(entry['wallTime'])
        assert entry['monotonic'] <= cutoff, 'Post-Settings state leaked into frozen report'
        assert entry['reason'] in ('initial', 'sample', 'effectivePresentation', 'beforeSettings',
                                   'notification')
        state(entry['state'])
    for key in ('omittedTransitions', 'clipboardOmittedTransitions'):
        if key in value:
            integer(value[key], 0)
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('--require-peer', action='store_true')
    parser.add_argument('--require-background-effective', type=int)
    parser.add_argument('--require-effective', type=int)
    parser.add_argument('--require-kvo', action='store_true')
    parser.add_argument('--require-engine-requested', type=int)
    parser.add_argument('--same-frozen-as', type=Path)
    parser.add_argument('--newer-than', type=Path)
    parser.add_argument('--exclude-sentinel', action='append', default=[])
    args = parser.parse_args()
    raw = args.report.read_bytes()
    assert 0 < len(raw) <= 65536, 'Clipboard report exceeds 64 KiB bound'
    for sentinel in args.exclude_sentinel:
        assert sentinel not in raw.decode(), 'Private sentinel leaked'
    report = json.loads(raw)
    keys = {'schema', 'capture', 'nonAtomic', 'cutoffMonotonic', 'own', 'peer'}
    fields(report, keys, keys)
    assert report['schema'] == 1 and report['capture'] == 'beforeSettings' and report['nonAtomic'] is True
    number(report['cutoffMonotonic'])
    entries = document(report['own'], report['cutoffMonotonic'])
    peer = report['peer']
    fields(peer, {'status', 'ageSeconds', 'document', 'candidatePIDs'}, {'status'})
    assert peer['status'] in ('missing', 'unreadableOrInvalid', 'identityMismatch', 'processIdentityMismatch',
                              'ambiguous', 'exited', 'stale', 'newerThanCutoff', 'available')
    if args.require_peer:
        assert peer['status'] == 'available', 'Current live peer was not qualified'
    if 'ageSeconds' in peer:
        number(peer['ageSeconds'])
        assert peer['ageSeconds'] >= 0
    if 'document' in peer:
        entries += document(peer['document'], report['cutoffMonotonic'])
        own_id, peer_id = report['own']['identity'], peer['document']['identity']
        assert own_id['role'] != peer_id['role']
        for key in ('sessionID', 'hostPID', 'corePID'):
            assert own_id[key] == peer_id[key], 'Cross-session/core peer included'
    if args.require_effective is not None:
        assert any(e['state']['effectivePresentation'] == args.require_effective for e in entries)
    if args.require_background_effective is not None:
        assert any(not e['state']['active'] and e['state']['requestedPresentation'] == 0
                   and e['state']['effectivePresentation'] == args.require_background_effective for e in entries), \
            'Inactive recorder did not see the independently controlled effective system options'
    if args.require_kvo:
        assert any(e['reason'] == 'effectivePresentation' for e in entries), 'Effective-option KVO was not observed'
    if args.require_engine_requested is not None:
        roles = [report['own']] + ([peer['document']] if 'document' in peer else [])
        assert any(doc['identity']['role'] == 'engine'
                   and any(entry['state']['requestedPresentation'] == args.require_engine_requested
                           and entry['state']['effectivePresentation'] == args.require_engine_requested
                           for entry in [doc['initial']] + doc['history']) for doc in roles), \
            'Frozen engine history lacks the independently established app-owned hiding state'
    if args.same_frozen_as:
        assert raw == args.same_frozen_as.read_bytes(), 'Repeated Settings opening replaced the frozen report'
    if args.newer_than:
        previous = json.loads(args.newer_than.read_bytes())
        assert report['cutoffMonotonic'] > previous['cutoffMonotonic'], 'New Settings episode retained stale freeze'
    print(json.dumps({'bytes': len(raw), 'entries': len(entries), 'peerStatus': peer['status'],
                      'privacyAllowlistPassed': True, 'frozenCutoffPassed': True}))


if __name__ == '__main__':
    main()
