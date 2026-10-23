import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'macos_smoke.py'

def test_smoke_has_native_assertions_and_real_executables():
    source = SCRIPT.read_text()
    assert "'--dyld-smoke'" in source
    assert 'Contents/Frameworks/Sparkle.framework/' in source
    assert 'Contents/MacOS/Jellyfin Player' in source
    assert 'Contents/Resources/mpv.app/Contents/MacOS/mpv' in source
    assert 'lavfi://testsrc' in source
    assert 'screencapture' in source
    assert 'accessibility permissions' in source

def test_non_macos_is_explicitly_unsupported(monkeypatch, capsys):
    spec=importlib.util.spec_from_file_location('macos_smoke', SCRIPT)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys,'platform','linux')
    assert module.main()==0
    assert 'UNSUPPORTED' in capsys.readouterr().out
