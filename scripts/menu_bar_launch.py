"""Launch the actual bundle through LaunchServices and observe its real PID."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time


class LaunchedApplication:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        if self.poll() is None:
            os.kill(self.pid, signal.SIGTERM)

    def kill(self):
        if self.poll() is None:
            os.kill(self.pid, signal.SIGKILL)

    def wait(self, timeout=15):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('LaunchServices application', timeout)
            time.sleep(0.2)
        return self.returncode


def launch(app, config, env, log, probe, through_launchservices=False):
    if not through_launchservices:
        return subprocess.Popen([str(app / 'Contents/MacOS/Jellyfin Player'), '--config', str(config)],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    command = ['/usr/bin/open', '-n', '-a', str(app)]
    # open --env is Apple's supported per-launch environment API. The app is
    # still launched by LaunchServices, not as a child of this Python process.
    for key in ('JELLYFIN_PLAYER_MENU_DIAGNOSTICS', 'JELLYFIN_MENU_PROBE_OUTPUT', 'JMS_TEST_OBSERVE'):
        if key in env:
            command.extend(['--env', key + '=' + env[key]])
    command.extend(['--args', '--config', str(config)])
    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        state = json.loads(subprocess.run([str(probe)], check=True, capture_output=True, text=True).stdout)
        candidates = [a for a in state['jellyfinProcesses']
                      if a['bundle'] == 'org.jellyfin.mpvshim.local'
                      and Path(a['bundlePath']).resolve() == app.resolve()]
        if len(candidates) == 1:
            return LaunchedApplication(candidates[0]['pid'])
        time.sleep(0.5)
    raise RuntimeError(f'LaunchServices did not register exact bundle: {app}')
