#!/usr/bin/env python3
"""Exercise moved packaged macOS executables and collect native GUI evidence."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def main():
    if sys.platform != 'darwin':
        print('UNSUPPORTED: native smoke requires macOS; host is ' + sys.platform)
        return 0
    root=pathlib.Path(__file__).resolve().parents[1]
    app=root/'work/dist/Jellyfin Player.app'
    if not app.is_dir(): raise RuntimeError(f'packaged app missing: {app}')
    evidence=root/'outputs/macos-smoke-evidence'; evidence.mkdir(parents=True,exist_ok=True)
    base=pathlib.Path(tempfile.mkdtemp(prefix='jellyfin smoke ')); home=base/'home'; home.mkdir()
    moved=base/'MOVED app with spaces'/'Jellyfin Player.app'; moved.parent.mkdir(); shutil.copytree(app,moved,symlinks=True)
    env={**os.environ,'HOME':str(home),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','TMPDIR':str(base),'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8','DYLD_PRINT_LIBRARIES':'1'}
    result={'host':run(['/usr/bin/sw_vers']).stdout,'app':str(moved),'profile':str(home),'tests':[]}
    helper=moved/'Contents/Helpers/Mac Updater.app/Contents/MacOS/Mac Updater'
    if not helper.is_file(): raise RuntimeError(f'updater executable missing: {helper}')
    dyld=run([str(helper),'--dyld-smoke'],env=env,timeout=60)
    (evidence/'updater-dyld.log').write_text(dyld.stdout+'\n--- stderr ---\n'+dyld.stderr)
    framework=str(moved/'Contents/Frameworks/Sparkle.framework/')
    ok=dyld.returncode==0 and 'SPARKLE_HELPER_DYLD_OK' in dyld.stdout and framework in dyld.stdout+dyld.stderr
    result['tests'].append({'name':'moved updater loads bundled Sparkle','returncode':dyld.returncode,'framework':framework,'passed':ok})
    if not ok: raise RuntimeError('updater did not load Sparkle from moved bundle; see updater-dyld.log')
    exe=moved/'Contents/MacOS/Jellyfin Player'
    if not exe.is_file(): raise RuntimeError(f'main executable missing: {exe}')
    log=(evidence/'player.log').open('w')
    proc=subprocess.Popen([str(exe)],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.time()+60; visible=False; accessibility=False
        while time.time()<deadline:
            if proc.poll() is not None: raise RuntimeError(f'main app exited during startup: {proc.returncode}')
            remaining=deadline-time.time()
            if remaining <= 0: break
            probe=run(['/usr/bin/osascript','-e','tell application "System Events" to get name of every process whose name is "Jellyfin Player"'],timeout=min(10,remaining))
            if probe.returncode==0:
                visible='Jellyfin Player' in probe.stdout
                if visible: break
            elif 'not authorized' in (probe.stderr+probe.stdout).lower() or 'assistive' in (probe.stderr+probe.stdout).lower(): accessibility=True
            time.sleep(1)
        if not visible:
            if accessibility: raise RuntimeError('app process started but window/process query was denied by macOS Accessibility permissions')
            raise RuntimeError('main app process did not become visible in System Events')
        shot=run(['/usr/sbin/screencapture','-x',str(evidence/'player.png')],timeout=20)
        if shot.returncode: raise RuntimeError('screencapture failed: '+shot.stderr)
        result['tests'].append({'name':'main app visible','pid':proc.pid,'passed':True})
        player=moved/'Contents/Resources/mpv.app/Contents/MacOS/mpv'
        if not player.is_file(): raise RuntimeError(f'branded mpv executable missing: {player}')
        mpvlog=(evidence/'mpv.log').open('w')
        mpv=subprocess.Popen([str(player),'--no-config','--idle=yes','--force-window=yes','--keep-open=yes','--vo=null','lavfi://testsrc=size=160x90:rate=1'],env=env,stdout=mpvlog,stderr=subprocess.STDOUT)
        try:
            time.sleep(3)
            if mpv.poll() is not None: raise RuntimeError(f'branded mpv exited during synthetic playback: {mpv.returncode}')
            info=run(['/usr/bin/plutil','-p',str(moved/'Contents/Info.plist')])
            if info.returncode or 'Jellyfin Player' not in info.stdout: raise RuntimeError('app metadata verification failed')
            result['tests'].append({'name':'branded mpv synthetic lavfi playback alive','pid':mpv.pid,'passed':True})
        finally:
            if mpv.poll() is None: mpv.send_signal(__import__('signal').SIGTERM)
            try: mpv.wait(timeout=15)
            except subprocess.TimeoutExpired: mpv.kill(); mpv.wait()
            mpvlog.close()
        quit_result=run(['/usr/bin/osascript','-e','tell application "System Events" to tell process "Jellyfin Player" to keystroke "q" using {command down}'],timeout=10)
        if quit_result.returncode: proc.terminate()
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired: proc.terminate(); proc.wait(timeout=10)
        if proc.returncode not in (0,-15): raise RuntimeError(f'main app graceful quit failed: {proc.returncode}')
        result['tests'].append({'name':'main app graceful quit','returncode':proc.returncode,'passed':True})
    finally:
        if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
        log.close()
    (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2)); return 0

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc: print('SMOKE FAILED: '+str(exc),file=sys.stderr); sys.exit(1)
