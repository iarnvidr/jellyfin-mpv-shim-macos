# Jellyfin MPV Shim for macOS — repository handoff

Prepared 23 October 2026. Implementation and interactive testing took place on 17–18 October; current on-disk state was inspected again for this handoff. This document describes what exists, what was tested, and what remains to make it a maintainable release project.

## Purpose and scope

The goal was to turn upstream Jellyfin MPV Shim into a normal Mac application: drag it into Applications, launch it through Finder, use its graphical interface, and update the application, Python, and mpv without terminal commands or local compilation. We also fixed navigation being obscured by the title bar, replaced unnatural trackpad scrolling with native Mac scrolling, and gave the player Jellyfin's name and icon in the Dock/app switcher.

This is an unofficial local macOS packaging/integration project around upstream, not a new media client. Upstream still supplies the Jellyfin connection, browsing UI, playback coordination, and most settings.

The current workspace is:

`/Users/et/Documents/Codex/2026-10-17/https-github-com-jellyfin-jellyfin-mpv-2`

The implementation lives in `work/`. Deliverables live in `outputs/`. The installed application is `/Applications/Jellyfin MPV Shim.app`.

## Read this first: current status and limitations

There is a working local packaging prototype, a DMG, and a source archive. Installation, launching, updater checks, downloading prebuilt runtimes, and native scrolling were exercised locally. The user explicitly confirmed that the final native trackpad implementation felt right.

However, do not describe this as a release-ready, fully reliable updater yet. At handoff inspection, `Runtimes/state.json` contained `active: null`, `previous: null`, `pending: false`, and an old `owner_pid`. Both downloaded runtime directories remain on disk. At the end of the earlier implementation session, the selected runtime was healthy and update checking reported Jellyfin 3.2.0, Python 3.15.0, and mpv 0.41.0. The later transition to an unselected runtime has not been diagnosed. No runtime was reactivated or application restarted while preparing this document.

The code can clear the active selection when a pending launch has died and no recorded owner is alive. That is a possible explanation, not a proven account of the later state. Treat lifecycle/rollback correctness as the first engineering priority. The built-in bundle remains the fallback; the existence of downloaded files does not mean they are currently selected.

Other important boundaries:

- The local package is ad-hoc signed, not Developer ID signed or notarized.
- Testing was on Apple Silicon/macOS 27.0.1. Intel and other macOS releases have not been validated.
- The graphical browser is still upstream's mpv/Lua interface. The whole UI was not rewritten in AppKit or SwiftUI.
- Runtime updates replace upstream Python packages, standalone Python, and the downloaded mpv bundle. They do **not** update our launcher, Swift updater, Objective-C scrolling bridge, or compatibility code. Those still need a new wrapper release/build.
- There is no CI release pipeline, wrapper update feed, systematic integration test suite, or supported OS matrix yet.

## Source baseline

Upstream repository: https://github.com/jellyfin/jellyfin-mpv-shim

The build baseline is tag `v3.1.0`, commit `7e9fd292459358dde12f054c24f79642ab5ec98f`, checked out in `work/source`. The default shader pack was populated at `work/source/jellyfin_mpv_shim/default_shader_pack` from its `v3.0.0` tag.

At handoff, upstream's Git status showed only the shader-pack directory as untracked. The final Mac adaptations live in wrapper files outside the upstream checkout. Earlier direct experiments with upstream window/browser code were superseded by this compatibility layer; do not assume those experimental edits remain in the final source.

The downloadable runtime tested later used upstream Jellyfin MPV Shim **3.2.0**. That is separate from the bundle/DMG baseline version, which still says **3.1.0**. The wrapper build number is `3.1.0.6`. A proper repository should give the wrapper its own coherent version and display bundled/current upstream/runtime versions separately.

## Architecture

Launch flow:

```text
Finder / Applications
  -> PyInstaller windowed launcher
     -> bundled Python + bundled upstream + bundled mpv fallback
     OR
     -> exec standalone Python from the selected runtime
        -> managed_launch.py
        -> downloaded upstream packages
        -> local_compat.py
        -> downloaded mpv.app
           -> NativeScroll bridge + patched Lua renderer
```

