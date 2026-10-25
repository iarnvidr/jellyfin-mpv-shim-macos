from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
from mac_menu import NativeMenus
from local_compat import patch_renderer


def entries(model):
    for item in model:
        yield item
        yield from entries(item.get('items', []))


class NativeMenuTests(unittest.TestCase):
    def setUp(self):
        self.ui = Mock(_browser=object())
        self.engine = SimpleNamespace(fullscreen=False, mute=False, ontop=False, window_minimized=False)
        self.state = dict(has_media=True, queue=dict(has_prev=False, has_next=True),
                          audio=[dict(id=2, label='English Stereo', selected=True)],
                          subtitles=[dict(id=-1, label='None', selected=False),
                                     dict(id=4, label='Danish', selected=True)])
        self.pm = Mock(_player=self.engine, _play_epoch=7)
        self.pm.osc_bridge.build_state.return_value = self.state
        self.pm.is_paused.return_value = False
        self.pm.get_volume.return_value = 98
        self.pm.put_task.side_effect = lambda task: task()
        self.updater = Mock()
        self.menu = NativeMenus(self.ui, self.pm, self.updater)

    def command(self, title):
        model = self.menu.model()
        return next(item['command'] for item in entries(model['menus'] + model['application'])
                    if item.get('title') == title)

    def test_tracks_keep_labels_selection_and_upstream_handlers(self):
        rows = list(entries(self.menu.model()['menus']))
        self.assertTrue(next(row for row in rows if row.get('title') == 'Danish')['checked'])
        self.assertEqual(self.menu.request(self.command('Danish')), {'ok': True})
        self.pm.osc_bridge.handle_action.assert_called_once_with(['set-sub', '4'])
        self.menu.request(self.command('English Stereo'))
        self.pm.osc_bridge.handle_action.assert_called_with(['set-audio', '2'])

    def test_commands_use_player_methods_and_preserve_syncplay_and_volume_limits(self):
        self.menu.request(self.command('Skip Forward 10 Seconds'))
        self.pm.seek.assert_called_once_with(10)
        self.menu.request(self.command('Increase Volume'))
        self.pm.set_volume.assert_called_once_with(100)
        self.menu.request(self.command('Enter Full Screen'))
        self.pm.set_fullscreen.assert_called_once_with(True, True)

    def test_disabled_and_stale_playback_commands_are_rejected(self):
        old = self.command('Danish')
        self.pm._play_epoch = 8
        self.assertEqual(self.menu.request(old), {'ok': False})
        self.assertEqual(self.menu.request('8:previous'), {'ok': False})
        self.state['has_media'] = False
        self.assertEqual(self.menu.request('8:set-sub:4'), {'ok': False})
        self.pm.put_task.assert_not_called()

    def test_browsing_disables_media_but_keeps_settings_and_updates(self):
        self.state['has_media'] = False
        rows = list(entries(self.menu.model()['menus']))
        self.assertFalse(next(row for row in rows if row.get('command') == '7:pause')['enabled'])
        self.menu.request('settings')
        self.ui._open_settings.assert_called_once_with('general')
        self.menu.request('updates')
        self.updater.assert_called_once_with()
        self.menu.request('show')
        self.ui.on_second_launch.assert_called_once_with()

    def test_player_right_click_callback_is_removed_from_shipped_renderer(self):
        source = Path(__file__).resolve().parents[1] / 'work/source/jellyfin_mpv_shim/mpvtk/renderer.lua'
        original = source.read_text()
        self.assertIn('state.mouse.down = true; on_rclick()', original)
        self.assertNotIn('state.mouse.down = true; on_rclick()', patch_renderer(original))


if __name__ == '__main__':
    unittest.main()
