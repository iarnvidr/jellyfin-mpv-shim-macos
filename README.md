# Jellyfin Player

[Jellyfin Player](https://github.com/iarnvidr/jellyfin-mpv-shim-macos) is an unofficial macOS app based on [Jellyfin MPV Shim](https://github.com/jellyfin/jellyfin-mpv-shim). It packages the client with a macOS launcher, native scroll integration, and the standard Jellyfin application icon. The app is named **Jellyfin Player**.

This is a preview for **Apple Silicon (arm64), macOS 15.7.9 or later**. Native macOS CI verifies the Jellyfin Player window, bundled Sparkle loading after moving the app, decoded video playback, and clean shutdown. First-open approval and a complete Sparkle install/relaunch still need validation on a user's Mac. The app is ad-hoc signed, not Developer ID signed or notarized. On first open, Gatekeeper may require per-app approval under **System Settings → Privacy & Security → Open Anyway**. Exact prompts vary by macOS version.

## Installation and updates

[Download Jellyfin Player](https://github.com/iarnvidr/jellyfin-mpv-shim-macos/releases), quit any older Jellyfin MPV Shim/Jellyfin Player instance, open the latest preview's DMG, and drag **Jellyfin Player.app** to Applications. Python, mpv, and Sparkle are bundled; no Homebrew, Python installation, or additional runtime download is needed. Release assets include SHA-256 checksums, an explicit native signature inventory, and a Sparkle Ed25519 signature for the update ZIP. Version 0.2.0 has invalid nested signatures and should not be installed.

Jellyfin Player uses the Dock and Command-Tab. If another installed version holds the shared settings lock, a dialog identifies it and asks you to quit it. Startup failures offer **Copy Diagnostics** and **Open Logs**.

Use the native macOS menu bar for playback, audio tracks, subtitles, video options, and window controls. **Jellyfin Player → Settings…** (Command-comma) opens settings, and **Check for Updates…** opens Sparkle. The player's right-click and Control-click menus are removed.

macOS Now Playing and system media commands belong to the Jellyfin Player Dock app, with Jellyfin artwork and the current media title, position, duration and playback state.

Settings uses native macOS controls. Command-W and the red close button stop playback and close the player window while keeping the app in the Dock; click its Dock icon or choose Show Player to reopen it. Command-Q quits the app. Browser text fields support Command-Z/Shift-Command-Z, clipboard commands, Command-arrow line navigation, and Option-arrow word navigation. The custom browser exposes visible controls through macOS Accessibility, including protected password fields.

Double-click the playback title header, or choose Window → Zoom, to fill the available desktop; repeat to restore the previous size. Video keeps its proportions. Double-clicking the native title bar also respects macOS's Minimize or Do Nothing preference.

For quiet audio, including audio reduced during a FaceTime call, use **Audio → Volume → 200%**, the volume shortcuts, or the player sliders. All support 0–200%, with separate remembered volumes for music and video. **100% (Normal)** restores normal playback volume. Boost is manual and can distort loud recordings; it does not disable FaceTime's system audio reduction.

Sparkle checks the repository's GitHub-hosted appcast and downloads complete app updates from GitHub Releases. The feed includes version 0.2.3, which passed native CI checks for legacy installation and current-host automatic installation and relaunch. Feed publication requires both checks to pass for each new release.

The app keeps Sparkle running to check automatically while Jellyfin Player is open. Settings → Updates controls Sparkle's saved preferences, shows the installed version and last check, and provides Check for Updates. Automatic checking is enabled by default; automatic downloading and installation is optional.

## Build and checks (maintainers)

For Linux development, open this repository in its `.devcontainer` configuration. It installs the pinned Python/uv environment; run `/tmp/jellyfin-venv/bin/python -m unittest discover -s tests -q` and `/tmp/jellyfin-venv/bin/python scripts/check.py`. Native AppKit compilation and packaged app checks run on the macOS GitHub Actions runner.

Build on Apple Silicon macOS 15.7.9 or later with Xcode command-line tools and the repository's pinned uv/Python toolchain. No Homebrew or other package manager is used or required at any stage. From the repository root:

```sh
uv sync --locked --group build
uv run --locked python scripts/prepare.py
uv run --locked python scripts/check.py
uv run --locked python work/build.py
uv run --locked python work/package.py
```

The build and packaging commands produce a local app/package; they do not establish interactive GUI qualification, notarization, or release readiness. Run the repository's checks with `uv run --locked python scripts/check.py`.

To ship a preview, update `VERSION`, the project version in `pyproject.toml` and its matching `uv.lock` entry together, merge to `main`, and wait for its **macOS build** to succeed. Run **Prepare macOS release** on `main` with that build's run ID, the matching `vX.Y.Z` tag, and `publish=true`. It reuses the exact tested packages, signs the update ZIP, publishes a preview, then runs both installation checks before updating the feed. A failed qualification leaves the published preview available for manual download and leaves the feed unchanged; fix the qualification and run **Sparkle installation check** on `main` with `to_version=X.Y.Z` and `publish=true` to retry while `VERSION` still matches. Leave `publish=false` to prepare only a draft. Published tags and assets must not be replaced.

## Repository

- `work/`: macOS wrapper, native integration, and build/package scripts.
- `work/source`: upstream Jellyfin MPV Shim source (pinned submodule).
- `vendor/default-shader-pack`: default shader pack (pinned submodule).
- `VERSION`: wrapper version.

This is not an official Jellyfin product. Licensed GPL-3.0-or-later; see [LICENSE.md](LICENSE.md) and [third-party notices](THIRD_PARTY.md).