The installed `.app` is a self-contained PyInstaller `--windowed --onedir` bundle. It includes Python, upstream assets/packages, mpv and linked libraries, the scrolling dylib, and a nested native updater app. Homebrew is used on the build machine, not required on the user's machine.

The wrapper's main bundle identifier is `org.jellyfin.mpvshim.local`. The updater uses `org.jellyfin.mpvshim.local.updater`. The branded downloaded player uses `org.jellyfin.mpvshim.player`.

## File map

All paths in this table are relative to `work/`.

| File | Responsibility |
| --- | --- |
| `launch.py` | Finder entry point, update-worker dispatch, runtime selection, logging, resource paths, graphical mode, external mpv selection. |
| `managed_launch.py` | Starts upstream under standalone Python while providing the resource/executable conventions expected by the wrapper and upstream. Also supports isolated compatibility verification. |
| `local_compat.py` | Applies Mac integration to the imported upstream code: title-bar inset, renderer patches, native scrolling bridge injection, settings/update controls, and render-based health reporting. |
| `NativeScroll.m` | Cocoa local scroll-event monitor and Unix-socket bridge into mpv/Lua. Compiled as `native-scroll.dylib`. |
| `runtime_update.py` | Discovers/downloads/verifies prebuilt Python and mpv, installs binary Python packages, brands mpv, stages versioned runtimes, and maintains activation/rollback state. |
| `mac_update.py` | Updater entry points, JSON worker protocol, helper launch, version reporting, and older package-overlay implementation retained for fallback/legacy behavior. Public install now delegates to the full runtime updater. |
| `Updater.swift` | Native AppKit update dialogs, progress, error reporting, and restart handling. Compiled into nested `Mac Updater.app`. |
| `build.py` | Compiles native components, invokes PyInstaller, assembles helper/support resources, updates bundle metadata, and ad-hoc signs the application. |
| `install.py` | Local developer installation: stops the current app, waits for shutdown, backs it up, copies a clean bundle into Applications, verifies its signature, and opens it. |
| `package.py` | Builds the drag-to-Applications DMG and source ZIP. |
| `brand_active.py` | One-off migration used to rebrand the already-downloaded local player while stopped. Not a general release installer. |
| `restore_runtime.py` | One-off local recovery script with a hard-coded runtime identifier. Do not ship or use as normal application logic. |

`work/build-env`, `dist`, `pyinstaller`, `installer`, `mac-package-source`, and `previous-*.app` are local build/staging/backups, not source to commit wholesale.

## Launcher and runtime bootstrapping

`launch.py` normalizes temporary-directory use to `/tmp`; inheriting a short-lived build/tool temporary directory caused lifecycle problems during development. It sets a CA certificate path using certifi and captures normal application output in a per-user launcher log.

When an active downloaded runtime exists, the launcher executes that runtime's Python with `-I` and `managed_launch.py`. Inherited `PYTHON*` and `DYLD_*` environment entries are removed for this handoff. `managed_launch.py` adds the selected `packages` directory and wrapper support directory, supplies `sys._MEIPASS`/frozen conventions, and routes `sys.executable` back through the main app for restart/helper behavior. It disables bytecode writes so importing support files does not modify the signed bundle.

Resource lookup prefers the selected upstream package and falls back to bundled assets. Settings are overridden to enable the graphical interface and use the selected external mpv executable. Multiprocessing/helper invocations need particular care because upstream uses `sys.executable`, which is deliberately redirected; they must never claim main-application ownership or falsely mark a launch healthy.

## Title-bar/navigation fix

The screenshot showed the Mac title bar covering the top navigation controls. The compatibility layer reserves 32 logical screen points, scaled by the display's HiDPI factor, for a bordered window. It adjusts browser layout and invalidates layout when the window chrome state changes. Fullscreen does not receive that inset.

This is implemented through upstream class/method wrapping, not a modification to macOS window-manager behavior. Verify normal, resized, maximized, fullscreen, and mixed-DPI display transitions before release.

## Native scrolling

