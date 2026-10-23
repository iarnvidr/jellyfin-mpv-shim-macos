"""Strict Mach-O closure, architecture and deployment-target audit for app bundles."""
from pathlib import Path
import argparse, json, re, subprocess, sys
SYSTEM_PREFIXES=('/System/Library/','/usr/lib/')

def apple(tool):
    p=Path('/usr/bin')/tool
    if p.exists(): return str(p)
    try: return subprocess.check_output(['/usr/bin/xcrun','--find',tool],text=True).strip()
    except (OSError,subprocess.CalledProcessError): raise RuntimeError(f'Apple tool unavailable: {tool}')

def run(tool,*args): return subprocess.check_output([apple(tool),*map(str,args)],text=True,stderr=subprocess.STDOUT)
def audit(app):
    app=Path(app).resolve(); problems=[]; binaries=[]; files=[]
    for path in sorted(app.rglob('*')):
        if path.is_symlink() or not path.is_file(): continue
        try: kind=run('file','-b',path)
        except (OSError,subprocess.CalledProcessError): continue
        if 'Mach-O' not in kind: continue
        rel=str(path.relative_to(app)); archs=run('lipo','-archs',path).split(); loads=run('otool','-L',path).splitlines()[1:]
        deps=[line.strip().split(' (',1)[0] for line in loads]
        bad=[d for d in deps if not d.startswith('@rpath/') and not d.startswith('@loader_path/') and not d.startswith('@executable_path/') and not d.startswith(SYSTEM_PREFIXES)]
        if bad: problems.append(f'{rel}: non-relative/non-system linkage: {bad}')
        if 'arm64' not in archs: problems.append(f'{rel}: missing arm64 architecture: {archs}')
        load=run('otool','-l',path); targets=re.findall(r'\b(?:minos|version)\s+(\d+(?:\.\d+){0,2})',load)
        if not targets: problems.append(f'{rel}: deployment target unavailable')
        elif any(tuple(map(int,x.split('.'))) > (15,0) for x in targets): problems.append(f'{rel}: minimum OS exceeds macOS 15: {targets}')
        binaries.append({'path':rel,'architectures':archs,'minimum_os':targets or None,'dependencies':deps})
        files.append(rel)
    inventory=[]
    for p in sorted(app.rglob('*')):
        if p.is_file() or p.is_symlink(): inventory.append({'path':str(p.relative_to(app)),'type':'symlink' if p.is_symlink() else 'file'})
    return {'app':str(app),'binary_count':len(binaries),'binaries':binaries,'inventory':inventory,'problems':problems}
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('app',type=Path); a=p.parse_args(); result=audit(a.app); print(json.dumps(result,indent=2)); sys.exit(bool(result['problems']))
