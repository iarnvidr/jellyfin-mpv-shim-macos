# Changes

## 0.2.13

- Fix macOS windowing: stop rebuilding native menus on every poll, keep the host window from hiding when the player is minimized, clear stale player-closed state on reopen, and route the player close button correctly.

## 0.2.12

- Add **Copy Diagnostics** to the existing native Settings footer, reachable from the browser without the macOS menu bar.
- Automatically retain bounded local host/player menu-state history before opening Settings, including presentation flags, activation, window/display geometry, and two menu preferences. Reports exclude screenshots, server/media details, and telemetry.
- The reported disappearance of the entire macOS menu bar remains unresolved. This update adds evidence collection; it does not claim to fix that disappearance.
