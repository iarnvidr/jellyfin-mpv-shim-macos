This directory records a locally rebuilt mpv candidate. It is not an unmodified
official mpv distribution. The active archive remains selected separately by
`work/native-dependencies.lock`.

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
