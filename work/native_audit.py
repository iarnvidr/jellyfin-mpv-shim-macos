"""Audits native Mach-O dependencies and deployment targets in a built app."""
from pathlib import Path
import argparse, json, re, subprocess, sys

def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)

def audit(app):
    problems, binaries = [], []
    for path in app.rglob('*'):
        if not path.is_file():
            continue
        try:
            kind = run('file', '-b', str(path))
        except (OSError, subprocess.CalledProcessError):
            continue
        if 'Mach-O' not in kind:
            continue
        deps = run('otool', '-L', str(path))
        bad = [line.strip().split(' (', 1)[0] for line in deps.splitlines()[1:]
               if '/opt/homebrew' in line or '/usr/local/Cellar' in line]
        if bad: problems.append(f'{path}: external Homebrew linkage: {bad}')
        load = run('otool', '-l', str(path))
        targets = re.findall(r'\bminos\s+(\d+(?:\.\d+){0,2})', load)
        binaries.append({'path': str(path.relative_to(app)), 'minimum_os': targets or None})
        if not targets:
            problems.append(f'{path}: deployment target unavailable (inspect load commands)')
        elif any(tuple(map(int, x.split('.'))) < (15, 0) for x in targets):
            pass  # Lower deployment targets are compatible with the macOS 15 floor.
    return {'app': str(app), 'binary_count': len(binaries), 'binaries': binaries, 'problems': problems}

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('app',type=Path); a=p.parse_args()
    result=audit(a.app); print(json.dumps(result,indent=2))
    sys.exit(bool(result['problems']))
