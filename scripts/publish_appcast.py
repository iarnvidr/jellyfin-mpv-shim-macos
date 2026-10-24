"""Validate a tested appcast before the trusted workflow commits it to updates."""
import argparse
import hashlib
import json
from pathlib import Path
import release


def qualified_appcast(directory, current_feed, current_commit, version):
    directory = Path(directory)
    records = {mode: json.loads((directory / mode / 'result.json').read_text())
               for mode in ('legacy', 'current-host')}
    for mode, record in records.items():
        if record.get('passed') is not True or record.get('to') != version or record.get('mode') != mode:
            raise ValueError(f'{mode}: installation qualification is incomplete')
        if record.get('after_signatures', {}).get('valid') is not True:
            raise ValueError(f'{mode}: installed signatures were not verified')
    current = records['current-host']
    if current.get('manual_reopen') is not False or not current.get('new_pid'):
        raise ValueError('automatic relaunch was not verified')
    if not current.get('after_window', {}).get('windows'):
        raise ValueError('the relaunched app did not have a usable window')
    if (current.get('base_feed_commit') != current_commit or
            current.get('base_feed_sha256') != hashlib.sha256(current_feed).hexdigest()):
        raise ValueError('the update feed changed after qualification; rerun the check')
    metadata = current['metadata']
    expected = release.ASSET_ROOT + f'v{version}/Jellyfin-Player-{version}-Apple-Silicon.zip'
    if metadata.get('asset_url') != expected:
        raise ValueError('update archive does not match the qualified release')
    candidate = (directory / 'current-host/candidate-appcast.xml').read_bytes()
    if hashlib.sha256(candidate).hexdigest() != current.get('appcast_sha256'):
        raise ValueError('the tested appcast was modified')
    if candidate != release.update_feed(current_feed, metadata, 'v' + version):
        raise ValueError('appcast metadata differs from the qualified update')
    return candidate, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--current-feed', type=Path, required=True)
    parser.add_argument('--current-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate, metadata = qualified_appcast(args.evidence, args.current_feed.read_bytes(),
                                           args.current_commit, release.version())
    release.public_asset(metadata['asset_url'], metadata['length'])
    args.output.write_bytes(candidate)


if __name__ == '__main__':
    main()
