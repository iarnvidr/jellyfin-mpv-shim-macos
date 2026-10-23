"""Mac integration kept outside the updateable upstream application."""
from pathlib import Path
import hashlib


def patch_renderer(text):
    replacements = [
        ('if scale <= 0 then scale = 1 end', 'if scale <= 0 then return end'),
        ('if wprev then\n        local slot',
         'if wprev and (state.force_snap or state.snapped) then\n        local slot'),
        ('if node.snap and node.snap > 0 then\n        local n',
         'if state.force_snap and node.snap and node.snap > 0 then\n        local n'),
    ]
    for old, new in replacements:
        if old not in text:
            raise ValueError('The scrolling integration needs an update for this release.')
        text = text.replace(old, new, 1)
    sync = 'function state.wheel_sync()'
    if sync not in text or 'local function on_dbl()' not in text:
        raise ValueError('This release needs a newer native scrolling integration.')
    text = text.replace('    state.wheel_on = want\n',
                        "    state.wheel_on = want\n    mp.set_property_native('user-data/mpvtk-native-scroll', want)\n", 1)
    native = '''
mp.register_script_message('mpvtk-native-scroll', function(json)
    if not state.wheel_on then return end
    local event = utils.parse_json(json)
    if not event then return end
    on_mouse_move(event.x or 0, event.y or 0)
    -- AppKit has already applied the user's natural-scroll preference,
    -- trackpad response and momentum. Keep its pixel displacement exactly.
    if event.dy and event.dy ~= 0 then
        on_wheel(event.dy > 0 and 1 or -1, 'y', {scale=math.abs(event.dy) / WHEEL_STEP})
    end
    if event.dx and event.dx ~= 0 then
        on_wheel(event.dx > 0 and 1 or -1, 'x', {scale=math.abs(event.dx) / WHEEL_STEP})
    end
end)

'''
    text = text.replace('local function on_dbl()', native + 'local function on_dbl()', 1)
    return text


def verify(package):
    from jellyfin_mpv_shim.mpvtk_browser.app import MpvtkBrowser
    from jellyfin_mpv_shim.player_window import WindowMixin
    from jellyfin_mpv_shim.mpvtk_browser.settings.general import GeneralTabMixin
    from jellyfin_mpv_shim.update_check import UpdateChecker
    for cls, method in [(MpvtkBrowser, 'build'), (MpvtkBrowser, 'refresh_window_controls'),
                        (WindowMixin, 'window_chrome_state'),
                        (GeneralTabMixin, '_settings_form'), (UpdateChecker, '_check_updates')]:
        if not callable(getattr(cls, method, None)):
            raise ValueError('This release needs a newer Mac integration.')
    patch_renderer((package / 'mpvtk/renderer.lua').read_text())


