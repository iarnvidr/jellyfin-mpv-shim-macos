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

Fresh packaged application qualification:
- Canonical standard macOS 15 build: https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40386360255
- Tested application source: `8ae673faeb8c9ce58d037382a87376594af301ca`.
- Update ZIP: `Jellyfin-Player-0.2.9-Apple-Silicon.zip`, 84,630,642 bytes,
  SHA-256 `170777e350c38fe700b5cd1fd8880fea33f543cb6cf4867066257e39934aa5c3`.
- macOS 26, all five cases, and macOS 15, four cases:
  https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40388477811
- macOS 15 natural HTTP-profile case:
  https://github.com/iarnvidr/jellyfin-mpv-shim-macos/actions/runs/40389749357

The standard build passed the native-control LuaJIT guard, native dependency
and minimum-OS audits, signing checks, and extracted DMG/update ZIP playback
checks. The same update ZIP was then used for both-platform menu regressions,
including natural HTTP-profile changes, observed mode changes, and legitimate
native/legacy fullscreen. The first matrix's macOS 15 natural case targeted a
cached PID belonging to the previous case's bundle. A focused retry resolved
the live engine by exact bundle path; application code and archive were unchanged.
The ensuing qualification metadata commit changes documentation only.

The rebuilt LuaJIT parser rejects a leading empty semicolon in a standalone
Lua chunk. The application's native-controls integration retains its existing
immediately invoked function inside an outer `do` block, preserving function
scope and closures while separating it from the concatenated renderer. Both
the standalone guard and actual packaged renderer/playback were exercised.
