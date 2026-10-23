"""Regression coverage for Mach-O deployment target parsing and closure."""
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
import native_audit

class NativeAuditParsing(unittest.TestCase):
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
        self.assertIn("player = resources / 'mpv'",launch)
        self.assertIn("standalone.symlink_to('mpv.app/Contents/MacOS/mpv')",source)

if __name__=='__main__': unittest.main()