def apply(resources, package):
    import mac_update
    import os
    import subprocess
    from jellyfin_mpv_shim import mpv_options
    # Change the visible player title without changing upstream profile paths
    # or its client identity on existing Jellyfin servers.
    mpv_options.USER_APP_NAME = 'Jellyfin Player'
    original_popen = subprocess.Popen.__init__
    def popen(self, args, *positional, **keywords):
        if isinstance(args, (list, tuple)) and args and Path(str(args[0])).name == 'mpv':
            from player_runtime import player_environment
            import startup
            keywords['env'] = player_environment(args[0], resources, keywords.get('env') or os.environ)
            # The upstream default discards terminal output. Keep a bounded,
            # redacted tail, drained continuously, for startup failure reports.
            args = [*args, '--terminal=yes', '--title=Jellyfin Player']
            keywords.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            original_popen(self, args, *positional, **keywords)
            startup.record_engine(self)
            return
        original_popen(self, args, *positional, **keywords)
    subprocess.Popen.__init__ = popen
    import python_mpv_jsonipc
    original_process_init = python_mpv_jsonipc.MPVProcess.__init__
    def process_init(self, *args, **kwargs):
        try:
            original_process_init(self, *args, **kwargs)
        except python_mpv_jsonipc.MPVProcessError as error:
            import startup
            startup.ENGINE_FAILURE = str(error)
            raise
    python_mpv_jsonipc.MPVProcess.__init__ = process_init
    original_mpv_init = python_mpv_jsonipc.MPV.__init__
    def mpv_init(self, *args, **kwargs):
        # One process per construction. Upstream may retry once without OSC;
        # repeating the same killed executable five times obscures the cause.
        kwargs.update(start_retries=1, start_retry_delay_ms=0, diagnose_start_failures=False)
        original_mpv_init(self, *args, **kwargs)
    python_mpv_jsonipc.MPV.__init__ = mpv_init
    from jellyfin_mpv_shim import tray
    def start_tray(self):
        import logging
        self.available = False
        self.ready.set()
        logging.getLogger('tray').info('macOS uses the Jellyfin Player Dock icon; closing the window quits the app. Reopen it from Applications.')
    tray.TrayManager.start = start_tray
    from jellyfin_mpv_shim import utils
    def get_resource(*parts):
        preferred = package.joinpath(*parts)
        return str(preferred if preferred.exists() else resources.joinpath('jellyfin_mpv_shim', *parts))
    utils.get_resource = get_resource
    verify(package)

    from jellyfin_mpv_shim.mpvtk import app as renderer_app
    text = patch_renderer((package / 'mpvtk/renderer.lua').read_text())
    cache = Path.home() / 'Library/Caches/Jellyfin MPV Shim/Mac'
    cache.mkdir(parents=True, exist_ok=True)
    renderer = cache / ('renderer-' + hashlib.sha256(text.encode()).hexdigest()[:16] + '.lua')
    if not renderer.exists():
        renderer.write_text(text)
    renderer_app._RENDERER = str(renderer)
    original_render = renderer_app.MpvtkApp._render
    def render(self):
        before = self.build_errors
        result = original_render(self)
        return result
    renderer_app.MpvtkApp._render = render

    from jellyfin_mpv_shim.player_window import WindowMixin
    original_chrome = WindowMixin.window_chrome_state
    original_raise = WindowMixin.raise_window
    def raise_window(self):
        import time
        import uuid
        import startup
        original_raise(self)
        # AppKit hide (Command-H) is distinct from window minimization.
        request=uuid.uuid4().hex
        self._player.command('set_property','user-data/jellyfin-window-action',
                             {'action':'show','request':request})
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            try:
                ack=self._player.command('get_property','user-data/jellyfin-window-ack')
                if isinstance(ack,dict) and ack.get('request')==request and ack.get('visible') is True:
                    startup.WINDOW_ACTIVATION=request
                    return
            except python_mpv_jsonipc.MPVError:
                pass
            time.sleep(.05)
        raise RuntimeError('The native player window did not acknowledge activation')
    WindowMixin.raise_window = raise_window
    def chrome(self):
        state = original_chrome(self)
        state['title_bar_inset'] = 0
        try:
            if self._player.border and not self._player.fullscreen:
                state['title_bar_inset'] = 32 * (self._player.display_hidpi_scale or 1)
        except Exception:
            pass
        return state
    WindowMixin.window_chrome_state = chrome

    from jellyfin_mpv_shim.mpvtk_browser.app import MpvtkBrowser
    from jellyfin_mpv_shim.mpvtk import Box, Column, Row, Text, Button, scaling
    original_refresh = MpvtkBrowser.refresh_window_controls
    def refresh(self):
        original_refresh(self)
        try:
            inset = (self.controller.window_chrome_state() or {}).get('title_bar_inset', 0)
            if inset != getattr(self, '_mac_inset', 0):
                self._mac_inset = inset
                self.invalidate()
        except Exception:
            pass
    MpvtkBrowser.refresh_window_controls = refresh
    original_build = MpvtkBrowser.build
    def build(self, size):
        inset = scaling.dip(getattr(self, '_mac_inset', 0))
        w, h = size
        content = original_build(self, (w, max(1, h - inset)))
        return Column([Box(h=inset), content], w=w, h=h, align='stretch') if inset else content
    MpvtkBrowser.build = build

    from jellyfin_mpv_shim.mpvtk_browser.settings.general import GeneralTabMixin
    original_form = GeneralTabMixin._settings_form
    def form(self, route, size):
        content = original_form(self, route, size)
        if route.get('_tab', 'general') == 'general':
            bar = Row([Text('Jellyfin Player ' + mac_update.current_version()),
                       Button('Check for Updates…', id='mac-check-updates',
                              on_click=mac_update.show_updater)], gap=16, pad=12, h=64)
            return Column([bar, content], flex=1, align='stretch')
        return content
    GeneralTabMixin._settings_form = form

    from jellyfin_mpv_shim.mpvtk_browser import window_chrome
    original_banner = window_chrome.banner
    def banner(browser):
        tree = original_banner(browser)
        if tree is not None:
            for index, child in enumerate(getattr(tree, 'children', [])):
                if getattr(child, 'id', None) == 'banner-open':
                    tree.children[index] = Button('Install Update…', id='banner-open',
                                                  on_click=mac_update.show_updater)
        return tree
    window_chrome.banner = banner
    from jellyfin_mpv_shim.update_check import UpdateChecker
    def check_updates(self):
        return False
    UpdateChecker._check_updates = check_updates
    UpdateChecker.open = lambda self: mac_update.show_updater()
