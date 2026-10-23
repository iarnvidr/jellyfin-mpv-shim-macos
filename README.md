# Jellyfin MPV Shim for macOS

An unofficial Apple Silicon packaging and integration project for
[Jellyfin MPV Shim](https://github.com/jellyfin/jellyfin-mpv-shim).
It adds a Finder-launchable app, native trackpad scrolling, Mac window adjustments,
and a native component updater while keeping the upstream client separate.

**Status: development prototype.** The original local build was exercised on
Apple Silicon/macOS 27.0.1. Runtime activation/rollback has an unresolved lifecycle
issue; downloaded components can lose their active selection. Builds are ad-hoc
signed, without Developer ID signing or notarization. Intel and other macOS
versions have not been qualified. See [the original handoff](docs/REPOSITORY-HANDOFF.md)
for the architecture, prior verification, and limitations.

## Build on Apple Silicon

Install Xcode command line tools, Homebrew Python 3.13, and mpv:

```sh
xcode-select --install
brew install python@3.13 mpv
git clone --recurse-submodules https://github.com/iarnvidr/jellyfin-mpv-shim-macos.git
cd jellyfin-mpv-shim-macos
python3.13 scripts/prepare.py
python3.13 -m venv work/build-env
work/build-env/bin/python -m pip install -r requirements-build.txt
work/build-env/bin/python -m pip install --no-deps ./work/source
work/build-env/bin/python scripts/check.py
work/build-env/bin/python work/build.py
work/build-env/bin/python work/package.py
```

The app is in `work/dist/`; the DMG is in `outputs/`. Drag the app into
Applications. `work/install.py` is an optional developer convenience that stops
and replaces `/Applications/Jellyfin MPV Shim.app`, retains a backup, and opens it.
Run it only when you intend to replace your installed app.

The manual **macOS build** Actions workflow produces a development DMG artifact.
CI runs syntax and upstream integration checks on each push and pull request.
A successful build does not qualify the application for release.

## Source and versions

- `work/`: original Python wrapper, Swift updater, Objective-C scroll bridge,
  and build/package scripts. The prototype layout is retained deliberately.
- `work/source`: upstream submodule at `v3.1.0`, commit
  `7e9fd292459358dde12f054c24f79642ab5ec98f`.
- `vendor/default-shader-pack`: shader submodule at `v3.0.0`, commit
  `9ab0195ece699680b422ec5bb2216d45e14c82b1`.
- `scripts/prepare.py`: verifies pins and copies shader assets into upstream's
  ignored resource directory before installation.
- `VERSION`: Mac wrapper version. Upstream and downloaded component versions
  are separate; in-app updates do not replace wrapper or native integration code.

To update upstream, change the submodule commit and the matching pin in
`scripts/prepare.py`, rerun preparation, reinstall upstream, and run checks.
The wrapper rejects incompatible renderer/API changes. Keep upstream changes in
the submodule or contribute them upstream; keep Mac integration in this repo.

`requirements-build.txt` preserves the prototype's exact environment versions,
with the developer-specific local source URL removed. It is not hash-locked.
Homebrew mpv and its libraries are resolved at build time. Runtime updates also
resolve Python dependencies dynamically. Builds are not bit-for-bit reproducible.

## Next engineering work

1. Reproduce and fix runtime ownership, health reporting, shutdown, and rollback.
2. Test fresh installation, offline launch, app relocation, update interruption,
   multiple launches, scrolling, fullscreen, and playback on a real Mac.
3. Define a supported OS/runtime matrix and curate compatible component updates.
4. Complete bundled license/source inventory, signing, notarization, and wrapper
   release/update distribution before publishing end-user releases.

## License and provenance

GPL-3.0-or-later; see [LICENSE.md](LICENSE.md) and
[third-party notices](THIRD_PARTY.md). This is an independent packaging project,
not an official Jellyfin macOS release.
