# Sparkle helper build integration

`Updater.swift` is compiled against the pinned Sparkle 2.10.0 `Sparkle.framework`
from the verified distribution in `work/native-dependencies.lock`. Build compiles
with `-F work -framework AppKit -framework Sparkle` and an executable rpath to
`Contents/Frameworks`; the framework must be copied into the main app before
runtime, with the nested helper's framework lookup resolving there.

The app's `Contents/Info.plist` must have `SUFeedURL` set to the production HTTPS
appcast and `SUPublicEDKey` set to the matching Sparkle-generated Ed25519 public
key. `SPARKLE_PUBLIC_ED_KEY` is the build input; an empty value intentionally
makes Sparkle's `canCheckForUpdates` fail closed. Never commit/store the private
key in source or build logs. The feed must describe complete app releases and
contain Sparkle archive signatures.

The helper must be bundled at `Contents/Helpers/Mac Updater.app`; its launch
argument is the main `.app` path. Sparkle 2.10.0 `SPUUpdater.h` specifies
`init(hostBundle:applicationBundle:userDriver:delegate:)` and documents that
`applicationBundle` controls termination/relaunch (normally same as host).
`SPUUpdater.start()` is required before `checkForUpdates()`. This integration
uses both bundles as the main application. The helper framework runpath and
embedded framework need validation on macOS, including code-signing order and
actual whole-app update/relaunch. Do not treat Linux static checks as that gate.
