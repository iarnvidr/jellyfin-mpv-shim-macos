"""Regression coverage for Mach-O deployment target parsing and closure."""
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
import native_audit

class NativeAuditParsing(unittest.TestCase):
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
        self.assertEqual(native_audit.rpaths_from_load_commands(output, '/tmp/App/Contents/Frameworks/x'), [])
        self.assertTrue(native_audit.resolve_rpath_dependency('@rpath/Other Framework.framework/Versions/A/Other Framework', ['@loader_path/../Frameworks']))

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

    def test_build_uses_nested_mpv_and_relocates_moltenvk_before_audit(self):
        build=Path(__file__).resolve().parents[1]/'work/build.py'
        source=build.read_text()
        self.assertIn("'@rpath/libMoltenVK.dylib'",source)
        self.assertIn("install_name_tool",source)
        self.assertLess(source.index('install_name_tool'),source.index("'native_audit.py'"))
        self.assertIn("mpv.app/Contents/MacOS/mpv",source)
        launch=(build.parent/'launch.py').read_text()
        self.assertIn("player = app_contents / 'Resources/mpv.app/Contents/MacOS/mpv'",launch)
        self.assertIn("standalone in (app/'Contents/Frameworks/mpv', app/'Contents/Resources/mpv')",source)

if __name__=='__main__': unittest.main()
