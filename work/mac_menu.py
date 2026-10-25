"""Native menu model and allowlisted actions, using the existing player handlers."""
import sys


class NativeMenus:
    def __init__(self, ui, player, updater):
        self.ui, self.player, self.updater = ui, player, updater
        self.actions = {}

    def model(self):
        # Playback startup can hold this lock during server I/O. Native menu
        # polling must not pile up blocked listener threads behind that work.
        self.actions = {}
        if not self.player._lock.acquire(blocking=False):
            return {'ready': False, 'application': [], 'menus': []}
        try:
            return self._model()
        finally:
            self.player._lock.release()

    def _model(self):
        pm, ui = self.player, self.ui
        self.actions = {}
        ready = ui._browser is not None
        state = pm.osc_bridge.build_state() if ready else {}
        media = bool(state.get('has_media'))
        engine = pm._player if ready else None
        try:
            editing = engine.command('get_property', 'user-data/jellyfin-native-edit') or {}
        except Exception:
            editing = {}
        if not isinstance(editing, dict):
            editing = {}
        epoch = str(pm._play_epoch)

        def item(title, command, action, *, enabled=True, key='', modifiers=None,
                 checked=False, playback=False):
            command = (epoch + ':' + command) if playback else command
            if enabled:
                if playback:
                    def current_session(action=action):
                        if str(pm._play_epoch) == epoch:
                            action()
                    self.actions[command] = current_session
                else:
                    self.actions[command] = action
            return dict(title=title, command=command, enabled=bool(enabled), key=key,
                        modifiers=modifiers or ['command'], checked=bool(checked))

        def choice(title, options, verb):
            return dict(title=title, items=[
                item(str(option['label']), verb + ':' + str(option['id']),
                     lambda v=str(option['id']): pm.osc_bridge.handle_action([verb, v]),
                     enabled=media, checked=option.get('selected', False), playback=True)
                for option in options])

        def edit(title, key, operation, allowed='focused', modifiers=None):
            return item(title, 'edit-' + key,
                        lambda: engine.command('script-message', 'jellyfin-native-edit', operation),
                        enabled=ready and editing.get(allowed, False), key=key, modifiers=modifiers)

        def close_window():
            pm.stop_for_window_close()
            engine.command('set_property', 'user-data/jellyfin-window-action', {'action': 'close'})

        def property_toggle(name):
            setattr(engine, name, not getattr(engine, name))

        menus = [
            dict(title='File', items=[
                item('Show Library', 'library', ui.activate, enabled=ready, key='l'),
                item('Manage Servers…', 'servers', lambda: ui._open_settings('servers'), enabled=ready),
                item('Close Window', 'close', close_window, enabled=ready, key='w')]),
            dict(title='Edit', items=[edit('Undo', 'z', 'UNDO', 'undo'),
                                      edit('Redo', 'Z', 'REDO', 'redo', ['command', 'shift']), {},
                                      edit('Cut', 'x', 'CUT', 'selection'), edit('Copy', 'c', 'CTRLC', 'selection'),
                                      edit('Paste', 'v', 'PASTE'), edit('Select All', 'a', 'CTRLA')]),
            dict(title='Playback', items=[
                item('Play' if not media or pm.is_paused() else 'Pause', 'pause', pm.toggle_pause,
                     enabled=media, key='p', playback=True),
                item('Stop', 'stop', pm.stop_to_browser, enabled=media, key='.', playback=True),
                {},
                item('Previous Item', 'previous', pm.play_prev,
                     enabled=media and state.get('queue', {}).get('has_prev', False), playback=True),
                item('Next Item', 'next', pm.play_next,
                     enabled=media and state.get('queue', {}).get('has_next', False), playback=True),
                {},
                item('Skip Back 10 Seconds', 'seek-back', lambda: pm.seek(-10),
                     enabled=media and not editing.get('focused'), key='\uf702', playback=True),
                item('Skip Forward 10 Seconds', 'seek-forward', lambda: pm.seek(10),
                     enabled=media and not editing.get('focused'), key='\uf703', playback=True),
                item('Previous Chapter', 'chapter-back', lambda: pm.chapter_seek(-1), enabled=media, playback=True),
                item('Next Chapter', 'chapter-next', lambda: pm.chapter_seek(1), enabled=media, playback=True)]),
            dict(title='Audio', items=[
                item('Increase Volume', 'volume-up', lambda: pm.set_volume(min(100, pm.get_volume(True) + 5)),
                     enabled=media, key='\uf700', playback=True),
                item('Decrease Volume', 'volume-down', lambda: pm.set_volume(max(0, pm.get_volume(True) - 5)),
                     enabled=media, key='\uf701', playback=True),
                item('Mute', 'mute', lambda: pm.set_mute(not engine.mute), enabled=media,
                     checked=engine.mute if engine else False, playback=True),
                {}, choice('Audio Track', state.get('audio', []), 'set-audio')]),
            dict(title='Subtitles', items=[
                choice('Subtitle Track', state.get('subtitles', []), 'set-sub'),
                choice('Secondary Subtitle', state.get('secondary_subtitles', []), 'set-secondary-sub'),
                *[choice(label, state.get('sub_style', {}).get(name, {}).get('options', []), verb)
                  for label, name, verb in [('Size', 'size', 'set-sub-size'),
                                            ('Position', 'position', 'set-sub-position'),
                                            ('Color', 'color', 'set-sub-color')]]]),
            dict(title='Video', items=[
                item('Exit Full Screen' if engine and engine.fullscreen else 'Enter Full Screen',
                     'fullscreen', lambda: pm.set_fullscreen(not engine.fullscreen, True),
                     enabled=ready, key='f', modifiers=['control', 'command']),
                item('Always on Top', 'ontop', lambda: property_toggle('ontop'),
                     enabled=ready, checked=engine.ontop if engine else False),
                choice('Video Quality', state.get('quality', {}).get('options', []), 'set-quality'),
                choice('Playback Profile', state.get('profiles', {}).get('options', []), 'set-profile'),
                item('Playback Information', 'stats', pm.toggle_stats, enabled=media, key='i', playback=True)]),
            dict(title='Window', items=[
                item('Minimize', 'minimize', lambda: setattr(engine, 'window_minimized', True), enabled=ready, key='m'),
                item('Zoom', 'zoom', lambda: engine.command('set_property', 'user-data/jellyfin-window-action', {'action': 'zoom'}), enabled=ready),
                item('Bring All to Front', 'front', ui.on_second_launch, enabled=ready),
                item('Show Player', 'show', ui.on_second_launch, enabled=ready)]),
            dict(title='Help', items=[
                item('View Logs', 'logs', lambda: ui._open_settings('logs'), enabled=ready)])]
        application = [
            item('Settings…', 'settings', lambda: ui._open_settings('general'), enabled=ready, key=','),
            item('Check for Updates…', 'updates', self.updater, enabled=ready)]
        return dict(ready=ready, application=application, menus=menus)

    def request(self, command):
        if command in ('settings-state', 'settings-relocation-state') or command.startswith('settings-set:'):
            from mac_settings import request
            return request(command, self.ui._browser, self.player)
        model = self.model()
        if command == 'state':
            return model
        action = self.actions.get(command)
        if action is None:
            return {'ok': False}
        self.player.put_task(action)
        return {'ok': True}


def request(command):
    # A native host can ask before upstream has finished importing/starting.
    # Never cause a second, partially initialized player during startup.
    module = sys.modules.get('jellyfin_mpv_shim.mpvtk_browser.ui')
    player_module = sys.modules.get('jellyfin_mpv_shim.player')
    ui = getattr(module, 'user_interface', None)
    player = getattr(player_module, 'playerManager', None)
    if ui is None or player is None or ui._browser is None:
        return {'ready': False, 'application': [], 'menus': []}
    from mac_update import show_updater
    return NativeMenus(ui, player, show_updater).request(command)
