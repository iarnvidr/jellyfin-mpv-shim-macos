"""Keep macOS volume controls and the bundled software mixer on one range."""
MAX_VOLUME = 200


def adjust_volume(self, delta):
    # Resolve the current volume on the player thread so rapid key repeats
    # accumulate rather than stepping repeatedly from a stale UI snapshot.
    def step(player):
        current = player.get_volume(True)
        if current is not None:
            player.set_volume(max(0.0, min(MAX_VOLUME, float(current) + delta)))
    self._act(step)


def patch_sliders(nodes):
    for node in nodes:
        if node.get('t') == 'slider' and node.get('id') in ('hud-vol', 'np-vol'):
            node['max'] = MAX_VOLUME
            node['tip'] = 'Volume: {:g}%'.format(node.get('value', 100))
