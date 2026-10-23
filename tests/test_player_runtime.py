from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
from player_runtime import player_environment
from startup import redact


class RuntimeIsolation(unittest.TestCase):
    def test_bundle_mode_and_drivers_override_inherited_homebrew_discovery(self):
        player=Path('/Applications/Jellyfin Player.app/Contents/Resources/mpv.app/Contents/MacOS/mpv')
        inherited={'HOME':'/Users/test','DYLD_LIBRARY_PATH':'/opt/homebrew/lib',
                   'DYLD_INSERT_LIBRARIES':'bad.dylib','VK_DRIVER_FILES':'bad.json',
                   'VK_ADD_DRIVER_FILES':'extra.json','VK_LAYER_PATH':'/opt/homebrew',
                   'MVK_CONFIG_DEBUG':'1','MPVBUNDLE':'false'}
        env=player_environment(player,Path('/app/Contents/Frameworks'),inherited)
        self.assertEqual(env['MPVBUNDLE'],'true')
        self.assertEqual(env['HOME'],inherited['HOME'])
        self.assertEqual(env['DYLD_INSERT_LIBRARIES'],'/app/Contents/Frameworks/native-scroll.dylib')
        self.assertEqual(env['VK_DRIVER_FILES'],str(player.parent.parent/'Resources/vulkan/icd.d/MoltenVK_icd.json'))
        for name in ('DYLD_LIBRARY_PATH','VK_ADD_DRIVER_FILES','VK_LAYER_PATH','MVK_CONFIG_DEBUG'):
            self.assertNotIn(name,env)
        self.assertEqual(inherited['MPVBUNDLE'],'false')

    def test_diagnostics_remove_server_urls_addresses_and_credentials(self):
        output=redact('failed http://private-server:8096/videos?token=secret 10.1.2.3:8096 AccessToken="abc" password=xyz Authorization: Bearer spaced-secret')
        for secret in ('private-server','10.1.2.3','abc','xyz','Bearer','spaced-secret','token=secret'):
            self.assertNotIn(secret,output)
