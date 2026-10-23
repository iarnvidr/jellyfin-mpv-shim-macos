"""Strict Mach-O closure, architecture and deployment-target audit for app bundles."""
from pathlib import Path
from collections import deque
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


def external_runpaths(output):
    """Raw LC_RPATH values to remove before signing a self-contained app."""
    result=[]
    for block in load_command_blocks(output):
        if re.search(r'\bcmd LC_RPATH\b',block):
            match=re.search(r'\bpath (.+?) \(offset \d+\)',block)
            if match and not match[1].startswith(('@loader_path/','@executable_path/',*SYSTEM_PREFIXES)):
                result.append(match[1])
    return list(dict.fromkeys(result))

LOAD_COMMAND_TYPES = {'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB'}

def parse_load_dependencies(output):
    """Return actual dylib loads, never LC_ID_DYLIB install identities."""
    result=[]
    for block in load_command_blocks(output):
        cmd=re.search(r'\bcmd (LC_[A-Z0-9_]+)', block)
        name=re.search(r'\bname (.+?) \(offset \d+\)', block)
        if cmd and cmd.group(1) in LOAD_COMMAND_TYPES and name:
            result.append(name.group(1))
    return result

def expand_path(value, executable, loader):
    if value.startswith('@executable_path'):
        return str(Path(executable).parent / value[len('@executable_path'):].lstrip('/'))
    if value.startswith('@loader_path'):
        return str(Path(loader).parent / value[len('@loader_path'):].lstrip('/'))
    return value

def rpaths_from_load_commands(output, image, executable=None):
    result=[]
    for block in load_command_blocks(output):
        if re.search(r'\bcmd LC_RPATH\b', block):
            m=re.search(r'\bpath (.+?) \(offset \d+\)', block)
            if m:
                value=m.group(1)
                value=expand_path(value, executable or image, image)
                result.append(str(Path(value).resolve()) if not value.startswith('@') else value)
    return result

def resolve_rpath_dependency(dep, rpaths):
    if not dep.startswith('@rpath/'): return []
    suffix=dep[len('@rpath/'):]
    return [str(Path(r).joinpath(suffix)) for r in rpaths]


def executable_type(load_commands):
    """Read Mach-O filetype (MH_EXECUTE is 2) from otool -hv."""
    match = re.search(r'\bEXECUTE\b', load_commands)
    return match is not None


def context_rpaths(image, load, inherited=(), executable=None):
    """Return this loader's runpaths appended to the inherited dyld stack."""
    return list(dict.fromkeys([*inherited, *rpaths_from_load_commands(load, image, executable)]))

