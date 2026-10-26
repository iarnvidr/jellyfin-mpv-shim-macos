"""Bounded actual System Settings UI preference controls on ephemeral CI."""
import json
import subprocess
import time


def exercise_ui_preferences(out, app, snapshot, probe):
    def control(value, label):
        result = subprocess.run([str(probe), '--menu-auto-hide', value], capture_output=True, text=True)
        data = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        (out / f'ui-auto-hide-{label}.json').write_text(json.dumps(data, indent=2))
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        return result.returncode, records[-1] if records else {}

    def dismiss_settings():
        subprocess.run(['killall', 'System Settings'], check=False, capture_output=True)
        subprocess.run(['open', '-a', str(app)], check=True)
        time.sleep(2)

    code, initial = control('read', 'original')
    original = initial.get('current')
    if code or original not in ('Always', 'Never', 'In Full Screen Only', 'On Desktop Only'):
        (out / 'ui-preference-result.json').write_text(json.dumps({
            'status': 'unavailable', 'reason': 'Actual System Settings popup was not accessible; preference effect not tested'}, indent=2))
        dismiss_settings()
        return
    snapshot('ui-auto-hide-settings-original')
    results = []
    try:
        for mode in ('Always', 'Never'):
            code, selected = control(mode, mode.lower() + '-set')
            read_code, actual = control('read', mode.lower() + '-readback')
            results.append({'requested': mode, 'selected': selected, 'readback': actual,
                            'verifiedControlValue': not code and not read_code and actual.get('current') == mode})
            for target in ('Finder', str(app)):
                name = 'finder' if target == 'Finder' else 'jellyfin'
                subprocess.run(['open', '-a', target], check=True)
                time.sleep(2)
                for label, point in [('in-window', (512, 384)), ('top-edge', (512, 0))]:
                    subprocess.run([str(probe), '--pointer', *map(str, point)], check=True)
                    time.sleep(2)
                    snapshot(f'ui-autohide-{mode.lower()}-{name}-{label}')
    finally:
        restore_code, restored = control(original, 'restore')
        read_code, actual = control('read', 'restored-readback')
        results.append({'restoreRequested': original, 'restore': restored, 'restoreReadback': actual})
        (out / 'ui-preference-result.json').write_text(json.dumps(results, indent=2))
        dismiss_settings()
        subprocess.run([str(probe), '--pointer', '512', '384'], check=True)
        assert not restore_code and not read_code and actual.get('current') == original, 'System Settings control was not restored'

