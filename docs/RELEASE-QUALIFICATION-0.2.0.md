# 0.2.0 qualification ledger

**State: preparation; not a release. No gate is marked passed by this ledger.** Record actual build/artifact identity, operator, date, hardware/OS, procedure, result, and evidence location for every test before changing status. A CI job or source-level check is not a substitute for interactive packaged-app evidence.

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Pinned uv/Python clean-checkout build and upstream checks | Pending | Current project anticipates pinned uv 0.13.1 and Python 3.13. Run locked sync, prepare, checks, package from clean checkout; prove lock unchanged. |
| Self-contained bundle; no developer tools on user Mac | Pending | Test final artifact on clean Apple Silicon Mac without Python/Homebrew/uv; connect, browse, playback. |
| OS/hardware support | Pending | Initial target Apple Silicon/macOS 15+. Verify collected binaries' minimum OS and interactive smoke tests on macOS 15 and a current macOS. No Intel claim. |
| 0.1.0 migration | Pending | One-time manual wrapper upgrade; verify settings/connections retained and active, pending, broken, stale legacy `Updates/`/`Runtimes/` selections cannot affect launch. |
| Runtime ownership, shutdown and recovery | Pending | Prototype handoff reports unresolved lifecycle/selection issue. Exercise quit/reopen, repeated launches, interruption and fallback; do not claim health rollback. |
| Sparkle whole-app update | Pending | On disposable apps/test feed, packaged helper discovers, verifies, replaces, shuts down and relaunches main app. Verify wrong key/modified archive rejection, cancellation, offline and unwritable install preserve installed app. |
| Playback/native UI | Pending | Exercise scrolling, window controls, fullscreen, seek, subtitles, audio, relocation, paths with spaces and normal shutdown. |
| Ad-hoc signing and first-open | Pending | Observe actual first-open Gatekeeper flow on supported macOS; document exact per-app approval. No notarization or Developer ID signing claim. |
| Contents, minimum OS, notices/source | Pending | Audit exact artifact and linked libraries, signatures, symlinks, permissions, notices, provenance and corresponding source. No artifact inventory audit currently claimed. |
| Release publication/feed/recovery | Pending | Build once, verify draft assets/checksums/signature/manifest/source, then publish and verify public assets and appcast. Production feed must not advance before verified assets. |

## Evidence log

No interactive qualification evidence recorded yet. Prior local prototype tests and known limitations are described only in the historical [repository handoff](REPOSITORY-HANDOFF.md); they do not qualify 0.2.0. Never infer completion from green CI. Append dated evidence here, preserve failed results, and leave gates pending until the required evidence exists.
