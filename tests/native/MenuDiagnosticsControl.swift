import AppKit
import Foundation

// Test-only independent setter. This is never linked into the player or its
// recorder. It intentionally changes its own presentation options so the
// player's background observer must report a real external system change.
final class MenuDiagnosticsControl: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var timer: Timer?
    private var previous = ""
    private let commands: URL
    private let output: URL
    private let started = ProcessInfo.processInfo.systemUptime

    init(commands: URL, output: URL) {
        self.commands = commands
        self.output = output
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let app = NSMenuItem(title: "Control Fixture", action: nil, keyEquivalent: "")
        let submenu = NSMenu()
        submenu.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = submenu
        menu.addItem(app)
        NSApp.mainMenu = menu
        let window = NSWindow(contentRect: NSRect(x: 100, y: 120, width: 400, height: 200),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Menu Diagnostics Control Fixture"
        window.isReleasedWhenClosed = false
        self.window = window
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        write("launched")
    }

    private func tick() {
        if ProcessInfo.processInfo.systemUptime - started > 120 {
            NSApp.presentationOptions = []
            write("timeout-normalized")
            NSApp.terminate(nil)
            return
        }
        guard let text = try? String(contentsOf: commands, encoding: .utf8) else { return }
        let command = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard command != previous else { return }
        previous = command
        switch command {
        case "normal":
            NSApp.presentationOptions = []
            write("normal")
        case "hide":
            NSApp.presentationOptions = [.autoHideMenuBar, .autoHideDock]
            write("hide")
        case "quit":
            NSApp.presentationOptions = []
            write("quit-normalized")
            NSApp.terminate(nil)
        default:
            write("unknown-command")
        }
    }

    private func write(_ phase: String) {
        let frontmost = NSWorkspace.shared.frontmostApplication
        let record: [String: Any] = [
            "phase": phase,
            "wallTime": Date().timeIntervalSince1970,
            "uptime": ProcessInfo.processInfo.systemUptime,
            "pid": ProcessInfo.processInfo.processIdentifier,
            "frontmostPID": frontmost?.processIdentifier ?? -1,
            "active": NSApp.isActive,
            "requestedPresentationOptions": NSApp.presentationOptions.rawValue,
            "effectivePresentationOptions": NSApp.currentSystemPresentationOptions.rawValue,
            "reportedMenuBarVisible": NSMenu.menuBarVisible(),
            "windowStyleMask": window?.styleMask.rawValue ?? 0,
            "windowOnActiveSpace": window?.isOnActiveSpace ?? false
        ]
        guard var data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) else { return }
        data.append(0x0a)
        if !FileManager.default.fileExists(atPath: output.path) {
            _ = FileManager.default.createFile(atPath: output.path, contents: nil)
        }
        guard let file = try? FileHandle(forWritingTo: output) else { return }
        do { try file.seekToEnd(); try file.write(contentsOf: data); try file.close() }
        catch { try? file.close() }
    }
}

guard CommandLine.arguments.count == 3 else { fatalError("Expected command-file and output-file") }
let app = NSApplication.shared
let controller = MenuDiagnosticsControl(commands: URL(fileURLWithPath: CommandLine.arguments[1]),
                                        output: URL(fileURLWithPath: CommandLine.arguments[2]))
app.delegate = controller
app.run()