Simply removing list snapping did not solve the problem: the user reported that scrolling still felt linear and lacked normal Mac acceleration. The final implementation takes the precise scroll displacement AppKit has already calculated rather than inventing another acceleration curve.

`NativeScroll.m` installs a local `NSEvent` scroll-wheel monitor inside mpv. It preserves precise pixel deltas, natural-scroll behavior, and momentum, converts coordinates for backing scale, and locks the gesture axis. It uses mpv's Unix IPC socket to send `mpvtk-native-scroll` messages to the Lua renderer.

The patched renderer advertises whether it currently owns scrolling through `user-data/mpvtk-native-scroll`. Native events are intercepted only when that UI path is active; normal mouse-wheel handling can continue through mpv's existing path. A `user-data/mpvtk-native-scroll-loaded` property provides a diagnostic signal.

`local_compat.py` injects the dylib into the spawned mpv process with `DYLD_INSERT_LIBRARIES`. It creates a content-hashed patched renderer under the user's cache rather than editing signed bundled resources. Its Lua patches remove inappropriate rounding/snapping and translate native pixel displacement through the renderer's existing wheel handler.

No global event tap or new Accessibility permission was introduced for this scrolling feature. Compatibility with hardened-runtime/library-validation settings still needs deliberate work when moving to Developer ID signing.

## In-app updates

The entry point is **Settings > General > Check for Updates…**. The existing update banner is adapted to offer installation. A separate AppKit helper displays current/available component versions, progress, errors, and restart options, keeping terminal steps out of the user flow.

The helper calls the main executable in JSON worker modes, including `--mac-update-check` and `--mac-update-install`. It has its own bundle identity to avoid application activation conflicts. Restart asks the running app to stop, waits for the parent PID to exit, then opens the main bundle with `NSWorkspace`.

The full runtime updater queries three sources in parallel:

1. PyPI metadata for `jellyfin-mpv-shim`.
2. The latest `astral-sh/python-build-standalone` GitHub release, selecting an Apple Silicon install-only stripped CPython archive, currently allowing stable versions at least 3.13.
3. The latest `mpv-player/mpv` GitHub release, selecting a stable ARM Mac ZIP whose declared minimum macOS major version fits the current machine.

Python selection currently chooses the highest matching stable version. That is a prototype policy; moving automatically to a new Python minor release is more aggressive than a curated compatibility channel.

An installation takes a lock, resolves the release metadata, downloads Python/mpv in parallel, checks their published SHA-256 digests, and extracts them into staging. Downloads are restricted to expected GitHub release URL prefixes, capped at 512 MiB each, with extracted archives capped at 2 GiB. ZIP extraction checks paths/symlinks; tar extraction uses Python's `data` filter. The official mpv ZIP encountered here contained a nested `mpv.tar.gz`, which is handled explicitly.

The new Python installs upstream and dependencies from PyPI into a separate `packages` directory using isolated pip and `--only-binary=:all:`. No compiler is required for these updates. If suitable wheels are missing, installation fails and the old selection is retained. Dependencies are resolved at install time; they are not a fully pinned/hash-locked runtime set.

Before activation, the updater checks the Python version, executes mpv's version command, imports application dependencies, and verifies the expected upstream integration methods/Lua patch anchors. It repeats verification after moving the runtime to its final UUID directory, catching relocation problems.

A manifest records component versions, Python build release, relative executable paths, and Python/mpv archive digests. The active and previous runtime identifiers live in a separate state file. Writes replace a temporary state file atomically.

### Health and rollback

A selected launch is recorded as pending. The intended success criterion is an actual populated browser render without new build errors; merely importing packages or returning from `main()` must not mark it healthy. Helper/verification processes must not become the recorded owner.

The implementation tracks pending/owner PIDs and reverts to the previous selection after a dead pending launch. If no previous selection exists, fallback is the bundled application. This logic was revised during development to avoid helper ownership and false health reports, but the current unselected state means it still requires focused validation.

PID existence alone is a weak identity check because PIDs are reusable. State selection/health writes also deserve concurrent-process tests; the install lock does not serialize every launcher/health-state mutation. Store process start identity or use a stronger single-instance/state ownership design. Add explicit activation/rollback diagnostics so unexpected fallback is visible and explainable.

