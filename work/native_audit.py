"""Strict Mach-O closure, architecture and deployment-target audit for app bundles."""
from pathlib import Path
import argparse, json, re, subprocess, sys
SYSTEM_PREFIXES=('/System/Library/','/usr/lib/')
OTOOL_DEPENDENCY_RE = re.compile(r'^\s*(.+?)\s+\(compatibility version ')
LOAD_COMMAND_SPLIT_RE = re.compile(r'(?=\nLoad command \d+)')


def parse_otool_dependencies(output):
    """Return load paths from otool -L output, excluding its image header/ID."""
    return [match.group(1) for line in output.splitlines()[1:]
            if (match := OTOOL_DEPENDENCY_RE.match(line))]


def load_command_blocks(output):
    return LOAD_COMMAND_SPLIT_RE.split(output)

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
        rel=str(path.relative_to(app)); archs=run('lipo','-archs',path).split()
        # otool -L starts with the image's own install ID for dylibs, while
        # executables start with a header "path:" line. Neither is a dependency.
        loads=run('otool','-L',path).splitlines()
        deps=parse_otool_dependencies('\n'.join(loads))
        bad=[d for d in deps if not d.startswith('@rpath/') and not d.startswith('@loader_path/') and not d.startswith('@executable_path/') and not d.startswith(SYSTEM_PREFIXES)]
        if bad: problems.append(f'{rel}: non-relative/non-system linkage: {bad}')
        if 'arm64' not in archs: problems.append(f'{rel}: missing arm64 architecture: {archs}')
        load=run('otool','-l',path)
        # Keep dylib identity distinct from actual LC_LOAD_* dependencies: -L
        # reports the identity as its first entry, which is not a load command.
        install_ids=[]
        load_commands=[]
        for block in load_command_blocks(load):
            cmd=re.search(r'\\bcmd (LC_[A-Z0-9_]+)', block)
            name=re.search(r'\\bname (.+?) \\(offset \\d+\\)', block)
            if not cmd or not name: continue
            if cmd.group(1) == 'LC_ID_DYLIB': install_ids.append(name.group(1))
            elif cmd.group(1).startswith('LC_LOAD_'): load_commands.append(name.group(1))
        # Only LC_BUILD_VERSION's minos is a deployment target; LC_VERSION_MIN_*
        # uses version, while dylib LC_ID_DYLIB also has a version field.
        targets=[]
        for block in re.split(r'(?=\nLoad command \d+)', load):
            if re.search(r'\bcmd LC_BUILD_VERSION\b', block):
                m=re.search(r'\bminos\s+(\d+(?:\.\d+){0,2})', block)
                if m: targets.append(m.group(1))
            elif re.search(r'\bcmd LC_VERSION_MIN_(?:MACOSX|IPHONEOS|TVOS|WATCHOS)\b', block):
                m=re.search(r'\bversion\s+(\d+(?:\.\d+){0,2})', block)
                if m: targets.append(m.group(1))
        if not targets: problems.append(f'{rel}: deployment target unavailable')
        elif any(tuple(map(int,(x.split('.')+['0'])[:2])) > (15,0) for x in targets): problems.append(f'{rel}: minimum OS exceeds macOS 15: {targets}')
        binaries.append({'path':rel,'architectures':archs,'minimum_os':targets or None,'install_ids':install_ids,'load_commands':load_commands,'dependencies':deps})
        files.append(rel)
    inventory=[]
    for p in sorted(app.rglob('*')):
        if p.is_file() or p.is_symlink(): inventory.append({'path':str(p.relative_to(app)),'type':'symlink' if p.is_symlink() else 'file'})
    return {'app':str(app),'binary_count':len(binaries),'binaries':binaries,'inventory':inventory,'problems':problems}
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('app',type=Path); a=p.parse_args(); result=audit(a.app); print(json.dumps(result,indent=2)); sys.exit(bool(result['problems']))
