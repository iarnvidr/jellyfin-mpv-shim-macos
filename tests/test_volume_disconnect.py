from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
from local_compat import patch_volume_persistence


class VolumePersistence(unittest.TestCase):
    def setUp(self):
        class Manager:
            pass
        self.settings = SimpleNamespace(music_volume=25, video_volume=50, save=Mock())
        patch_volume_persistence(SimpleNamespace(
            PlayerManager=Manager, _mpv_errors=(BrokenPipeError, TimeoutError),
            settings=self.settings))
        self.manager = Manager()
        self.manager._video = object()
        self.manager._current_is_audio = Mock(return_value=False)

    def test_dead_or_unresponsive_engine_does_not_break_timeline(self):
        for error in (BrokenPipeError, TimeoutError, TypeError):
            with self.subTest(error=error):
                engine = Mock()
                type(engine).volume = PropertyMock(side_effect=error)
                self.manager._player = engine
                self.manager._maybe_save_volume()
                self.settings.save.assert_not_called()

    def test_changed_volume_is_saved_once_in_the_correct_bucket(self):
        self.manager._player = SimpleNamespace(volume=60)
        self.manager._maybe_save_volume()
        self.manager._maybe_save_volume()
        self.assertEqual(self.settings.video_volume, 60)
        self.settings.save.assert_called_once()
        self.manager._current_is_audio.return_value = True
        self.manager._player.volume = 30
        self.manager._maybe_save_volume()
        self.assertEqual(self.settings.music_volume, 30)
        self.assertEqual(self.settings.video_volume, 60)

    def test_unrelated_errors_remain_visible(self):
        self.manager._player = SimpleNamespace(volume='invalid')
        with self.assertRaises(ValueError):
            self.manager._maybe_save_volume()
