# Third-party sources

The Mac wrapper was imported from the owner's
`Jellyfin-MPV-Shim-Mac-Packaging-Source.zip` and accompanying repository handoff.
Its upstream snapshot (775 files) and shader snapshot (65 files) were compared
by SHA-256 against the pinned Git checkouts; there were no differences.
The imported wrapper is maintained here under GPL-3.0-or-later.

- Jellyfin MPV Shim: https://github.com/jellyfin/jellyfin-mpv-shim,
  GPL-3.0-or-later; license and icon retained in the upstream submodule.
- Default shader pack: https://github.com/iwalton3/default-shader-pack.
  Retain its included notices and individual shader licenses.
- Python build dependencies: exact versions in `requirements-build.txt`;
  each dependency retains its own license.
- Build bundles include Python, mpv, and libraries collected by PyInstaller.
  Homebrew package metadata and the actual collected binaries must be audited
  for complete notices and corresponding-source obligations before distribution.
- Downloaded runtimes use python-build-standalone, mpv, and PyPI dependencies.
  They are separate from the wrapper and retain their own licensing obligations.

The prototype copies the upstream license into the app. That is not yet a
complete inventory of licenses or corresponding sources for a distributed DMG.
