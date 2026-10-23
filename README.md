# Jellyfin Player

[Jellyfin Player](https://github.com/iarnvidr/jellyfin-mpv-shim-macos) is an unofficial macOS app based on [Jellyfin MPV Shim](https://github.com/jellyfin/jellyfin-mpv-shim). It packages the client with a macOS launcher, native scroll integration, and the standard Jellyfin application icon. The app is named **Jellyfin Player**.

This is a preview for **Apple Silicon (arm64), macOS 15 or later**. Native macOS CI verifies the Jellyfin Player window, bundled Sparkle loading after moving the app, decoded video playback, and clean shutdown. First-open approval and a complete Sparkle install/relaunch still need validation on a user's Mac. The app is ad-hoc signed, not Developer ID signed or notarized. On first open, Gatekeeper may require per-app approval under **System Settings → Privacy & Security → Open Anyway**. Exact prompts vary by macOS version.

## Installation and updates

[Download Jellyfin Player 0.2.1](https://github.com/iarnvidr/jellyfin-mpv-shim-macos/releases/tag/v0.2.1), quit any older Jellyfin MPV Shim/Jellyfin Player instance, open the DMG, and drag **Jellyfin Player.app** to Applications. Python, mpv, and Sparkle are bundled; no Homebrew, Python installation, or additional runtime download is needed. Release assets include SHA-256 checksums, an explicit native signature inventory, and a Sparkle Ed25519 signature for the update ZIP. Version 0.2.0 has invalid nested signatures and should not be installed.

Jellyfin Player uses the Dock and Command-Tab rather than a separate tray icon. Closing its window quits the app; reopen it from Applications. Existing settings are retained. If another installed version holds the shared settings lock, a dialog identifies it and asks you to quit it. Startup failures offer **Copy Diagnostics** and **Open Logs**, even if the browser could not start.

Sparkle checks the repository's GitHub-hosted appcast and downloads complete app updates from GitHub Releases. The production appcast currently contains no releases while install/relaunch testing is pending; this preview must be installed manually.

Users upgrading from **0.1.0** must manually download and install the complete app; the old component updater cannot update the macOS wrapper. Keep existing settings, and do not delete legacy `~/Library/Application Support/Jellyfin MPV Shim/Updates/` or `Runtimes/` folders as part of the upgrade. The current launcher uses its bundled environment rather than those legacy selections. See [installation and recovery](docs/INSTALL-AND-RECOVERY.md).

## Build and checks (maintainers)

Build on Apple Silicon macOS 15 or later with Xcode command-line tools and the repository's pinned uv/Python toolchain. No Homebrew or other package manager is used or required at any stage. From the repository root:

```sh
uv sync --locked --group build
uv run --locked python scripts/prepare.py
uv run --locked python scripts/check.py
uv run --locked python work/build.py
uv run --locked python work/package.py
```

The build and packaging commands produce a local app/package; they do not establish interactive GUI qualification, notarization, or release readiness. Run the repository's checks with `uv run --locked python scripts/check.py`.

## Repository

- `work/`: macOS wrapper, native integration, and build/package scripts.
- `work/source`: upstream Jellyfin MPV Shim source (pinned submodule).
- `vendor/default-shader-pack`: default shader pack (pinned submodule).
- `VERSION`: wrapper version.

This is not an official Jellyfin product. Licensed GPL-3.0-or-later; see [LICENSE.md](LICENSE.md) and [third-party notices](THIRD_PARTY.md).
