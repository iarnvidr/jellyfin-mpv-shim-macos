import AppKit
import Foundation
import Sparkle

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
            showError("The main Jellyfin MPV Shim application could not be located.")
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

let arguments = CommandLine.arguments
if arguments.count == 2 {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = Updater(appBundleURL: URL(fileURLWithPath: arguments[1]))
    app.delegate = delegate
    app.run()
}
