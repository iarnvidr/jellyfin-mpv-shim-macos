# Jellyfin MPV Shim for macOS

Unofficial Apple Silicon macOS packaging and integration for [Jellyfin MPV Shim](https://github.com/jellyfin/jellyfin-mpv-shim). The wrapper adds Finder launching, Mac window/trackpad integration, and (planned) whole-app updates while keeping the upstream client separate.

**0.2.0 preparation; not released or qualified.** The version is a preparation identifier, not a release claim. Automated build/runtime changes are in progress. No release gates are claimed passed. See the [shipping plan](docs/PLAN-0.2.0.md), [qualification ledger](docs/RELEASE-QUALIFICATION-0.2.0.md), [installation/recovery guide](docs/INSTALL-AND-RECOVERY.md), and [third-party notices policy](THIRD_PARTY.md). Historical prototype findings remain in the [original handoff](docs/REPOSITORY-HANDOFF.md), which is retained unchanged.

## User-facing status

The intended 0.2.0 product is a self-contained app: no terminal, Homebrew, Python, uv, or package installation should be needed on the user's Mac. That is a target, not yet evidence. The intended initial architecture is Apple Silicon and macOS 15+, subject to binary minimum-OS inspection and interactive testing. Intel is not in scope. The prototype was ad-hoc signed, not Developer ID signed or notarized; expect macOS first-open approval and use only the per-app approval flow described in the recovery guide. Do not disable Gatekeeper system-wide. The exact first-open prompt has not been qualified.

**0.1.0 users:** this transition requires one manual download/install of 0.2.0; the old component updater cannot update the wrapper. Preserve settings and do not delete legacy `Updates/` or `Runtimes/` content as a migration shortcut. See [upgrade and recovery](docs/INSTALL-AND-RECOVERY.md). Sparkle whole-app updating is planned and itself remains unqualified.

## Development setup (maintainers)

The project anticipates pinned uv 0.13.1 and Python 3.13, with the upstream client as a pinned local source. These are developer/build tools, not user runtime requirements. From a clean checkout on macOS, after installing Xcode command line tools and obtaining required native build inputs:

```sh
uv sync --locked --group build
uv run --locked python scripts/prepare.py
uv run --locked python scripts/check.py
uv run --locked python work/build.py
uv run --locked python work/package.py
```

These commands are preparation instructions, not evidence that a release build or packaged app has passed qualification. Maintainer build/dev/release/runtime flows must not install or rely on Homebrew or any alternative system package manager. Use pinned uv/Python and the Xcode-provided SDK/compiler tools only, plus native assets whose provenance and hashes are verified or dependencies built from controlled source. Do not accept ambient `/opt/homebrew` or other package-manager paths as inputs. See the plan for unresolved native mpv provenance and artifact audits. The manual macOS workflow is development automation, not release qualification.

## Source and versioning

- `work/`: wrapper, native integration, and build/package scripts.
- `work/source`: upstream submodule, baseline `v3.1.0` (`7e9fd292459358dde12f054c24f79642ab5ec98f`).
- `vendor/default-shader-pack`: shader submodule, baseline `v3.0.0` (`9ab0195ece699680b422ec5bb2216d45e14c82b1`).
- `VERSION`: wrapper preparation version (`0.2.0`); distinct from upstream and component versions.

The product is not an official Jellyfin release. GPL-3.0-or-later; see [LICENSE.md](LICENSE.md) and [THIRD_PARTY.md](THIRD_PARTY.md).
