The active mpv archive is a macOS 15 arm64 rebuild from upstream commit
`3aecc359bb815475dc50909ba06b40d8a1a26dad` with the fullscreen entry-mechanism
routing fix. It is a modified build, not an unmodified official distribution.

`work/native-dependencies.lock` selects its exact vendored bytes and SHA-256.
[fullscreen-owner-build/README.md](fullscreen-owner-build/README.md) records
its source patch, build provenance, dependency versions and comparison results.
The ZIP retains the existing `mpv.tar.gz` payload format and is acquired offline.
The previous official archive is retained for historical comparison.

It retains the CoreAudio initialization failure fix
`c5d391adba7bd024954d0df1e0405f5749f4d4ca`. See `THIRD_PARTY.md` for the native
dependency licensing/provenance limitations.
