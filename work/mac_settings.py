"""Schema-backed preferences for the AppKit Settings window."""
import json
import math
import os
import signal
import threading
from pathlib import Path

_relocation_lock = threading.Lock()
_relocation = None


def open_settings():
    pid = int(os.environ.get('JELLYFIN_PLAYER_HOST_PID', '0'))
    if pid > 1:
        os.kill(pid, signal.SIGURG)


def snapshot(browser):
    cfg = browser._config()
    values, schema = cfg.get_settings(), cfg.settings_schema()
    tabs = []
    for tab in cfg.FORM_TABS:
        groups = []
        for title, keys in cfg.sections(tab):
            fields = []
            for key in keys:
                if key not in schema:
                    continue
                options = cfg.LABELED_ENUMS.get(key)
                if not options and callable(getattr(browser, '_dynamic_enum', None)):
                    dynamic = browser._dynamic_enum(key)
                    if isinstance(dynamic, (list, tuple)):
                        options = dynamic
                if options is None and key in cfg.ENUMS:
                    options = [(str(value), value) for value in cfg.ENUMS[key]]
                if options and values.get(key) not in [option[1] for option in options]:
                    options = [*options, (str(values.get(key)), values.get(key))]
                fields.append(dict(key=key, title=cfg.label_for(key), kind='directory' if key == 'sync_path' else schema[key],
                                   value=values.get(key), nullable=cfg.is_nullable(key),
                                   options=options or [], restart=key in cfg.RESTART_REQUIRED,
                                   note=cfg.NOTES.get(key, ''),
                                   enabled=not (key == 'fullscreen' and values.get('browser_fullscreen'))))
            if fields:
                groups.append(dict(title=title, fields=fields))
        tabs.append(dict(id=tab, title=tab.title(), groups=groups))
    return dict(ok=True, tabs=tabs)


def request(command, browser, player):
    global _relocation
    if command == 'settings-relocation-state':
        with _relocation_lock:
            return dict(_relocation or {'ok': False, 'error': 'No download move is running.'})
    if command == 'settings-state':
        return snapshot(browser)
    try:
        payload = json.loads(command.removeprefix('settings-set:'))
        key, value = payload['key'], payload['value']
        cfg = browser._config()
        allowed = {field['key']: field for tab in snapshot(browser)['tabs']
                   for group in tab['groups'] for field in group['fields']}
        field = allowed[key]
        if not field['enabled']:
            raise ValueError('Turn off browser fullscreen before changing playback fullscreen.')
        if key == 'sync_path':
            if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
                raise ValueError('Choose an absolute folder path.')
            with _relocation_lock:
                if _relocation and _relocation.get('busy'):
                    return dict(ok=False, error='A download move is already running.')
                _relocation = dict(ok=True, busy=True)
            def move():
                global _relocation
                try:
                    ok, message = cfg.relocate_downloads(value)
                    result = dict(ok=ok, busy=False, message=message)
                except Exception as error:
                    result = dict(ok=False, busy=False, error=str(error))
                with _relocation_lock:
                    _relocation = result
            threading.Thread(target=move, name='native-download-relocation', daemon=True).start()
            return dict(ok=True, busy=True)
        if value is None:
            if not field['nullable']:
                raise ValueError('This setting cannot be empty.')
        else:
            if field['kind'] == 'bool' and not isinstance(value, bool):
                raise ValueError('Choose an enabled or disabled value.')
            value = cfg.coerce(field['kind'], value)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('Enter a finite number.')
        if field['options'] and value not in [option[1] for option in field['options']]:
            raise ValueError('Choose a value from the list.')
    except (ValueError, TypeError, KeyError) as error:
        return dict(ok=False, error=str(error))
    completed, result = threading.Event(), {}

    def save():
        try:
            browser._set_setting(key, value)
            result.update(ok=cfg.get_settings().get(key) == value,
                          restart=field['restart'])
        except Exception as error:
            result.update(ok=False, error=str(error))
        finally:
            completed.set()
    player.put_task(save)
    if not completed.wait(2):
        return dict(ok=False, error='The player is busy. Check the saved value before retrying.')
    return result
