import AppKit
import Foundation
import Network
import Darwin
import Sparkle

final class AppHost: NSObject, NSApplicationDelegate {
    private func log(_ message: String) {
        FileHandle.standardError.write(Data(("AppHost \(Date().timeIntervalSince1970): \(message)\n").utf8))
    }
    private var core: Process?
    private let sessionID = UUID().uuidString
    private var stopping = false
    private var signals: [DispatchSourceSignal] = []
    private var menus: NativeMenuSession?
    private var playerClosed = false
    private var updater: SPUStandardUpdaterController?
    private let arguments = Array(CommandLine.arguments.dropFirst())

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Keep Sparkle's scheduler alive for the lifetime of the actual app.
        updater = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
        let process = Process()
        process.executableURL = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Helpers/Jellyfin Player Core.app/Contents/MacOS/Jellyfin Player Core")
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["JELLYFIN_PLAYER_HOSTED"] = "1"
        environment["JELLYFIN_PLAYER_SESSION_ID"] = sessionID
        environment["JELLYFIN_PLAYER_HOST_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        process.environment = environment
        process.terminationHandler = { [weak self] process in
            self?.log("Core exited status=\(process.terminationStatus)")
            // terminateLater can run a nested AppKit loop from a main-queue
            // signal handler. Dispatching back to that queue would wait for
            // terminate() to return, while terminate() waits for this reply.
            RunLoop.main.perform(inModes: [.common, .modalPanel]) {
                guard let self = self else { return }
                self.log("Core exit on main queue; stopping=\(self.stopping)")
                if self.stopping { NSApp.reply(toApplicationShouldTerminate: true) }
                else { NSApp.terminate(nil) }
            }
        }
        do {
            try process.run()
            core = process
            menus = NativeMenuSession(lock: profileURL.appendingPathComponent("instance.lock"),
                                      corePID: Int(process.processIdentifier), sessionID: sessionID,
                                      updates: { [weak self] command in self?.updateCommand(command) }) { NSApp.terminate(nil) }
        } catch {
            let alert = NSAlert()
            alert.messageText = "Jellyfin Player could not start"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            NSApp.terminate(nil)
        }
        for number in [SIGTERM, SIGINT, SIGUSR1, SIGUSR2, SIGURG, SIGWINCH, SIGALRM] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler {
                if number == SIGUSR1 { NSApp.hide(nil) }
                else if number == SIGUSR2 { self.playerClosed = false; NSApp.unhideWithoutActivation() }
                else if number == SIGWINCH { self.playerClosed = true }
                else if number == SIGURG { self.menus?.openSettings() }
                else if number == SIGALRM { _ = self.updateCommand("updates-check") }
                else { NSApp.terminate(nil) }
            }
            source.resume()
            signals.append(source)
        }
    }

    private func updateCommand(_ command: String) -> [String: Any]? {
        guard command.hasPrefix("updates-"), let updater = updater?.updater else { return nil }
        switch command {
        case "updates-check": updater.checkForUpdates()
        case "updates-checks:on": updater.automaticallyChecksForUpdates = true
        case "updates-checks:off": updater.automaticallyChecksForUpdates = false
        case "updates-downloads:on": updater.automaticallyDownloadsUpdates = true
        case "updates-downloads:off": updater.automaticallyDownloadsUpdates = false
        case "updates-state": break
        default: return ["ok": false]
        }
        return ["ok": true, "checks": updater.automaticallyChecksForUpdates,
                "downloads": updater.automaticallyDownloadsUpdates,
                "allowsDownloads": updater.allowsAutomaticUpdates,
                "canCheck": updater.canCheckForUpdates,
                "version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown",
                "lastCheck": updater.lastUpdateCheckDate.map { DateFormatter.localizedString(from: $0, dateStyle: .medium, timeStyle: .short) } ?? "Never"]
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        log("Quit requested; Core running=\(core?.isRunning ?? false), stopping=\(stopping)")
        guard let core = core, core.isRunning else { return .terminateNow }
        if !stopping {
            stopping = true
            core.terminate()
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Preserve startup failures reported by Core (including lock conflicts)
        // when the native host closes after its diagnostic dialog is dismissed.
        if let core = core, !core.isRunning, core.terminationStatus != 0 {
            exit(core.terminationStatus)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        playerClosed = false
        NSApp.unhide(nil)
        showPlayer()
        return false
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        // Hiding the child can briefly activate the host. Let its hide signal
        // arrive before deciding whether this was an intentional app switch.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            if NSApp.isActive && !NSApp.isHidden && self?.playerClosed == false && NSApp.keyWindow == nil && self?.menus?.isTracking != true { self?.showPlayer() }
        }
    }

    func applicationDidHide(_ notification: Notification) {
        let player = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/mpv.app").resolvingSymlinksInPath()
        for application in NSRunningApplication.runningApplications(withBundleIdentifier: "org.jellyfin.mpvshim.player") {
            if application.bundleURL?.resolvingSymlinksInPath() == player { application.hide() }
        }
    }

    private var profileURL: URL {
        var profile = URL(fileURLWithPath: "/Users/\(NSUserName())/Library/Application Support/jellyfin-mpv-shim")
        if let index = arguments.firstIndex(of: "--config"), index + 1 < arguments.count {
            profile = URL(fileURLWithPath: arguments[index + 1])
        }
        return profile
    }

    private func showPlayer() {
        guard !NSApp.isHidden, !stopping, let core = core, core.isRunning else { return }
        let profile = profileURL
        guard let text = try? String(contentsOf: profile.appendingPathComponent("instance.lock"), encoding: .utf8) else { return }
        let lines = text.components(separatedBy: .newlines)
        guard lines.count >= 3, let port = UInt16(lines[0]),
              let data = lines[2].data(using: .utf8),
              let identity = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              (identity["pid"] as? Int) == Int(core.processIdentifier),
              let endpoint = NWEndpoint.Port(rawValue: port) else { return }
        let connection = NWConnection(host: "127.0.0.1", port: endpoint, using: .tcp)
        connection.stateUpdateHandler = { state in
            if case .ready = state {
                connection.send(content: Data(("JMS1" + lines[1] + "\n").utf8), completion: .contentProcessed { error in
                    if error != nil { connection.cancel(); return }
                    connection.receive(minimumIncompleteLength: 6, maximumLength: 6) { _, _, _, _ in connection.cancel() }
                })
            }
        }
        connection.start(queue: .global())
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) { connection.cancel() }
    }
}

@main
struct JellyfinApplication {
    static func main() {
        let app = NSApplication.shared
        traceMenuOwner(1, -1)
        let policyResult = app.setActivationPolicy(.regular)
        traceMenuOwner(2, policyResult ? 1 : 0)
        let host = AppHost()
        app.delegate = host
        withExtendedLifetime(host) { app.run() }
    }
}
