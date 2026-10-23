"""Keep mpv's app identity and native driver discovery inside this bundle."""
from pathlib import Path


def player_environment(player, resources, inherited):
    # These are loader overrides, not playback preferences. Inheriting them can
    # inject a second MoltenVK or code from an unrelated Homebrew installation.
    env = {key: value for key, value in inherited.items()
           if not key.startswith(('DYLD_', 'VK_', 'MVK_'))}
    contents = Path(player).parent.parent
    icd = contents / 'Resources/vulkan/icd.d/MoltenVK_icd.json'
    env.update(MPVBUNDLE='true',
               VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
               VK_LOADER_SEARCH_ONLY_IN_BUNDLE='1',
               DYLD_INSERT_LIBRARIES=str(Path(resources) / 'native-scroll.dylib'))
    return env
