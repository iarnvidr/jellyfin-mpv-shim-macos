# Diagnostic-only menu ownership trace

This branch observes existing calls without adding a visibility, activation, or policy change. It is not a production release. Compare exact signed public 0.2.12 BEFORE the diagnostic copy, using the same qualified display session. Build through the normal macOS-15 workflow to retain the matched toolchain; preserve source/artifact identity and label the modified diagnostic bundle separately.

Set `JELLYFIN_MENU_OWNER_TRACE` to a dedicated case directory in the actual host launch environment (`open --env` for LaunchServices). The environment is inherited by core and engine. Files `owner-0.jsonl` (host) and `owner-1.jsonl` (engine) contain numeric fields only. Each process records at most 512 events, each file at most 1 MiB. No timestamps or fields enter the native menu model.

The trace starts before the host's regular-policy setter and before the engine's FIRST existing accessory-policy setter. Menu object identity is a bounded weak-map process-local token, not a pointer/address. `menuToken` is the current `NSApp.mainMenu`; `installedToken` is the last menu actually assigned by `PlayerMenuBar`. Generation increases only after our actual mainMenu assignment. These tokens can identify a 1→1 policy setter followed by unchanged menu identity and a skipped model/object guard. Tokens are not WindowServer menu-owner identity.

Each main-thread row also records up to 32 actual on-screen WindowServer menu/status-level windows as numeric arrays `[windowNumber, ownerPID, layer, x, y, width, height, alpha]`. This distinguishes a preserved NSMenu token from an absent per-display menu window. Extra WindowServer reads perturb timing and do not identify which application supplied the menu content.

Numeric phases:

| Phase | Observation |
| --- | --- |
| 1 / 2 | Immediately before / after existing host regular-policy setter |
| 10 | Enter existing applyPlayerBranding, before engine policy setter |
| 11 / 12 | Immediately before / after existing accessory-policy setter; result is actual setter BOOL |
| 13 / 14 | Immediately before / after existing JellyfinInstallNativeMenus call |
| 20 / 21 | Install entry / existing-session guard returned |
| 22 / 23 | New engine NativeMenuSession before / after initialization |
| 30 / 31 | Immediately before / after actual PlayerMenuBar mainMenu assignment |
| 32 / 33 | Native menu tracking began / ended |
| 34 | First model/object-equality guard skip after a policy-setter return |
| 40 | mainMenu KVO notification (not a guarantee of intercepting every external setter) |
| 50 | Effective presentation KVO notification |
| 60 | NSWorkspace active-Space-change notification |
| 70 / 71 | Application did become / resign active |
| 72 / 73 / 74 | Window became key / changed screen / changed backing properties |
| 80 / 81 / 82 / 83 | Window will enter / did enter / will exit / did exit native fullscreen |

`tests/native/TraceMenuDisplayState.m` is an independent read-only helper. Compile with `xcrun clang -fobjc-arc tests/native/TraceMenuDisplayState.m -o trace-menu-display -framework Cocoa -framework CoreGraphics`. Capture its stdout beside each passive image BEFORE interventions. It reports actual active CG display bounds and numeric window metadata intersecting each display's top 48 CG points, including unrelated covering windows. No window names, owner names, URLs, titles, or pixel data are read into its report. CG owner PID indicates the owner of the reported WindowServer window; it does not establish which application's menu content is selected.

Limitations: synchronous observation adds timing overhead. AppKit global `menuBarVisible` is not per-display rendered evidence. Keep independent passive screenshots and compare original published bytes; a diagnostic-only positive must be repeated without the trace before making a production-cause claim. No source visibility fix or 0.2.13 publication is part of this branch.
