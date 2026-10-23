# Plan: ship macOS wrapper 0.2.0

Status: implementation in progress; not released or qualified. Preparation includes uv project/lock files and work toward build/runtime/updater changes, but the scope below is not complete. No release gate is claimed passed. Track concrete qualification evidence in [the ledger](RELEASE-QUALIFICATION-0.2.0.md).

## Product outcome

An Apple Silicon user downloads a DMG from our GitHub Releases, drags one app
into Applications, opens it, connects to Jellyfin, and plays media. No terminal,
Homebrew, Python, uv, or package installation is required on their Mac.

Check for Updates offers complete Mac application releases from
`iarnvidr/jellyfin-mpv-shim-macos`. Installing a release replaces the wrapper,
native integrations, upstream client, private Python runtime, and mpv together.
Server connections and user settings survive the replacement.

The release remains ad-hoc signed unless Developer ID credentials become
available. Document the macOS first-open approval honestly. Sparkle update
signatures provide update authenticity; they do not provide Apple notarization.

## Scope and dependency decisions

| Component | Decision for 0.2.0 | Where it exists |
| --- | --- | --- |
| uv | Manage Python, dependencies, locking, and build commands | Developer machines and CI only |
| PyInstaller | Retain for the self-contained app; tighten its collected contents | Build tool; its bootloader is part of the app |
| CPython and client libraries | Bundle one tested private environment; never download replacements at runtime | Inside the app |
| mpv and required libraries | Bundle a versioned, recorded build with no Homebrew runtime dependency | Inside the app |
| Native scrolling/window integration | Preserve and test existing behavior | Inside the app |
| Sparkle 2 | Add one pinned native update framework and its required helpers | Inside the app |
| GitHub Releases | Host DMG, update archive, checksums, and source/provenance assets | Distribution |
| Appcast | Host a small version/signature feed on a dedicated GitHub branch | Distribution |

Do not add another GUI toolkit, a separate update service, runtime uv/pip, or
another packaging framework for this release. Do not rewrite the upstream UI.
Retain the existing pinned client/shader baseline during packaging migration;
upgrade upstream separately only if a release blocker requires it.

Initial target: Apple Silicon, macOS 15 and newer, subject to verification of
every bundled binary's actual minimum OS. Qualify macOS 15 and the user's Mac
before claiming that range. Intel/universal builds are a later release.

## 1. Establish the dependency and build baseline

Implement:

- Add root `pyproject.toml`, `.python-version`, and committed `uv.lock`. Separate
  application dependencies from build/test tools. Use the pinned upstream
  submodule as a local, non-editable source so its shader resources are bundled.
- Replace `requirements-build.txt`, manual virtualenv creation, and pip commands
  with `uv sync --locked` and `uv run --locked ...` in scripts, CI, and README.
  Pin the Python patch release and uv release used to produce releases.
- Retain `VERSION` as the wrapper's version source. Distinguish wrapper version
  from the upstream client version in diagnostic metadata.
- Record Python, upstream, shaders, mpv, native dependencies, Sparkle, toolchain,
  and source revisions in a build manifest. Hash downloads outside uv's lock.
- Resolve the current floating Homebrew mpv input: select a tested distributable
  build or controlled build source, record its immutable origin/hash and source
  provenance, and verify relocation. Do not claim uv locks native binaries.

Acceptance:

- A clean checkout prepares resources, syncs, checks, and builds using documented
  uv commands. Locked sync does not rewrite the lockfile.
- CI uses the same commands; no developer-specific paths remain.
- Inventory identifies what is bundled and why; build tools and unnecessary
  metadata are excluded where compatible with application resource discovery.

## 2. Prove the Sparkle integration before expanding the release pipeline

Implement:

- Pin a Sparkle 2 distribution and verify its download hash. Retain its notices.
- Integrate its native UI through our existing AppKit helper. Explicitly target
  the main Jellyfin app as the bundle being updated and relaunched, not the
  nested updater helper. Avoid adding a Python Objective-C bridge dependency.
