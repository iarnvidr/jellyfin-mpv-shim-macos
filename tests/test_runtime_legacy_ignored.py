"""Legacy component-update state must never be consulted during app startup."""
import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_legacy_runtime_modules_are_retired():
    assert not (ROOT / 'work/runtime_update.py').exists()
    assert not (ROOT / 'work/managed_launch.py').exists()


def test_launcher_does_not_select_external_runtime():
    source = (ROOT / 'work/launch.py').read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert 'runtime_update' not in names
    assert 'managed_launch.py' not in source
    assert 'execve' not in source


def test_legacy_updates_are_fail_closed_without_key():
    source = (ROOT / 'work/mac_update.py').read_text()
    assert 'Component updates are retired' in source
    assert 'import runtime_update' not in source
    assert 'pypi.org' not in source
    assert 'urllib.request' not in source
    assert 'def _install' not in source


def test_upstream_component_banner_is_suppressed():
    source = (ROOT / 'work/local_compat.py').read_text()
    assert 'self.new_version = result' not in source
    assert 'def check_updates(self):\n        return False' in source


def test_scroll_bridge_remains_installed():
    source = (ROOT / 'work/local_compat.py').read_text()
    assert 'DYLD_INSERT_LIBRARIES' in source
    assert 'mpvtk-native-scroll' in source