MAX_AUDIT_STATES = 100_000


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
        load=run('otool','-l',path)
        deps=parse_load_dependencies(load)
        bad=[d for d in deps if not d.startswith('@rpath/') and not d.startswith('@loader_path/') and not d.startswith('@executable_path/') and not d.startswith(SYSTEM_PREFIXES)]
        if bad: problems.append(f'{rel}: non-relative/non-system linkage: {bad}')
        if 'arm64' not in archs: problems.append(f'{rel}: missing arm64 architecture: {archs}')
        rpaths=rpaths_from_load_commands(load,path)
        for rpath in rpaths:
            if not rpath.startswith(SYSTEM_PREFIXES) and not Path(rpath).resolve().is_relative_to(app):
                problems.append(f'{rel}: external runtime search path: {rpath}')
        # The graph is rooted only at actual MH_EXECUTE images. Each traversal
        # carries the dyld stack inherited from its parent plus this loader's
        # LC_RPATH entries; unrelated helper roots never leak search paths.
        for dep in deps:
            if dep.startswith('@loader_path/'):
                candidate=Path(path.parent / dep[len('@loader_path/'):])
                if not candidate.exists(): problems.append(f'{rel}: unresolved dependency: {dep}')
            elif dep.startswith('@executable_path/'):
                pass
        # Keep dylib identity distinct from actual LC_LOAD_* dependencies: -L
        # reports the identity as its first entry, which is not a load command.
        install_ids=[]
        load_commands=[]
        for block in load_command_blocks(load):
            cmd=re.search(r'\bcmd (LC_[A-Z0-9_]+)', block)
            name=re.search(r'\bname (.+?) \(offset \d+\)', block)
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
        binaries.append({'path':rel,'architectures':archs,'minimum_os':targets or None,'install_ids':install_ids,'load_commands':load_commands,'dependencies':deps,'_rpaths':rpaths,'_load':load})
        files.append(rel)
    # Build a graph keyed by canonical bundle paths; repeated visits are kept
    # distinct when inherited stacks differ, since that changes @rpath lookup.
    by_path={str(app / b['path']): b for b in binaries}
    roots=[]
    for path, binary in by_path.items():
        try: header=run('otool','-hv',path)
        except (OSError,subprocess.CalledProcessError): continue
        if executable_type(header): roots.append(path)
    main_exe=str(app/'Contents/MacOS/Jellyfin Player')
    queue=deque((root,root,context_rpaths(root,by_path[root]['_load'], executable=root)) for root in roots)
    # Python extensions run under the main executable's dyld stack. Seed them
    # before traversal; normal graph walking then follows their transitive loads.
    if main_exe in by_path:
        main_stack=context_rpaths(main_exe,by_path[main_exe]['_load'],executable=main_exe)
        for module,b in by_path.items():
            if module.endswith('.so'):
                queue.append((module,main_exe,context_rpaths(module,b['_load'],main_stack,executable=main_exe)))
    visited=set(); unresolved=set()
    while queue:
        loader, executable, stack=queue.popleft()
        # Paths are ordered: dyld resolves the first existing candidate. Keep
        # root and executable identity, but canonicalize aliases for cycle checks.
        stack=tuple(dict.fromkeys(str(Path(p).resolve()) if not p.startswith('@') else p for p in stack))
        state=(loader,executable,stack)
        if state in visited: continue
        visited.add(state)
        if len(visited) > MAX_AUDIT_STATES:
            raise RuntimeError(f'native audit exceeded {MAX_AUDIT_STATES} distinct (root, loader, search-path) states; possible pathological rpath graph')
        b=by_path[loader]
        for dep in b['dependencies']:
            if dep.startswith('@rpath/'):
                candidates=resolve_rpath_dependency(dep,stack)
            else:
                expanded=expand_path(dep,executable,loader)
                candidates=[expanded] if dep.startswith(('@loader_path/','@executable_path/')) else []
            target=next((str(Path(c).resolve()) for c in candidates if Path(c).exists()),None)
            if target is None:
                if candidates: unresolved.add((loader,dep))
                continue
            if not Path(target).is_relative_to(app) and not target.startswith(SYSTEM_PREFIXES):
                problems.append(f'{Path(loader).relative_to(app)}: dependency resolves outside the bundle: {dep} -> {target}')
            if target in by_path:
                child_stack=context_rpaths(target,by_path[target]['_load'],stack, executable=executable)
                queue.append((target,executable,child_stack))
    for loader,dep in sorted(unresolved):
        problems.append(f"{Path(loader).relative_to(app)}: unresolved @rpath dependency: {dep}")
    icd=app/'Contents/Resources/mpv.app/Contents/Resources/vulkan/icd.d/MoltenVK_icd.json'
    try:
        icd_data=json.loads(icd.read_text())
        driver=(icd.parent/icd_data['ICD']['library_path']).resolve()
        expected=(app/'Contents/Resources/mpv.app/Contents/Frameworks/libMoltenVK.dylib').resolve()
        if driver != expected or not driver.is_file():
            problems.append(f'Vulkan ICD must resolve to bundled MoltenVK: {driver}')
    except (OSError,ValueError,KeyError,TypeError) as error:
        problems.append(f'Invalid bundled Vulkan ICD: {error}')
    for binary in binaries:
        binary.pop('_load',None); binary.pop('_rpaths',None)
    inventory=[]
    for p in sorted(app.rglob('*')):
        if p.is_file() or p.is_symlink(): inventory.append({'path':str(p.relative_to(app)),'type':'symlink' if p.is_symlink() else 'file'})
    return {'app':str(app),'binary_count':len(binaries),'binaries':binaries,'inventory':inventory,'problems':problems}
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('app',type=Path); a=p.parse_args(); result=audit(a.app); print(json.dumps(result,indent=2)); sys.exit(bool(result['problems']))
