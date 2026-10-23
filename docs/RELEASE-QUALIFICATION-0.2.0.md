# 0.2.0 qualification ledger

**State: preparation; not a release. No gate is marked passed by this ledger.** Record actual build/artifact identity, operator, date, hardware/OS, procedure, result, and evidence location for every test before changing status. A CI job or source-level check is not a substitute for interactive packaged-app evidence.

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Pinned uv/Python clean-checkout build and upstream checks | Pending | Current project anticipates pinned uv 0.13.1 and Python 3.13. Build/dev/release/runtime use of Homebrew or any alternative system package manager is forbidden. Run locked sync, prepare, checks, and package from clean checkout using only pinned uv/Python, Xcode SDK tools, and verified immutable native assets or controlled source builds; prove lock unchanged. Prior failed Homebrew-cache runs are superseded historical evidence, not a pass. |
| Self-contained bundle; no developer tools on user Mac | Pending | Test final artifact on clean Apple Silicon Mac without Python, uv, Homebrew, or other package manager; connect, browse, playback. |
| OS/hardware support | Pending | Initial target Apple Silicon/macOS 15+. Verify collected binaries' minimum OS and interactive smoke tests on macOS 15 and a current macOS. No Intel claim. |
| 0.1.0 migration | Pending | One-time manual wrapper upgrade; verify settings/connections retained and active, pending, broken, stale legacy `Updates/`/`Runtimes/` selections cannot affect launch. |
| Runtime ownership, shutdown and recovery | Pending | Prototype handoff reports unresolved lifecycle/selection issue. Exercise quit/reopen, repeated launches, interruption and fallback; do not claim health rollback. |
| Sparkle whole-app update | Pending | On disposable apps/test feed, packaged helper discovers, verifies, replaces, shuts down and relaunches main app. Verify wrong key/modified archive rejection, cancellation, offline and unwritable install preserve installed app. |
| Playback/native UI | Pending | Exercise scrolling, window controls, fullscreen, seek, subtitles, audio, relocation, paths with spaces and normal shutdown. |
| Ad-hoc signing and first-open | Pending | Observe actual first-open Gatekeeper flow on supported macOS; document exact per-app approval. No notarization or Developer ID signing claim. |
| Contents, minimum OS, notices/source | Pending | Audit exact artifact and linked libraries, signatures, symlinks, permissions, notices, provenance and corresponding source. No artifact inventory audit currently claimed. |
| Release publication/feed/recovery | Pending | Build once, verify draft assets/checksums/signature/manifest/source, then publish and verify public assets and appcast. Production feed must not advance before verified assets. |

## Evidence log

### Automated Mac CI — run 39966871763, commit `fc64e673`

Run `39966871763` on commit `fc64e673` is reported green. This is automated CI evidence only: pinned checkout/build pipeline and its configured integration checks/package verification succeeded on its Apple Silicon macOS runner. It does **not** establish a GUI launch, connect/playback, first-open Gatekeeper behavior, user-machine installation, Sparkle key/signature flow, or interactive update qualification. No key was used. No production release/feed was published. Treat this run as the immutable build candidate; use its artifact outputs, not a rebuild.

Workflow artifact assembly now requests DMG, Sparkle update ZIP, source ZIP, build manifest, native audit, bundle inventory, and SHA256SUMS in one upload from the single package invocation. Availability of each file in the retained run artifact should be checked before further qualification. The exact verified mpv 0.41.0 release input was downloaded and SHA-256 matched `489cf6a54f57c54f86ad8d7cedaf5bb26848770d58dc059021214e2f689ee799`; archive inspection found only outer `mpv.tar.gz`, which contains `mpv.app`, executable, MoltenVK, Vulkan ICD config and 72 named bundled dylibs under `Contents/MacOS/lib`. The archive has no standalone license/notice or corresponding source files. Upstream mpv source repository is https://github.com/mpv-player/mpv, release v0.41.0, but the exact upstream build commit/configuration and corresponding-source archive availability have not been established by the release artifact. This is a concrete licensing/source blocker: obtain/verify exact build revision and source plus applicable licenses/notices for mpv and every bundled dylib before publication. Do not call the notices inventory complete.

Current locally checked-out source revision: upstream Jellyfin MPV Shim commit `7e9fd292459358dde12f054c24f79642ab5ec98f` (submodule pin); shader pack `9ab0195ece699680b422ec5bb2216d45e14c82b1`. CI build outputs and exact app native audit are in the run artifact and must be examined as part of candidate review. No GUI, no key, no release publication. Historical failed attempts remain superseded, not qualification evidence.

No interactive qualification evidence recorded yet. Automated CI green does not change the pending state of interactive and release gates. Append dated evidence here, preserve failures, and leave gates pending until their own criteria are met.
