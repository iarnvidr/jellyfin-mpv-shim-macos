"""Verify the real screenshot and engine state at the targeted exit boundary."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--require-visible', action='store_true')
parser.add_argument('--evidence-dir', type=Path, default=Path('outputs/menu-bar-proof'))
parser.add_argument('--cases', default='')
args = parser.parse_args()
root = args.evidence_dir
ocr = {Path(row['path']).stem: row for row in map(json.loads, (root / 'menu-pixels-ocr.jsonl').read_text().splitlines())}
results = []
phases = ('original-http-profile-actual-menu-exit-2',
             'observed-switch-legacy-to-native-second-exit-request-settled',
             'observed-switch-legacy-to-native-next-entry-exit',
             'original-switch-native-to-legacy-second-exit-request-settled',
             'original-switch-native-to-legacy-next-entry-exit',
             'original-intent-native-intentional-windowed',
             'original-intent-legacy-intentional-windowed')
if args.cases:
    phases = tuple(name for name in phases
                   if any(name.startswith(case + '-') for case in args.cases.split(',')))
for name in phases:
    state_path = root / (name + '.json')
    if not state_path.exists():
        continue
    state = json.loads(state_path.read_text())
    image = ocr[name]
    text = ' '.join(word['text'] for word in image['words'])
    windowed = state['mpvState']['fullscreen'] is False
    engines = {app['pid'] for app in state['jellyfinProcesses']
               if app.get('bundle') == 'org.jellyfin.mpvshim.player'}
    windows = [window for window in state['jellyfinAXWindows'] if window['pid'] in engines]
    ax_windowed = bool(windows) and all(window.get('AXFullScreen') is False for window in windows)
    # The outer Dock host may own foreground after a production menu action.
    # Both app processes must provide the same Jellyfin menu, verified below.
    jellyfin_active = state['frontmost'].get('bundle') in (
        'org.jellyfin.mpvshim.player', 'org.jellyfin.mpvshim.local')
    menu_visible = 'Jellyfin Player' in text and all(word in text for word in ('File', 'Edit', 'Playback'))
    results.append({'phase': name, 'windowed': windowed, 'axWindowed': ax_windowed,
                    'jellyfinActive': jellyfin_active,
                    'menuVisibleFromScreenshot': menu_visible,
                    'top22NonBlackPixels': image['top22NonBlackPixels'], 'ocr': text,
                    'passed': windowed and ax_windowed and jellyfin_active and menu_visible})
(root / 'menu-regression-verdict.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
if args.require_visible and (not phases or len(results) != len(phases) or not all(row['passed'] for row in results)):
    raise SystemExit('Actual windowed menu regression failed or required phase was not reached')