- Use Sparkle's supported replacement, validation, authorization, and relaunch
  mechanisms rather than writing another installer.
- Configure an HTTPS appcast URL and embedded public Ed25519 key. Generate the
  private key securely, keep it outside Git, store the release credential in
  GitHub Actions secrets, and arrange a recoverable protected backup.
- Start with user-initiated Check for Updates. Any later automatic checks use
  Sparkle's preference model; do not add a resident updater daemon.

Acceptance on macOS:

- Two disposable application versions demonstrate discovery, signed download,
  whole-app replacement, clean shutdown, and correct relaunch using a test feed.
- Test uses the actual packaged helper and app identity. An import or compile
  check alone does not satisfy this gate.
- A modified archive or wrong signing key is rejected without replacing the
  installed app. Check cancellation, offline use, and unwritable installation.
- Validate the ad-hoc-signed configuration. If helper-based hosting fails,
  resolve that integration first and revise this plan before adding another
  framework or building a custom replacement mechanism.

## 3. Remove the prototype's component updater

Implement:

- Simplify `work/launch.py` to always execute the environment bundled in the app.
  Stop selecting downloaded Python runtimes and package overlays.
- Remove `runtime_update.py`, `managed_launch.py`, the wheel-overlay installer,
  and obsolete worker/health/ownership paths once no live callers remain.
- Replace the custom download/install dialogs in `Updater.swift` with the
  validated Sparkle integration. Keep the settings update button; show the Mac
  app version, and remove Python/mpv installation details from ordinary UI.
- Ensure upstream's update banner cannot advertise or install an independent
  PyPI release. Route the update experience through our app release feed.
- Ignore legacy `Updates/` and `Runtimes/` selections from 0.1.0. Preserve user
  data and leave old runtime files untouched initially; no broad cleanup on launch.
- Document a one-time manual installation of 0.2.0 for 0.1.0 users. Their old
  updater cannot deliver the new wrapper. Later versions can use Sparkle.

Acceptance:

- Test with a fresh profile and fixtures containing active, pending, broken,
  and stale legacy runtime selections. All launch the new bundled client.
- Existing connections/settings survive; unavailable old runtime folders cannot
  prevent startup. No runtime code executes pip or fetches Python/PyPI updates.
- Quit, repeated launch, stop commands, and reopening work without the old
  owner-PID/health-state rollback mechanism.

## 4. Finish the application bundle and installer

Implement:

- Tighten PyInstaller collection without breaking fonts, shaders, certificates,
  native libraries, or upstream distribution metadata actually used at runtime.
- Give the main app, updater, and running player consistent names/icons. Choose
  a permanent bundle identifier before shipping 0.2.0; explicitly test any
  migration from `org.jellyfin.mpvshim.local` and avoid breaking settings paths.
- Preserve framework symlinks, executable permissions, and native loader paths.
  Bundle mpv's required libraries. Never modify the app after final signing.
- Produce a drag-to-Applications DMG and a Sparkle-compatible whole-app archive
  with `ditto` or equivalent symlink-preserving packaging. Sign the update archive
  with Sparkle's tool, not an improvised crypto format.
- Include complete applicable notices, build provenance, and corresponding
  source material required for the actual bundled components. The current
  upstream-only license copy is insufficient.

Acceptance:

- On a Mac without Homebrew/Python/uv, install from the downloaded artifact,
  launch, connect, browse, and play media. No external developer tools are needed.
- Move the app, test paths with spaces, and verify offline relaunch. Audit linked
  libraries for references to `/opt/homebrew`, build directories, or unbundled
  dependencies. Confirm minimum-OS metadata for collected native binaries.
- Test mouse/trackpad scrolling, window controls, fullscreen, seek, subtitles,
  audio, and normal shutdown. Verify app signatures and DMG integrity.
- Observe the actual first-open Gatekeeper experience and document it; don't
  describe the package as notarized or disable system-wide protections.

## 5. Automate releases and the update feed

Implement:

- Extend the macOS workflow into build/test/package and a separate publish job.
  Use minimal permissions; untrusted pull requests never receive release keys.
