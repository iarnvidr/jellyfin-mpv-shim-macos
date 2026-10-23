import AppKit
import Foundation

let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 2 else { exit(2) }
let report = URL(fileURLWithPath: args[0])
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
application.finishLaunching()
let alert = NSAlert()
alert.alertStyle = .critical
alert.messageText = "Jellyfin Player could not open"
alert.informativeText = args[1] + "\n\nDetails: " + report.path
alert.addButton(withTitle: "Quit")
alert.addButton(withTitle: "Copy Diagnostics")
alert.addButton(withTitle: "Open Logs")
application.activate(ignoringOtherApps: true)
while true {
    switch alert.runModal() {
    case .alertSecondButtonReturn:
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString((try? String(contentsOf: report, encoding: .utf8)) ?? args[1], forType: .string)
    case .alertThirdButtonReturn:
        NSWorkspace.shared.open(report.deletingLastPathComponent())
    default: exit(0)
    }
}
