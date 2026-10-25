from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
from mac_volume import adjust_volume, patch_sliders


class VolumeBoostTests(unittest.TestCase):
    def test_video_and_music_sliders_use_the_full_boost_range(self):
        nodes = [dict(id='hud-vol', t='slider', max=100, value=175),
                 dict(id='np-vol', t='slider', max=100, value=200),
                 dict(id='seek', t='slider', max=500, value=30)]
        patch_sliders(nodes)
        self.assertEqual([node['max'] for node in nodes], [200, 200, 500])
        self.assertEqual(nodes[0]['tip'], 'Volume: 175%')
        self.assertEqual(nodes[1]['tip'], 'Volume: 200%')

    def test_repeated_steps_resolve_current_volume_when_executed(self):
        queue, volume = [], [98]
        player = Mock()
        player.get_volume.side_effect = lambda percent: volume[0]
        player.set_volume.side_effect = lambda value: volume.__setitem__(0, value)
        gateway = SimpleNamespace(_act=queue.append)
        for _ in range(25):
            adjust_volume(gateway, 5)
        player.get_volume.assert_not_called()
        for task in queue:
            task(player)
        self.assertEqual(volume[0], 200)
        queue.clear()
        adjust_volume(gateway, -500)
        queue.pop()(player)
        self.assertEqual(volume[0], 0)

    def test_unavailable_player_does_not_set_a_volume(self):
        player = Mock()
        player.get_volume.return_value = None
        adjust_volume(SimpleNamespace(_act=lambda task: task(player)), 5)
        player.set_volume.assert_not_called()
