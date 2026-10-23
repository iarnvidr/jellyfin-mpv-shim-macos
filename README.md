# Jellyfin Player

[Jellyfin Player](https://github.com/iarnvidr/jellyfin-mpv-shim-macos) is an unofficial macOS app based on [Jellyfin MPV Shim](https://github.com/jellyfin/jellyfin-mpv-shim). It packages the client with a macOS launcher, native scroll integration, and the standard Jellyfin application icon. The app is named **Jellyfin Player**.

This is a preview for **Apple Silicon (arm64), macOS 15 or later**. It has not been qualified through interactive GUI testing; do not treat it as a production-ready or fully tested release. The app is ad-hoc signed, not Developer ID signed or notarized. On first open, Gatekeeper may block it or require per-app approval. If macOS offers an **Open Anyway** approval for this app, use that route only if you trust the artifact and its source. Do not disable Gatekeeper globally or remove quarantine as a general workaround. Exact prompts can vary by macOS version; the app has not been validated against every first-open flow.

## Installation and updates

For an available preview, use its accompanying release instructions and verify the downloaded artifact before opening it. No production update feed is advertised as ready. Sparkle is integrated in the app, but whole-app update behavior has not been tested end to end and is not claimed as a qualified replacement for the legacy updater.

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