## Player name and icon

The downloaded official `mpv.app` originally appeared as “mpv” with the mpv icon in Cmd-Tab/Dock. `brand_player()` now updates its bundle name/display name to “Jellyfin MPV Shim”, gives it the dedicated player bundle ID, copies upstream's Jellyfin `.icns` over the application icon, and removes generic file/URL handler declarations from this private player bundle.

Because branding changes bundle contents, the modified player is ad-hoc re-signed and its signature verified. This happens during future runtime installations, after original archive verification and before activation. The existing selected runtime was migrated separately while stopped. macOS application registration was refreshed during local verification.

The actual executable remains named `mpv`, and the internal directory remains `mpv.app`; that preserves the executable discovery/path assumptions. User-visible identity comes from bundle metadata/icon resources.

## Local data layout

| Location under the user's home | Contents |
| --- | --- |
| `Library/Application Support/Jellyfin MPV Shim/Runtimes/state.json` | Selected/previous runtime and launch-health bookkeeping. |
| `Library/Application Support/Jellyfin MPV Shim/Runtimes/versions/<UUID>/` | Standalone `python/`, downloaded `player/mpv.app`, `packages/`, `manifest.json`. |
| `Library/Application Support/Jellyfin MPV Shim/Updates/` | Older package-only overlay implementation/state. |
| `Library/Application Support/jellyfin-mpv-shim/` | Upstream user configuration and connection data; the capitalization/path differs intentionally from wrapper runtime storage. |
| `Library/Caches/Jellyfin MPV Shim/Mac/` | Generated patched renderer. |
| `Library/Logs/Jellyfin MPV Shim/launcher.log` | Application/wrapper output. |

Keep accounts, tokens, server configuration, logs, caches, runtime downloads, and machine-specific activation state out of the repository and release source archive. This document deliberately omits connection details.

The two downloaded runtime IDs currently on this machine are `f33a47cd856d4b579c40bfdd333b7694` and `25d08c7ba2a14014b42a9086fcc877e3`. Both manifests report Jellyfin 3.2.0, Python 3.15.0, and mpv 0.41.0. These are debugging references, not identifiers to hard-code in the product.

## Build, install, and packaging

The local build used Python 3.13 in `work/build-env`, PyInstaller, Apple's Swift/Clang tooling, and Homebrew mpv at `/opt/homebrew/bin/mpv`. The source archive includes `requirements-build.txt` from the environment. The build script copies distribution metadata and collects upstream/API/IPC packages and Pillow's font support.

Expected local layout:

```text
work/
  source/                     # pinned upstream checkout, with shader pack
  build-env/                  # Python 3.13 environment
  launch.py, build.py, ...     # wrapper source files listed above
outputs/
```

From the project root, with those prerequisites prepared:

```sh
work/build-env/bin/python work/build.py
work/build-env/bin/python work/package.py
```

`build.py` produces `work/dist/Jellyfin MPV Shim.app`. It compiles `Updater.swift` and `NativeScroll.m`, assembles the nested helper, copies support modules and the Jellyfin icon, maintains the Frameworks/Resources support symlink, adds local-network usage metadata, includes the upstream license, and signs the final bundle.

`package.py` creates a DMG containing the application, an Applications shortcut, and a short installation readme. It also creates the source ZIP. `install.py` is an optional developer convenience that **modifies `/Applications`**, stops/replaces the current app, and keeps a timestamped backup in `work/`.

Always replace a bundle cleanly. Copying over an existing signed `.app` can leave stale files and invalidate its signature. Never write generated renderers or bytecode into a signed application. Do not mutate a packaged bundle after final signing without re-signing it.

Current deliverables:

- `outputs/Jellyfin-MPV-Shim-3.1.0-Apple-Silicon.dmg` — 61,027,358 bytes at handoff.
- `outputs/Jellyfin-MPV-Shim-Mac-Packaging-Source.zip` — 9,505,338 bytes at handoff. Contains wrapper/build sources, the upstream snapshot, shader assets, build requirements, and build notes.

