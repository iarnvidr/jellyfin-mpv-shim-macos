"""Exercise Sparkle against unmodified published apps before exposing an appcast."""
import argparse
import functools
import getpass
import http.server
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'work'))
import release
from bundle_signing import sign_bundle, verify_bundle
from macos_smoke import PROBE_SOURCE, visible_descendant


def command(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def download(url, destination):
    request = urllib.request.Request(url, headers={'User-Agent': 'Jellyfin-Player-update-test'})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open('wb') as out:
        while data := response.read(1024 * 1024):
            out.write(data)


def released_archive(version, directory, verifier):
    base = release.ASSET_ROOT + f'v{version}/'
    name = f'Jellyfin-Player-{version}-Apple-Silicon.zip'
    archive = directory / name
    download(base + name, archive)
    download(base + 'SHA256SUMS', directory / 'SHA256SUMS')
    expected = dict(line.split('  ', 1)[::-1] for line in
                    (directory / 'SHA256SUMS').read_text().splitlines())
    if release.checksum(archive) != expected[name]:
        raise RuntimeError('Released archive checksum mismatch')
    download(base + 'signature.json', directory / 'signature.json')
    signature = json.loads((directory / 'signature.json').read_text())
    command(verifier, (ROOT / 'work/sparkle-public-key.txt').read_text().strip(),
            signature['edSignature'], archive)
    return archive, signature


def wait_window(probe, pid, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = visible_descendant(probe, pid)
        if state:
            return state
        time.sleep(.5)
    raise RuntimeError(f'No visible app window for launcher PID {pid}')


def wait_exit(pid, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(.1)
    raise RuntimeError(f'Process {pid} did not quit cleanly')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-version', default='0.2.1')
    parser.add_argument('--to-version', default='0.2.2')
    parser.add_argument('--legacy-install-only', action='store_true')
    parser.add_argument('--current-host-fixture', action='store_true')
    args = parser.parse_args()
    args.to_version = args.to_version.removeprefix('v')
    if args.current_host_fixture:
        args.from_version = args.to_version
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Run this test only on an isolated macOS GitHub runner')
    mode = 'current-host' if args.current_host_fixture else 'legacy'
    evidence = ROOT / 'outputs/sparkle-smoke-evidence' / mode
    evidence.mkdir(parents=True, exist_ok=True)
    result = {'from': args.from_version, 'to': args.to_version, 'passed': False,
              'mode': mode, 'manual_reopen': args.legacy_install_only}
    old_pid = None
    created_profile = False
    server = None
    try:
        with tempfile.TemporaryDirectory(prefix='jellyfin-sparkle-') as directory:
            temporary = Path(directory).resolve()
            verifier = temporary / 'verify-update'
            command('/usr/bin/xcrun', 'swiftc', ROOT / 'tests/native/VerifyUpdate.swift',
                    '-o', verifier)
            old = temporary / 'old'; old.mkdir()
            new = temporary / 'new'; new.mkdir()
            old_archive, _ = released_archive(args.from_version, old, verifier)
            new_archive, new_signature = released_archive(args.to_version, new, verifier)
            installed = temporary / 'Applications'; installed.mkdir()
            command('/usr/bin/ditto', '-x', '-k', old_archive, installed)
            app = installed / 'Jellyfin Player.app'
            if args.current_host_fixture:
                # Only the old test fixture is changed, never the target ZIP.
                # Exercise the current host as an older version without making
                # artificial public releases just for an updater test.
                info_path = app / 'Contents/Info.plist'
                info = plistlib.loads(info_path.read_bytes())
                info.update(CFBundleVersion='0.0.0', CFBundleShortVersionString='0.0.0')
                info_path.write_bytes(plistlib.dumps(info))
                sign_bundle(app)
                result['from'] = '0.0.0'
            result['before_signatures'] = verify_bundle(app)

            lock = dict(line.split('=', 1) for line in
                        (ROOT / 'work/native-dependencies.lock').read_text().splitlines()
                        if line and not line.startswith('#'))
            sparkle_tar = temporary / 'sparkle.tar.xz'
            download(lock['SPARKLE_URL'], sparkle_tar)
            if release.checksum(sparkle_tar) != lock['SPARKLE_SHA256']:
                raise RuntimeError('Sparkle tool checksum mismatch')
            sparkle = temporary / 'sparkle'; sparkle.mkdir()
            with tarfile.open(sparkle_tar) as archive:
                archive.extractall(sparkle, filter='data')
            harness = temporary / 'Update Test.app/Contents'
            (harness / 'MacOS').mkdir(parents=True)
            (harness / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'org.jellyfin.mpvshim.update-test',
                'CFBundleExecutable': 'AutoUpdate', 'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1', 'LSUIElement': True}))
            cli = harness / 'MacOS/AutoUpdate'
            command('/usr/bin/xcrun', 'clang', '-fobjc-arc', '-fblocks',
                    ROOT / 'tests/native/AutoUpdate.m', '-o', cli,
                    '-F', sparkle, '-framework', 'AppKit', '-framework', 'Sparkle',
                    '-Wl,-rpath,' + str(sparkle))

            feed = temporary / 'feed'; feed.mkdir()
            metadata = {'version': args.to_version, 'signature': new_signature['edSignature'],
                        'length': new_archive.stat().st_size, 'minimum_os': '15.7.9',
                        'asset_url': release.ASSET_ROOT + f'v{args.to_version}/' + new_archive.name,
                        'feed_url': release.FEED_URL, 'release_notes': 'Jellyfin Player update.'}
            (feed / 'appcast.xml').write_bytes(release.update_feed(
                b'<rss version="2.0"><channel><title>Jellyfin Player</title></channel></rss>',
                metadata, 'v' + args.to_version))
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(feed)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f'http://127.0.0.1:{server.server_port}/appcast.xml'

            launcher = temporary / 'launch-app'
            command('/usr/bin/xcrun', 'swiftc', ROOT / 'tests/native/LaunchApp.swift',
                    '-o', launcher, '-framework', 'AppKit')
            probe_source = temporary / 'probe.swift'; probe_source.write_text(PROBE_SOURCE)
            probe = temporary / 'probe'
            command('/usr/bin/xcrun', 'swiftc', probe_source, '-o', probe, '-framework', 'AppKit')
            # Use the normal profile path: Sparkle relaunches without --config.
            # The CI-only guard above prevents touching a developer's profile.
            profile = Path('/Users') / getpass.getuser() / 'Library/Application Support/jellyfin-mpv-shim'
            if profile.exists():
                raise RuntimeError('The isolated runner already has a Jellyfin profile')
            profile.mkdir(parents=True)
            created_profile = True
            (profile / 'conf.json').write_text(json.dumps({'mpv_ext': True, 'mpv_ext_path': None,
                                                         'video_volume': 37}))
            sentinel = profile / 'update-test-sentinel'; sentinel.write_text('retain this profile')
            home = ROOT / 'outputs/sparkle-test-home' / mode; home.mkdir(parents=True)
            env = {**os.environ, 'HOME': str(home), 'TMPDIR': '/tmp'}
            launch = command(launcher, app, env=env,
                             capture_output=True, text=True, timeout=30)
            old_pid = int(launch.stdout.strip().splitlines()[-1])
            result['old_pid'] = old_pid
            result['before_window'] = wait_window(probe, old_pid)
            owner_pid = json.loads((profile / 'instance.lock').read_text().splitlines()[2])['pid']
            snapshot = command(launcher, '--list', capture_output=True, text=True, timeout=10)
            (evidence / 'running-applications.json').write_text(snapshot.stdout)
            common = [str(cli), str(app), url]
            install_options = ['legacy'] if args.legacy_install_only else []
            for phase, options, timeout in [('discovery', ['probe'], 45), ('installation', install_options, 120)]:
                with (evidence / f'{phase}.log').open('w') as output:
                    completed = subprocess.run(common + options, env=env, stdout=output,
                                               stderr=subprocess.STDOUT, timeout=timeout)
                result[phase + '_status'] = completed.returncode
                if completed.returncode:
                    raise RuntimeError(f'Sparkle {phase} failed with status {completed.returncode}')

            info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
            if info['CFBundleShortVersionString'] != args.to_version:
                raise RuntimeError('Sparkle did not install the target version')
            result['after_signatures'] = verify_bundle(app)
            if sentinel.read_text() != 'retain this profile':
                raise RuntimeError('The shared profile was not retained')
            if json.loads((profile / 'conf.json').read_text()).get('video_volume') != 37:
                raise RuntimeError('The saved playback setting was not retained')
            if args.legacy_install_only:
                command(launcher, '--quit', old_pid)
                wait_exit(owner_pid)
                command(launcher, app, env=env, capture_output=True, text=True, timeout=30)
            else:
                wait_exit(old_pid)
                wait_exit(owner_pid)
            # Sparkle must restart the actual app, without the test launching it.
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,command='], text=True)
                new_pids = [int(row.strip().split(None, 1)[0]) for row in processes.splitlines()
                            if str(app / 'Contents/MacOS/Jellyfin Player') in row
                            and int(row.strip().split(None, 1)[0]) != old_pid]
                for pid in new_pids:
                    window = visible_descendant(probe, pid)
                    if window:
                        result.update(new_pid=pid, after_window=window, passed=True)
                        os.kill(pid, signal.SIGTERM)
                        wait_exit(pid)
                        break
                if result['passed']:
                    break
                time.sleep(.5)
            if not result['passed']:
                raise RuntimeError('The installed app did not relaunch with a visible window')
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        if server:
            server.shutdown()
        if old_pid:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for logs in (locals().get('home'), Path.home()):
            if logs:
                directory = logs / 'Library/Logs/Jellyfin MPV Shim'
                for filename in ('launcher.log', 'startup-diagnostic.json'):
                    source = directory / filename
                    if source.exists():
                        import shutil
                        shutil.copy2(source, evidence / (logs.name + '-' + filename))
        if created_profile:
            import shutil
            shutil.rmtree(profile)
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
