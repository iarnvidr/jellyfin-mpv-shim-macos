"""Entry point run by the independently updateable Python interpreter."""
from pathlib import Path
import json
import os
import sys

# Support code lives inside the signed app bundle and must stay unchanged.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))

if sys.argv[1] == '--verify-runtime':
    runtime, resources = map(Path, sys.argv[2:4])
    sys.path.insert(0, str(runtime / 'packages'))
    import jellyfin_mpv_shim
    import local_compat
    import PIL.ImageFont
    import requests
    import python_mpv_jsonipc
    local_compat.verify(Path(jellyfin_mpv_shim.__file__).parent)
    print('Runtime verified')
else:
    runtime, resources, app = map(Path, sys.argv[1:4])
    sys.argv = [str(app)] + sys.argv[4:]
    sys.path.insert(0, str(runtime / 'packages'))
    sys._MEIPASS = str(resources)
    sys.frozen = True
    sys._JELLYFIN_MANAGED = True
    # Relaunches, multiprocessing and the updater return through the app.
    sys.executable = str(app)
    os.environ['JELLYFIN_MANAGED_RUNTIME'] = str(runtime)
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    from launch import launch
    launch()
