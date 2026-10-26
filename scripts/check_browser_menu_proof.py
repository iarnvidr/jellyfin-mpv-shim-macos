"""Require actual browser/video gestures plus passive windowed menu pixels."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--evidence-dir', type=Path, default=Path('outputs/menu-bar-proof'))
parser.add_argument('--require-context', action='store_true')
args = parser.parse_args()
root = args.evidence_dir
ocr = {Path(row['path']).stem: row for row in map(json.loads, (root / 'menu-pixels-ocr.jsonl').read_text().splitlines())}
phases = ('after-real-login', 'authenticated-home', 'after-real-window-click',
          'card-right-click', 'card-control-click', 'item-details',
          'navigation-history-right-click', 'textbox-right-click', 'launchservices-reopen',
          'first-real-playback', 'video-right-click', 'video-control-click',
          'returned-to-browser', 'returned-browser-right-click')
identity = json.loads((root / 'original-browser-published-identity.json').read_text())
results = []
for phase in phases:
    name = 'original-browser-' + phase
    state = json.loads((root / (name + '.json')).read_text())
    text = ' '.join(word['text'] for word in ocr[name]['words'])
    apps = state['jellyfinProcesses']
    matching = [app for app in apps if app.get('pid') in (identity['hostPID'], identity['enginePID'])]
    expected_bundle = identity['bundle']
    identity_valid = len(matching) == 2 and all(app['bundlePath'] in (
        expected_bundle, expected_bundle + '/Contents/Resources/mpv.app') for app in matching)
    player_windows = [w for w in state['jellyfinAXWindows'] if w['pid'] == identity['enginePID']]
    passed = (identity_valid and state['frontmost'].get('pid') in (identity['hostPID'], identity['enginePID'])
              and state['mpvState']['fullscreen'] is False and bool(player_windows)
              and all(window.get('AXFullScreen') is False for window in player_windows)
              and 'Jellyfin Player' in text and all(word in text for word in ('File', 'Edit', 'Playback')))
    results.append({'phase': phase, 'passed': passed, 'ocr': text, 'frontmost': state['frontmost']})
summary = json.loads((root / 'summary.json').read_text())
assert len(summary) == 1 and 'error' not in summary[0], summary
case = summary[0]
assert case['videoContextAbsent'] is True
if args.require_context:
    assert case['browserContext'] == {'right': True, 'control': True}, case
    assert case['historyContext'] is True and case['returnedBrowserContext'] is True, case
    item = json.loads((root / 'original-browser-context-action-server-item.json').read_text())
    assert item['UserData']['IsFavorite'] is True, item
    textbox = ' '.join(ocr['original-browser-textbox-right-click']['wholeImageWords'])
    assert 'Copy' in textbox and 'Paste' in textbox, textbox
verdict = {'passed': all(result['passed'] for result in results),
           'contextRequired': args.require_context, 'identity': identity, 'phases': results}
(root / 'browser-menu-verdict.json').write_text(json.dumps(verdict, indent=2))
print(json.dumps(verdict, indent=2))
assert verdict['passed'], 'Passive windowed browser/video menu pixels failed; see verdict'