The ZIP is the useful starting material for formalization, not the entire generated workspace. Its upstream snapshot has no Git history. Recover provenance by pinning the upstream commit/tag explicitly in the new repository.

## What was verified

During implementation:

- Built a self-contained Apple Silicon application and installed it cleanly into Applications.
- Connected to the user's existing servers and rendered the browser.
- Exercised native update dialogs/checks and installed a prebuilt Python/mpv/application runtime.
- Checked Python/mpv versions, imports, wrapper compatibility, and relocation.
- Confirmed the native scroll bridge reported loaded; the user confirmed the final trackpad feel.
- Observed macOS list the branded running player as “Jellyfin MPV Shim”; checked that the player icon matched the Jellyfin icon and its modified signature verified.
- Checked the main application signature and DMG integrity after final packaging.
- Observed update status “current” for Jellyfin 3.2.0 / Python 3.15.0 / mpv 0.41.0 at the end of that session.

Verification limits: this was local exploratory/smoke testing, not an automated release qualification. Native UI automation could list the branded running application but repeatedly failed to bind it for a direct Cmd-Tab screenshot; the identity/icon checks should not be represented as screenshot-based visual verification. The later `active: null` state supersedes any implication that the downloaded runtime is still selected today.

## Recommended repository structure

```text
README.md
LICENSE / third-party notices
pyproject.toml
src/macos_wrapper/
  launch.py
  managed_launch.py
  local_compat.py
  mac_update.py
  runtime_update.py
native/
  NativeScroll.m
  Updater.swift
assets/
  jellyfin.icns
scripts/
  build.py
  package.py
  install-local.py
upstream/                     # submodule or reproducibly fetched pinned source
tests/
docs/
  architecture.md
  updates.md
  release.md
.github/workflows/
```

That is a proposed layout; current scripts still assume the `work/` layout and need path/configuration changes before moving files. Use a reproducible upstream/shader-pack source mechanism rather than relying on untracked nested directories. Separate disposable migration/recovery scripts from supported product code.

## Prioritized next work

1. **Diagnose activation/rollback.** Reproduce normal quit/reopen, crash before/after first render, duplicate launch, helper invocation, stop/restart, and install/restart sequences. Explain the current lost selection before shipping. Add state transition logs and race/process-identity tests.
2. **Separate wrapper and component releases.** Give the wrapper its own version; display bundled and active component versions clearly. Add a signed/notarized wrapper update mechanism if “everything updates in-app” is the long-term requirement.
3. **Curate compatible runtime combinations.** Pin supported Python minor versions or publish a compatibility manifest. Avoid assuming the newest Python/upstream/mpv combination is safe because imports succeed. Define behavior when latest assets/wheels are missing, release naming changes, GitHub rate-limits requests, or the user is offline.
4. **Harden update reproducibility and integrity.** Lock/hash the Python dependency set, document the trust model, and validate extraction/redirect/metadata assumptions. Current archive digests come from the same GitHub API used for discovery; there is no separately signed wrapper release manifest.
5. **Formalize the Mac integrations.** Replace brittle string-replacement anchors/private-method wrapping where upstream extension points can be added. Keep the explicit compatibility rejection when upstream changes; do not silently install a release that loses scrolling or navigation fixes.
6. **Signing/distribution.** Add Developer ID signing/notarization and test the native bridge under hardened runtime. Audit licenses, source provenance, notices, and bundled third-party components for a distributable package; the current copied license is not a complete distribution inventory.
7. **CI and acceptance coverage.** Build on a clean Apple Silicon runner, verify signatures/artifacts, smoke-test a fresh profile, establish a minimum macOS version, and test update interruption/rollback. Add offline-launch, moving-the-app, multiple-display, fullscreen, mouse-wheel, and trackpad checks.
8. **Clean up prototype paths/code.** Remove or migrate the legacy overlay updater, hard-coded local recovery IDs, generated backups, and version naming inconsistencies. Define runtime retention/cleanup so downloaded versions do not grow indefinitely.

The central design worth preserving is the separation between a small Mac integration wrapper and replaceable, prebuilt upstream runtimes. The central unresolved issue is proving that activation, health reporting, shutdown, and rollback agree on which process/runtime owns the application.
