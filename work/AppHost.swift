import AppKit
import Foundation
import Network
import Darwin

final class AppHost: NSObject, NSApplicationDelegate {
    private var core: Process?
    private var stopping = false
    private var signals: [DispatchSourceSignal] = []
    private let arguments = Array(CommandLine.arguments.dropFirst())

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let application = NSMenuItem()
        let commands = NSMenu()
        commands.addItem(withTitle: "Quit Jellyfin Player", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        application.submenu = commands
        menu.addItem(application)
        NSApp.mainMenu = menu

        let process = Process()
        process.executableURL = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Helpers/Jellyfin Player Core.app/Contents/MacOS/Jellyfin Player Core")
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["JELLYFIN_PLAYER_HOSTED"] = "1"
        process.environment = environment
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if self.stopping { NSApp.reply(toApplicationShouldTerminate: true) }
                else { NSApp.terminate(nil) }
            }
        }
        do {
            try process.run()
            core = process
        } catch {
            let alert = NSAlert()
            alert.messageText = "Jellyfin Player could not start"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            NSApp.terminate(nil)
        }
        for number in [SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { NSApp.terminate(nil) }
            source.resume()
            signals.append(source)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let core = core, core.isRunning else { return .terminateNow }
        if !stopping {
            stopping = true
            core.terminate()
        }
        return .terminateLater
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showPlayer()
        return false
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        showPlayer()
    }

    private func showPlayer() {
        guard !stopping, let core = core, core.isRunning else { return }
        var profile = URL(fileURLWithPath: "/Users/\(NSUserName())/Library/Application Support/jellyfin-mpv-shim")
        if let index = arguments.firstIndex(of: "--config"), index + 1 < arguments.count {
            profile = URL(fileURLWithPath: arguments[index + 1])
        }
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

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let host = AppHost()
app.delegate = host
app.run()
