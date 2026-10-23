import AppKit
import Foundation

final class Updater: NSObject, NSApplicationDelegate {
    let executable: String
    let parentPID: Int32
    var window: NSWindow!
    var label: NSTextField!
    var installing = false
    init(_ executable: String, _ pid: Int32) {
        self.executable = executable; self.parentPID = pid
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 140),
                          styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Jellyfin MPV Shim Updates"
        window.center()
        let spinner = NSProgressIndicator(frame: NSRect(x: 28, y: 50, width: 32, height: 32))
        spinner.style = .spinning; spinner.startAnimation(nil)
        label = NSTextField(labelWithString: "Checking for updates…")
        label.frame = NSRect(x: 80, y: 43, width: 330, height: 45)
        window.contentView?.addSubview(spinner)
        window.contentView?.addSubview(label)
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        run(["--mac-update-check"]) { result in self.checked(result) }
    }
    func run(_ args: [String], completion: @escaping ([String: Any]) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(); process.executableURL = URL(fileURLWithPath: self.executable)
            process.arguments = args
            let output = Pipe(); process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            var result: [String: Any]
            do {
                try process.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                result = (try JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    ?? ["status": "error", "message": "The updater returned an invalid response."]
            } catch { result = ["status": "error", "message": error.localizedDescription] }
            DispatchQueue.main.async { completion(result) }
        }
    }
    func alert(_ title: String, _ message: String, _ buttons: [String]) -> NSApplication.ModalResponse {
        window.orderOut(nil)
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = message
        for button in buttons { alert.addButton(withTitle: button) }
        return alert.runModal()
    }
    func checked(_ result: [String: Any]) {
        guard let status = result["status"] as? String else { fail("Could not check for updates."); return }
        if status == "error" { fail(result["message"] as? String ?? "Could not check for updates."); return }
        if status == "current" {
            _ = alert("You’re up to date", "Jellyfin MPV Shim \(result["current"] ?? "")\n\(result["runtime"] ?? "")", ["OK"])
            NSApp.terminate(nil); return
        }
        guard let latest = result["latest"] as? String else { fail("Missing release version."); return }
        if alert("Updates are available",
                 "\(result["components"] ?? "Jellyfin MPV Shim \(latest)")\n\nDownload and install? Your server connections and settings will be kept. Restart the app when you’re ready.",
                 ["Install Update", "Later"]) != .alertFirstButtonReturn {
            NSApp.terminate(nil); return
        }
        installing = true
        label.stringValue = "Preparing Python, mpv and Jellyfin…"
        window.makeKeyAndOrderFront(nil)
        run(["--mac-update-install", latest]) { result in
            if result["status"] as? String != "installed" {
                self.fail(result["message"] as? String ?? "The update could not be installed."); return
            }
            let answer = self.alert("Update ready", "Jellyfin MPV Shim \(latest)\n\(result["runtime"] ?? "")\n\nRestart to use the new versions.", ["Restart Now", "Later"])
            if answer == .alertFirstButtonReturn { self.restart() }
            else { NSApp.terminate(nil) }
        }
    }
    func fail(_ message: String) {
        _ = alert("Update could not be completed", message + "\n\nYour current app is still available.", ["OK"])
        NSApp.terminate(nil)
    }
    func restart() {
        label.stringValue = "Restarting Jellyfin MPV Shim…"
        window.makeKeyAndOrderFront(nil)
        run(["stop"]) { _ in
            DispatchQueue.global().async {
                var exited = false
                for _ in 0..<200 {
                    if kill(self.parentPID, 0) != 0 { exited = true; break }
                    Thread.sleep(forTimeInterval: 0.1)
                }
                DispatchQueue.main.async {
                    if !exited { self.fail("Close Jellyfin MPV Shim and open it again to finish the update."); return }
                    let appURL = URL(fileURLWithPath: self.executable).deletingLastPathComponent()
                        .deletingLastPathComponent().deletingLastPathComponent()
                    NSWorkspace.shared.openApplication(at: appURL, configuration: NSWorkspace.OpenConfiguration()) { _, _ in
                        DispatchQueue.main.async { NSApp.terminate(nil) }
                    }
                }
            }
        }
    }
}

let arguments = CommandLine.arguments
if arguments.count >= 3 {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = Updater(arguments[1], Int32(arguments[2]) ?? 0)
    app.delegate = delegate
    app.run()
}
