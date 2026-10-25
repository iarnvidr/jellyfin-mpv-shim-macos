from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
from mac_media import snapshot


class NativeMediaTests(unittest.TestCase):
    def test_metadata_and_progress_keep_the_real_media_title(self):
        player = SimpleNamespace(_player=SimpleNamespace(media_title='Monk — S07E16',
            metadata={'artist': 'Monk'}, duration=2400, time_pos=123, pause=True, speed=1.25))
        model = snapshot(player, True, '9', {'pause': '9:system-pause'})
        self.assertEqual(model['title'], 'Monk — S07E16')
        self.assertEqual((model['position'], model['duration'], model['paused'], model['rate']), (123, 2400, True, 1.25))
        self.assertEqual(model['commands'], {'pause': '9:system-pause'})

    def test_stopped_or_disabled_playback_does_not_read_the_engine(self):
        player = SimpleNamespace()
        self.assertEqual(snapshot(player, False, '9', {}), {'active': False})
        with patch.dict(sys.modules, {'jellyfin_mpv_shim.conf': SimpleNamespace(settings=SimpleNamespace(media_keys=False))}):
            self.assertEqual(snapshot(player, True, '9', {}), {'active': False})

    def test_nonfinite_or_missing_engine_properties_have_serializable_defaults(self):
        player = SimpleNamespace(_player=SimpleNamespace(duration=float('nan'), time_pos=float('inf')))
        model = snapshot(player, True, '9', {})
        self.assertEqual((model['duration'], model['position']), (0, 0))
        self.assertEqual(model['title'], 'Jellyfin Player')
