This directory records the locally rebuilt mpv selected by
`work/native-dependencies.lock`. It is not an unmodified official distribution.

Both original and patched sources were built in the same macOS 15 CI job from
mpv commit `3aecc359bb815475dc50909ba06b40d8a1a26dad`. The only source change is
`source.patch`: remember the native/legacy fullscreen mechanism selected on
entry, and use that mechanism for exit even if the preference changes during
playback. It adds no presentation-option writes.

Build workflow and exact commands:
https://github.com/iarnvidr/jellyfin-mpv-shim-macos/tree/8251874

Build run, complete build logs, original comparator bundle and patched bundle:
https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40383810921

`manifest.json` records source, patch, artifact, tar and vendor ZIP checksums.
The version, compiler, SDK, Homebrew inventory, Meson options and dependency
records are retained alongside it. Both variants passed 42 upstream tests and
strict bundle signature verification. Playback/menu regression qualification
is separate from these compilation checks.

The vendor ZIP contains the unchanged patched tarball, named `mpv.tar.gz`,
using ZIP_STORED with a fixed member timestamp. This preserves the existing
offline acquisition format. No source build or package-manager invocation is
added to the shipping build or application runtime.

This rebuild uses the dependency versions recorded here, including FFmpeg
9.0.1 and libplacebo 7.360.1. It is not byte-equivalent to the previously pinned
official development archive. Existing native licensing/provenance limitations
in `THIRD_PARTY.md` still apply.

Controlled playback comparison:
- Rebuilt original: https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40384667380
- Rebuilt patched: https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40384672078

With decoded, advancing playback, changing `native-fs` after legacy fullscreen
entry left the original engine windowed while application/system presentation
options remained 5 and the menu bar was hidden. The patched engine exited using
the original mechanism, with presentation options 0 and the menu bar visible.
A normal GUI/HTTP-profile route also changed the effective mechanism without an
IPC mode change; the patched engine exited correctly on the first request.
The rebuilt original's menu visibility after its second exit varied from the
published original, so the controlled synthetic comparison establishes the
presentation-state fix more directly. These results do not establish the
original reporter's configuration or every cause of a hidden menu bar.

A fresh packaged-app comparison is required separately from the engine builds.
