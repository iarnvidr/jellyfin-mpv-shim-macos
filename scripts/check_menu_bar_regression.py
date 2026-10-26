"""Verify the real screenshot and engine state at the targeted exit boundary."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--require-visible', action='store_true')
args = parser.parse_args()
root = Path('outputs/menu-bar-proof')
ocr = {Path(row['path']).stem: row for row in map(json.loads, (root / 'menu-pixels-ocr.jsonl').read_text().splitlines())}
results = []
for name in ('original-http-profile-actual-menu-exit-2',
             'observed-switch-legacy-to-native-second-exit-request-settled',
             'original-intent-native-intentional-windowed',
             'original-intent-legacy-intentional-windowed'):
    state_path = root / (name + '.json')
    if not state_path.exists():
        continue
    state = json.loads(state_path.read_text())
    image = ocr[name]
    text = ' '.join(word['text'] for word in image['words'])
    windowed = state['mpvState']['fullscreen'] is False
    engine_active = state['frontmost'].get('bundle') == 'org.jellyfin.mpvshim.player'
    menu_visible = 'Jellyfin Player' in text and all(word in text for word in ('File', 'Edit', 'Playback'))
    results.append({'phase': name, 'windowed': windowed, 'engineActive': engine_active,
                    'menuVisibleFromScreenshot': menu_visible,
                    'top22NonBlackPixels': image['top22NonBlackPixels'], 'ocr': text,
                    'passed': windowed and engine_active and menu_visible})
(root / 'menu-regression-verdict.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
if args.require_visible and (len(results) < 2 or not all(row['passed'] for row in results)):
    raise SystemExit('Actual windowed menu regression failed or required phase was not reached')
