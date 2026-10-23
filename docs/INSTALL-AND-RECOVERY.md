# Installation and recovery

Jellyfin Player is an unofficial preview for Apple Silicon Macs running macOS 15 or later. It has not been qualified through interactive GUI testing. The app is ad-hoc signed and not notarized, so macOS may show a warning or block it at first launch. The exact Gatekeeper prompt and approval experience can vary; no universal first-open flow is guaranteed.

Obtain the app only from a trusted source and verify the artifact against the release's published integrity information when available. If macOS offers a per-app **Open Anyway** approval in Privacy & Security, you may use it after deciding to trust that artifact. Do not disable Gatekeeper system-wide or remove quarantine attributes as a general workaround. Sparkle signatures, when present, are not Apple notarization.

## Upgrade from 0.1.0

Upgrade manually by downloading and installing the complete Jellyfin Player app. The 0.1.0 component updater cannot update the macOS wrapper. Quit the old app before replacing it. Preserve your settings and do not delete these legacy folders as an upgrade shortcut:

- `~/Library/Application Support/Jellyfin MPV Shim/Updates/`
- `~/Library/Application Support/Jellyfin MPV Shim/Runtimes/`

The current launcher uses its bundled environment rather than legacy component/runtime selections. Keep a copy of the previous app if you may need to return to it.

Sparkle is integrated, but an end-to-end whole-app update has not been qualified. No production update feed is advertised as ready, and Sparkle is not claimed as a tested, complete replacement for the legacy updater.

## Recovery

If the app does not open or behaves unexpectedly, quit it and reinstall a previously retained, trusted compatible app manually. Preserve settings and the legacy folders while diagnosing. Do not assume that withdrawing an update feed can restore an already-installed app, or that reverting the app reverses any data migration.

## Maintainer checks

On Apple Silicon macOS 15 or later with Xcode command-line tools and pinned uv/Python, no Homebrew or other package manager is used or required. From the repository root, the locked checks and local packaging commands are:

```sh
uv sync --locked --group build
uv run --locked python scripts/prepare.py
uv run --locked python scripts/check.py
uv run --locked python work/build.py
uv run --locked python work/package.py
```

These commands do not qualify GUI behavior, notarization, or production update delivery. Sparkle integration alone is not evidence that an update feed or end-to-end update is ready.
