"""Explicit inside-out signing, including code nested under Resources."""
import argparse
import json
from pathlib import Path
import subprocess

MACHO_MAGICS = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca',
    'cafebabf', 'bfbafeca')}
BUNDLE_SUFFIXES = {'.app', '.framework', '.xpc', '.bundle'}


def is_macho(path):
    with path.open('rb') as stream:
        return stream.read(4) in MACHO_MAGICS


def signing_targets(app):
    app = Path(app).resolve()
    targets = []
    for path in app.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_file() and is_macho(path):
            targets.append(path)
        elif path.is_dir() and path.suffix in BUNDLE_SUFFIXES:
            # A .bundle directory can also be plain resources.
            if (path / 'Contents/Info.plist').is_file() or path.suffix == '.framework':
                targets.append(path)
    # Children precede their seals; the outer app is always last.
    return sorted(targets, key=lambda p: (-len(p.parts), str(p))) + [app]


def verify_bundle(app):
    app = Path(app).resolve()
    results = []
    for target in signing_targets(app):
        result = subprocess.run(['/usr/bin/codesign', '--verify', '--strict',
                                 '--all-architectures', str(target)],
                                capture_output=True, text=True, timeout=30)
        results.append({'path': str(target.relative_to(app)) or '.',
                        'valid': result.returncode == 0,
                        'diagnostic': (result.stdout + result.stderr).strip()})
    failed = [r for r in results if not r['valid']]
    if failed:
        raise ValueError('Invalid bundled signatures: ' + json.dumps(failed))
    return {'targets': results, 'valid': True}


def sign_bundle(app):
    for target in signing_targets(app):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-',
                        '--timestamp=none', str(target)], check=True, timeout=60)
    return verify_bundle(app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('sign', 'verify'))
    parser.add_argument('app', type=Path)
    args = parser.parse_args()
    print(json.dumps((sign_bundle if args.command == 'sign' else verify_bundle)(args.app), indent=2))
