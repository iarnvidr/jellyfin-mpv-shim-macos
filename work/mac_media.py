"""Playback metadata for the Dock host's system media integration."""
import math
import sys


def snapshot(player, active, epoch, commands):
    settings = getattr(sys.modules.get('jellyfin_mpv_shim.conf'), 'settings', None)
    enabled = getattr(settings, 'media_keys', True)
    if not active or not enabled:
        return dict(active=False)
    engine = player._player

    def read(name, default):
        try:
            value = getattr(engine, name)
            if isinstance(default, float):
                return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else default
            return value if isinstance(value, type(default)) else default
        except Exception:
            return default
    metadata = read('metadata', {})
    return dict(active=True, epoch=epoch, title=read('media_title', 'Jellyfin Player'),
                artist=str(metadata.get('artist') or ''), album=str(metadata.get('album') or ''),
                position=max(0, read('time_pos', 0.0)), duration=max(0, read('duration', 0.0)),
                paused=read('pause', False), rate=read('speed', 1.0), commands=commands)
