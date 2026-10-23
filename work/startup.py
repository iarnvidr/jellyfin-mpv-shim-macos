"""Startup diagnostics that work before the Python browser has a window."""
from collections import deque
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import threading

ENGINE_OUTPUT = deque(maxlen=32)
ENGINE_PROCESS = None
ENGINE_ATTEMPTS = 0
ENGINE_FAILURE = None
WINDOW_ACTIVATION = None


class StartupFailure(RuntimeError):
    pass


def redact(text):
    text = re.sub(r'https?://\S+', '[server address omitted]', str(text))
    text = re.sub(r'(?im)\bauthorization\s*[:=]\s*[^\r\n]+', 'Authorization=[omitted]', text)
    text = re.sub(r'''(?i)((?:access[_-]?)?token|authorization|password|api[_-]?key|X-Emby-Token)["']?[\s:=]+["']?[^\s,"'}]+''', r'\1=[omitted]', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b', '[address omitted]', text)
    return text.replace(str(Path.home()), '~')[:16384]


def record_engine(process):
    global ENGINE_PROCESS, ENGINE_ATTEMPTS
    ENGINE_PROCESS = process
    ENGINE_ATTEMPTS += 1
    def read():
        # Drain the pipe continuously; never let diagnostic capture block mpv.
        try:
            for line in iter(lambda: process.stdout.readline(1024), b''):
                if isinstance(line, bytes): line = line.decode('utf-8', 'replace')
                ENGINE_OUTPUT.append(redact(line[:1024]).rstrip())
        finally:
            process.stdout.close()
    threading.Thread(target=read, daemon=True).start()


def signature_results(player):
    contents = Path(player).parent.parent
    targets = [contents.parent, Path(player), contents / 'Frameworks/libMoltenVK.dylib']
    results = []
    for target in targets:
        try:
            check = subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(target)],
                                   capture_output=True, text=True, timeout=10,
                                   env={k:v for k,v in os.environ.items() if not k.startswith('DYLD_')})
            results.append({'path': str(target), 'valid': check.returncode == 0,
                            'diagnostic': redact(check.stdout + check.stderr)})
        except (OSError, subprocess.TimeoutExpired) as error:
            results.append({'path': str(target), 'valid': None, 'diagnostic': type(error).__name__})
    return results


def write_report(error, app, player, logs):
    app, logs = Path(app), Path(logs)
    signatures = signature_results(player)
    status = ENGINE_PROCESS.poll() if ENGINE_PROCESS else None
    # Engine startup diagnostics only. Do not copy browser/server/script output
    # or Python tracebacks that can contain private URLs or account data.
    error_terms = ('library not loaded:', 'referenced from:', 'reason:', 'code signature',
                   'invalid page', 'error parsing option', 'failed to initialize',
                   'error opening', 'option not found', 'dyld[')
    output = '\n'.join(line for line in ENGINE_OUTPUT if any(term in line.lower() for term in error_terms))
    if isinstance(error, StartupFailure):
        reason = str(error)
    elif any(item['valid'] is False for item in signatures):
        reason = 'A bundled player signature is invalid. Download a corrected release; security approval cannot repair this.'
    elif not Path(player).is_file():
        reason = 'The bundled player is missing. Reinstall the complete app.'
    elif 'Library not loaded:' in output or 'image not found' in output:
        reason = 'macOS could not load a player dependency.'
    elif (ENGINE_FAILURE and 'timed out' in ENGINE_FAILURE.lower()) or (status is None and ENGINE_ATTEMPTS):
        reason = 'The player did not make its IPC connection before the startup timeout.'
    elif status is not None:
        reason = f'The player exited during startup (status {status}).'
        if status < 0: reason += f' Termination signal: {-status}.'
    else:
        reason = 'Jellyfin Player could not finish starting.'
    import plistlib
    with (app/'Contents/Info.plist').open('rb') as source:
        info = plistlib.load(source)
    report = {'app': str(app), 'version': info.get('CFBundleShortVersionString'),
              'macOS': platform.mac_ver()[0], 'architecture': platform.machine(),
              'engine': str(player), 'attempts': ENGINE_ATTEMPTS, 'exit_status': status,
              'reason': redact(reason), 'error_type': type(error).__name__,
              'signature_checks': signatures, 'recent_engine_errors': output,
              'log_directory': str(logs)}
    logs.mkdir(parents=True, exist_ok=True)
    path = logs/'startup-diagnostic.json'
    path.write_text(json.dumps(report, indent=2)+'\n')
    path.chmod(0o600)
    return path, reason


def show_error(app, report, message):
    helper = Path(app)/'Contents/Helpers/Jellyfin Player Diagnostics.app/Contents/MacOS/Jellyfin Player Diagnostics'
    # Separate AppKit executable: works even when Python/mpv cannot create UI.
    subprocess.run([str(helper), str(report), message], check=False)