- Validate that the tag matches `VERSION` and bundle versions. Build release
  artifacts once, test them, then upload those same artifacts to a draft release.
- Include DMG, update archive, checksums, build manifest, and source bundle with
  upstream/shader content. GitHub's automatic archives omit submodule contents.
- Publish a Sparkle appcast at the fixed URL
  `https://raw.githubusercontent.com/iarnvidr/jellyfin-mpv-shim-macos/updates/appcast.xml`.
  Each entry contains the wrapper/build version, OS requirement, release notes,
  exact GitHub Release asset URL, byte length, and archive signature.
- Test using an isolated feed. Do not advertise test or prerelease builds in the
  production feed. Keep this release to one production update channel.
- Serialize production publication. Verify public asset availability before
  advancing the feed. Retain the prior feed if any preceding step fails; prevent
  an older workflow from overwriting a newer version. Never overwrite a published
  update archive with different bytes under the same version.

Acceptance:

- A draft release has all assets and verifiable hashes/signatures. The appcast's
  URLs, versions, lengths, and minimum OS agree with those assets.
- A failed build/upload does not change the production feed. A feed publication
  failure is clearly retryable after the release is available.
- Preserve previous releases for manual recovery. Document feed withdrawal and
  reinstalling a prior compatible app; Sparkle signature verification is not an
  application-health rollback system and should not be presented as one.

## 6. Qualify and ship 0.2.0

**Current status: all interactive and release acceptance gates pending.** No release claim is made. The historical prototype handoff is retained unchanged and is not evidence for 0.2.0. See [qualification ledger](RELEASE-QUALIFICATION-0.2.0.md), [installation and recovery](INSTALL-AND-RECOVERY.md), and [third-party notice policy](../THIRD_PARTY.md). In particular, the one-time 0.1.0 upgrade is manual, first-open behavior is ad-hoc/unnotarized and must be observed, rollback is manual, signing-key backup is a procedure only (setup not claimed), and the interactive OS/playback/update matrix remains pending.

Release checklist:

- [ ] Locked uv build and upstream integration checks pass from clean checkout. **Pending; not claimed passed.**
- [ ] Fresh install on a Mac with no developer tooling passes.
- [ ] macOS 15 and the user's current macOS receive an interactive smoke test.
- [ ] 0.1.0 manual upgrade retains settings and ignores all legacy runtime state.
- [ ] Packaged Sparkle test update replaces/relaunches the main app successfully.
- [ ] Wrong signatures, cancellation, offline operation, and permission failures
      preserve the installed application.
- [ ] Playback, scrolling, fullscreen, relocation, and quit/reopen pass.
- [ ] Bundle contents, licenses/source obligations, minimum OS, and signatures
      are reviewed against the actual artifact.
- [ ] README explains installation, first-open approval, update source, supported
      platform, and recovery without exposing build steps in the normal user flow.
- [ ] Draft release assets are verified before publication; publish release,
      then production appcast, and verify both public downloads and the feed.

Do not mark the release ready solely because GitHub Actions is green. Record
interactive test results and unresolved limitations alongside the release.

## Suggested implementation sequence

1. `build: migrate to locked uv project and record build inputs`
2. `updater: integrate and validate Sparkle whole-app replacement`
3. `runtime: remove component switching and preserve legacy user settings`
4. `package: finalize relocatable app, branding, and distribution inventory`
5. `ci: publish verified release assets and signed appcast`
6. `release: qualify and document 0.2.0`

Implementation can proceed through build and automated checks autonomously.
Actual GUI/first-open/update testing needs a usable Mac session; record that as
outstanding evidence when unavailable, rather than inferring success from CI.

## References

- [uv project and lockfile workflow](https://docs.astral.sh/uv/guides/projects/)
- [Sparkle integration](https://sparkle-project.org/documentation/)
- [Sparkle host/application bundles](https://sparkle-project.org/documentation/bundles/)
- [Sparkle update publication and signing](https://sparkle-project.org/documentation/publishing/)
- [Original prototype handoff](REPOSITORY-HANDOFF.md)
