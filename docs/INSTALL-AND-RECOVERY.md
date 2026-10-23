# Installation and recovery

Jellyfin Player is an unofficial preview for Apple Silicon Macs running macOS 15 or later. It has not been qualified through interactive GUI testing. The app is ad-hoc signed and not notarized, so macOS may show a warning or block it at first launch. The exact Gatekeeper prompt and approval experience can vary; no universal first-open flow is guaranteed.

Obtain the app only from a trusted source and verify the artifact against the release's published integrity information when available. If macOS offers a per-app **Open Anyway** approval in Privacy & Security, you may use it after deciding to trust that artifact. Do not disable Gatekeeper system-wide or remove quarantine attributes as a general workaround. Sparkle signatures, when present, are not Apple notarization.

## Recovery

If the app does not open, use **Copy Diagnostics** or **Open Logs** in the startup error dialog.

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
