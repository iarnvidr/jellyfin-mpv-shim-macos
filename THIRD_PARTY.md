# Third-party notices and source policy

This repository contains an unofficial GPL-3.0-or-later macOS wrapper around Jellyfin MPV Shim. The wrapper license is in [LICENSE.md](LICENSE.md). The source baseline and shader provenance are recorded in [README.md](README.md); retain upstream and shader notices and their individual applicable licenses.

## Known dependencies and required distribution work

| Material | Known status / obligation |
| --- | --- |
| Jellyfin MPV Shim upstream | GPL-3.0-or-later; pinned source is `work/source`. Preserve its license and provide the corresponding source for the exact distributed version. |
| Default shader pack | `vendor/default-shader-pack`; preserve its included notices and honor each shader's license/source terms. |
| Python project dependencies | Current locked project dependencies are represented in `uv.lock`; each bundled dependency's license and source obligations must be reviewed for the exact artifact. |
| PyInstaller | Build dependency; its bootloader is included in the application. Preserve applicable license/notices and assess source obligations for distributed form. |
| CPython, mpv, native libraries | Intended bundle contents, but actual collected artifact inventory and immutable native origins are not yet audited. Obtain applicable licenses/notices and corresponding source for every distributed component. uv does not lock these native binaries. No Homebrew or alternative system package manager may supply build/runtime inputs; use verified immutable assets or controlled source builds. |
| Sparkle 2 | Planned updater dependency, not evidence of an included or qualified artifact. If distributed, pin exact version, retain notices, and include applicable source material. |
| Downloaded 0.1 prototype runtimes | Separate legacy runtime downloads had their own obligations. The new product intends no runtime component downloads; migration must not be confused with an audit of those historic artifacts. |

## Release rule

This is a known-input policy, **not a completed artifact inventory**. Historical Mac attempts that failed on Homebrew cache behavior are superseded by the no-package-manager constraint; they are not evidence of a successful build, nor proof that native inputs have been fully inventoried. Do not represent notices as complete, a DMG as audited, or source obligations as satisfied until the exact release artifact has been inspected. Before distribution, enumerate every bundled executable, framework, dylib, Python package, resource and license; record versions and provenance/hashes; determine each license's notice and corresponding-source requirements; include notices and source materials (including upstream and shader contents, which GitHub's generated archive omits for submodules); then independently verify the packaged contents. Record evidence and unresolved findings in the [qualification ledger](docs/RELEASE-QUALIFICATION-0.2.0.md). No artifact inventory audit is claimed here.
