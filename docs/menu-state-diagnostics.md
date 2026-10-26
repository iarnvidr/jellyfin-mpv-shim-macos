# Local menu-state diagnostics

This recorder observes the unresolved macOS system-menu-bar problem. It does not repair presentation state or establish why an affected Mac hides its menu bar.

The existing browser Settings button opens native Settings without requiring the system menu bar. Before creating or showing that window, the host freezes its own bounded history and reads the player's already-recorded history. The **Copy Diagnostics** footer button copies that frozen JSON to the local clipboard. Reopening Settings after closing it captures a new report; repeated requests while it remains visible preserve the original report.

Each process samples AppKit on the main thread once per second, and records presentation KVO and selected application/window/display notifications. Histories retain the initial state and at most 16 transitions. Only the latest eight transitions per process normally enter the copied report; omitted counts are explicit. Whole valid JSON is reduced further when necessary to remain within 64 KiB.

The report includes numeric window/display geometry, safe-area insets, scale, window flags, activation state, PID/session identity, launch version, OS version/build, requested and effective presentation flags, reported menu visibility, menu item count, and two allowlisted global menu preferences. Engine fullscreen/native-fs properties are explicitly unavailable in this first version; window style must not be treated as an engine fullscreen verdict. Reported menu visibility does not prove the rendered screen pixels.

There are no window/media titles, server addresses, app URLs, command-line arguments, screenshots, keystrokes, arbitrary preference enumeration, network requests, or telemetry. The recorder never sets presentation, activation, fullscreen, or preferences and requests no permissions.

Local files are fixed `host.json` and `engine.json` under `~/Library/Logs/Jellyfin Player/menu-state`, with a protected temporary file per role during atomic replacement. The directory is owner-only and files are created owner-only before content is written. Each file is capped at 256 KiB. The writer retains at most one in-flight and one pending snapshot. Transitions persist immediately; unchanged-state disk heartbeats occur every ten seconds. A peer older than fifteen seconds is labeled stale.

Peer files must match a closed schema, session/core/host identities, a live process launch identity, and the expected bundle location. Multiple live matching bundle processes are reported as ambiguous. Missing, invalid, exited, stale, mismatched, and newer-than-cutoff peers are explicit. Each sample has its own wall-clock and monotonic timestamp; both processes are **not** sampled atomically. The report includes the common pre-Settings monotonic cutoff and excludes later history.

Diagnostics use separate files and do not enter the native menu's serialized model comparison. Reading or copying diagnostics cannot rebuild the menu through a changing diagnostic field.
