"""Regression coverage for Mach-O deployment target parsing and closure."""
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
import native_audit


class DeploymentVersion(unittest.TestCase):
    def test_patch_versions_are_enforced(self):
        minimum = native_audit.deployment_version(native_audit.MINIMUM_MACOS)
        self.assertEqual(minimum, (15, 7, 9))
        self.assertLess(native_audit.deployment_version('15'), minimum)
        self.assertEqual(native_audit.deployment_version('15.0'), (15, 0, 0))
        self.assertLess(native_audit.deployment_version('15.7.8'), minimum)
        self.assertGreater(native_audit.deployment_version('15.7.10'), minimum)
        self.assertGreater(native_audit.deployment_version('16.0'), minimum)

class NativeAuditParsing(unittest.TestCase):
    def test_external_runpaths_are_removed_without_removing_bundle_or_apple_paths(self):
        values=['@executable_path/lib','/opt/homebrew/Cellar/vulkan-loader/1.4/lib','@loader_path/../Frameworks','/usr/lib','/tmp/old-build/lib']
        output='\n'.join(f'Load command {i}\n cmd LC_RPATH\n path {path} (offset 12)' for i,path in enumerate(values))
        self.assertEqual(native_audit.external_runpaths(output),[values[1],values[4]])
    def test_otool_load_parser_ignores_image_header_and_extracts_spaced_paths(self):
        output='''/tmp/Jellyfin MPV Shim.app/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle:\n\t/Users/runner/work/Jellyfin MPV Shim.app/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle (compatibility version 1.0.0, current version 2.0.0)\n\t@rpath/Other Framework.framework/Versions/A/Other Framework (compatibility version 1.0.0, current version 1.0.0)\n'''
        deps=native_audit.parse_otool_dependencies(output)
        self.assertEqual(deps,['/Users/runner/work/Jellyfin MPV Shim.app/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle','@rpath/Other Framework.framework/Versions/A/Other Framework'])

    def test_otool_l_multiple_blocks_extracts_real_load_ids_and_rpaths(self):
        output = '''Load command 0\n      cmd LC_BUILD_VERSION\n  minos 11.0\nLoad command 1\n      cmd LC_ID_DYLIB\n         name @rpath/libThing.dylib (offset 24)\nLoad command 2\n      cmd LC_LOAD_DYLIB\n         name @rpath/Other Framework.framework/Versions/A/Other Framework (offset 24)\nLoad command 3\n      cmd LC_RPATH\n         path @loader_path/../Frameworks (offset 12)\nLoad command 4\n      cmd LC_LOAD_DYLIB\n         name /usr/lib/libSystem.B.dylib (offset 24)\n'''
        blocks = native_audit.load_command_blocks(output)
        commands = [b for b in blocks if 'cmd LC_' in b]
        self.assertTrue(any('cmd LC_LOAD_DYLIB' in b for b in commands))
        self.assertTrue(any('cmd LC_ID_DYLIB' in b for b in commands))
        self.assertEqual(native_audit.rpaths_from_load_commands(output, '/tmp/App/Contents/Frameworks/x'), ['/tmp/App/Contents/Frameworks'])
        self.assertTrue(native_audit.resolve_rpath_dependency('@rpath/Other Framework.framework/Versions/A/Other Framework', ['@loader_path/../Frameworks']))

    def test_rpath_resolution_uses_inherited_loader_runpaths_and_rejects_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            libs=root/'Frameworks'
            libs.mkdir()
            (libs/'libNested.dylib').touch()
            dep='@rpath/libNested.dylib'
            self.assertTrue(any(Path(c).exists() for c in native_audit.resolve_rpath_dependency(dep,[str(libs)])))
            self.assertFalse(any(Path(c).exists() for c in native_audit.resolve_rpath_dependency('@rpath/missing.dylib',[str(libs)])))

    def test_version_fields_are_not_misread_as_minimum_os(self):
        load = '''Load command 0\n      cmd LC_BUILD_VERSION\n  minos 11.0\n sdk 26.0\nLoad command 1\n      cmd LC_ID_DYLIB\n current version 26.0.0\n compatibility version 1.0.0\n'''
        blocks = __import__('re').split(r'(?=\nLoad command \d+)', load)
        targets=[]
        import re
        for block in blocks:
            if re.search(r'\bcmd LC_BUILD_VERSION\b',block):
                m=re.search(r'\bminos\s+(\d+(?:\.\d+){0,2})',block)
                if m: targets.append(m.group(1))
            elif re.search(r'\bcmd LC_VERSION_MIN_(?:MACOSX|IPHONEOS|TVOS|WATCHOS)\b',block):
                m=re.search(r'\bversion\s+(\d+(?:\.\d+){0,2})',block)
                if m: targets.append(m.group(1))
        self.assertEqual(targets,['11.0'])

    def test_so_dependency_closure_inherits_module_rpath_and_follows_nested_loads(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'Player.app'
            main=app/'Contents/MacOS/Jellyfin Player'
            pillow=app/'Contents/Frameworks/PIL/Pillow.so'
            dylibs=pillow.parent/'.dylibs'
            nested=dylibs/'libnested.dylib'
            leaf=dylibs/'libleaf.dylib'
            for path in (main,pillow,nested,leaf):
                path.parent.mkdir(parents=True,exist_ok=True); path.touch()
            loads={
                str(main): 'Load command 0\\n cmd LC_RPATH\\n path @executable_path/../Frameworks (offset 12)',
                str(pillow): 'Load command 0\\n cmd LC_RPATH\\n path @loader_path/.dylibs (offset 12)\\nLoad command 1\\n cmd LC_LOAD_DYLIB\\n name @rpath/libnested.dylib (offset 24)',
                str(nested): 'Load command 0\\n cmd LC_LOAD_DYLIB\\n name @rpath/libleaf.dylib (offset 24)',
                str(leaf): '',
            }
            deps={str(main):[],str(pillow):['@rpath/libnested.dylib'],str(nested):['@rpath/libleaf.dylib'],str(leaf):[]}
            records=[]
            for path in (main,pillow,nested,leaf):
                records.append({'path':str(path.relative_to(app)),'_load':loads[str(path)],'dependencies':deps[str(path)]})
            indexed={str(app/r['path']):r for r in records}
            stack=native_audit.context_rpaths(str(pillow),loads[str(pillow)],native_audit.context_rpaths(str(main),loads[str(main)],executable=str(main)),executable=str(main))
            self.assertIn(str(dylibs),stack)
            self.assertTrue(any(Path(candidate).exists() for candidate in native_audit.resolve_rpath_dependency(deps[str(pillow)][0],stack)))
            wrong=native_audit.resolve_rpath_dependency(deps[str(pillow)][0],[str(app/'Contents/Frameworks')])
            self.assertFalse(any(Path(candidate).exists() for candidate in wrong))
            # Verify nested dependency is discoverable with the same propagated stack.
            nested_stack=native_audit.context_rpaths(str(nested),loads[str(nested)],stack,executable=str(main))
            self.assertTrue(any(Path(candidate).exists() for candidate in native_audit.resolve_rpath_dependency(deps[str(nested)][0],nested_stack)))

    def test_walk_queue_is_deque_and_state_limit_is_explicit(self):
        self.assertEqual(native_audit.MAX_AUDIT_STATES, 100_000)
        source=(Path(native_audit.__file__).read_text())
        self.assertIn('queue=deque(',source)
        self.assertIn('queue.popleft()',source)
        self.assertIn('exceeded',source)

    def test_build_uses_nested_mpv_and_relocates_moltenvk_before_audit(self):
        build=Path(__file__).resolve().parents[1]/'work/build.py'
        source=build.read_text()
        self.assertIn("'@rpath/libMoltenVK.dylib'",source)
        self.assertIn("install_name_tool",source)
        self.assertLess(source.index('install_name_tool'),source.index("'native_audit.py'"))
        self.assertIn("mpv.app/Contents/MacOS/mpv",source)
        self.assertIn('timeout=180',source)
        self.assertIn('timeout=30',source)
        self.assertIn('BUILD_STAGE',source)
        launch=(build.parent/'launch.py').read_text()
        self.assertIn("player = app_contents / 'Resources/mpv.app/Contents/MacOS/mpv'",launch)
        self.assertIn("core/'Frameworks/mpv'",source)
        self.assertIn("core/'Resources/mpv'",source)

if __name__=='__main__': unittest.main()
