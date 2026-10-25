import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work'))
import mac_settings


class NativeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.values = dict(enabled=True, speed=1.0, choice='a', sync_path='/downloads', secret='token')
        self.cfg = SimpleNamespace(
            FORM_TABS=['general'], LABELED_ENUMS={'choice': [('A', 'a'), ('B', 'b')]},
            ENUMS={}, RESTART_REQUIRED={'speed'}, NOTES={'speed': 'Restart required'},
            sections=lambda tab: [('Player', list(self.values))],
            get_settings=lambda: self.values,
            settings_schema=lambda: {'enabled': 'bool', 'speed': 'float', 'choice': 'str', 'sync_path': 'str'},
            label_for=lambda key: key.title(), is_nullable=lambda key: key == 'speed',
            coerce=lambda kind, value: float(value) if kind == 'float' else value)
        self.browser = Mock()
        self.browser._config.return_value = self.cfg
        self.browser._set_setting.side_effect = self.values.__setitem__
        self.player = Mock()
        self.player.put_task.side_effect = lambda task: task()

    def save(self, key, value):
        return mac_settings.request('settings-set:' + json.dumps(dict(key=key, value=value)), self.browser, self.player)

    def test_schema_excludes_private_and_download_relocation_fields(self):
        model = mac_settings.snapshot(self.browser)
        fields = model['tabs'][0]['groups'][0]['fields']
        self.assertEqual([field['key'] for field in fields], ['enabled', 'speed', 'choice'])
        self.assertNotIn('token', json.dumps(model))

    def test_saves_use_existing_side_effect_handler_and_coercion(self):
        self.assertEqual(self.save('speed', '1.25'), {'ok': True, 'restart': True})
        self.browser._set_setting.assert_called_once_with('speed', 1.25)
        self.assertTrue(self.save('speed', None)['ok'])

    def test_invalid_values_cannot_reach_save_handler(self):
        for key, value in [('secret', 'new'), ('sync_path', '/other'), ('enabled', 'false'),
                           ('enabled', None), ('choice', 'unknown'), ('speed', 'nan'), ('speed', 'bad')]:
            with self.subTest(key=key, value=value):
                self.assertFalse(self.save(key, value)['ok'])
        self.browser._set_setting.assert_not_called()
