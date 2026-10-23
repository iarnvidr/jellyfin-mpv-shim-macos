"""Replace the bundle cleanly while retaining a local recovery copy."""
from pathlib import Path
import datetime
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
target = Path('/Applications/Jellyfin Player.app')
executable = str(target / 'Contents/MacOS/Jellyfin Player')
if target.exists():
    subprocess.run([executable, 'stop'], timeout=15, capture_output=True)
    for _ in range(100):
        processes = subprocess.check_output(['ps', '-axo', 'command='], text=True).splitlines()
        if not any(command == executable for command in processes):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('The app is still closing; try again shortly.')
    backup = ROOT / 'work' / ('previous-' + datetime.datetime.now().strftime('%H%M%S') + '.app')
    target.rename(backup)
subprocess.run(['ditto', str(ROOT / 'work/dist/Jellyfin Player.app'), str(target)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(target)], check=True)
subprocess.run(['open', str(target)], check=True)
print('Installed and verified')
