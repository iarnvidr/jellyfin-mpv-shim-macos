import AppKit
import Foundation
import Sparkle
import Darwin

/// A small native host for Sparkle. The host bundle is the *main* application,
/// never this nested helper; consequently Sparkle replaces and relaunches the app.
final class Updater: NSObject, NSApplicationDelegate {
    private let appBundleURL: URL
    private var updater: SPUUpdater!
    private var userDriver: SPUStandardUserDriver!

    init(appBundleURL: URL) {
        self.appBundleURL = appBundleURL.standardizedFileURL
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard appBundleURL.pathExtension == "app",
              let hostBundle = Bundle(url: appBundleURL),
              hostBundle.bundleIdentifier == "org.jellyfin.mpvshim.local" else {
            showError("The main Jellyfin Player application could not be located.")
            return
        }
        // SPUUpdater is explicitly created for the containing app's bundle.
        // Keep the delegate alive: SPUUpdater's userDriver and delegate are weakly held.
        userDriver = SPUStandardUserDriver(hostBundle: hostBundle, delegate: nil)
        updater = SPUUpdater(hostBundle: hostBundle, applicationBundle: hostBundle,
                             userDriver: userDriver, delegate: nil)
        do {
            try updater.start()
        } catch {
            showError("Sparkle could not start: \(error.localizedDescription)")
            return
        }
        guard updater.canCheckForUpdates else {
            showError("Sparkle updates are not configured for this application.")
            return
        }
        NSApp.activate(ignoringOtherApps: true)
        updater.checkForUpdates()
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Check for Updates"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
if arguments == ["--dyld-smoke"] {
    // Taking the metatype forces a real reference to Sparkle's public API while
    // deliberately avoiding NSApplication, windows, and the run loop.
    _ = SPUUpdater.self
    print("JELLYFIN_PLAYER_SPARKLE_DYLD_OK")
    exit(0)
}
guard arguments.count == 1,
      !arguments[0].hasPrefix("-"),
      let hostBundle = Bundle(url: URL(fileURLWithPath: arguments[0])),
      hostBundle.bundleURL.pathExtension == "app",
      hostBundle.bundleIdentifier == "org.jellyfin.mpvshim.local" else {
    fputs("Usage: Mac Updater <main Jellyfin Player .app>\n", stderr)
    exit(2)
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = Updater(appBundleURL: hostBundle.bundleURL)
app.delegate = delegate
app.run()
