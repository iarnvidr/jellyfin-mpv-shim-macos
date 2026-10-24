import AppKit
import Foundation

if CommandLine.arguments[1] == "--list" {
    let apps = NSWorkspace.shared.runningApplications.filter {
        $0.bundleIdentifier?.hasPrefix("org.jellyfin.mpvshim") == true
    }.map { app -> [String: Any] in
        ["pid": Int(app.processIdentifier), "bundle": app.bundleURL?.path ?? "",
         "identifier": app.bundleIdentifier ?? "", "executable": app.executableURL?.path ?? ""]
    }
    print(String(decoding: try JSONSerialization.data(withJSONObject: apps), as: UTF8.self))
    exit(0)
}
let configuration = NSWorkspace.OpenConfiguration()
configuration.createsNewApplicationInstance = true
configuration.arguments = Array(CommandLine.arguments.dropFirst(2))
configuration.environment = ProcessInfo.processInfo.environment
NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: CommandLine.arguments[1]),
                                   configuration: configuration) { app, error in
    if let app = app {
        print(app.processIdentifier)
        exit(0)
    }
    fputs("Application launch failed: \(error?.localizedDescription ?? "unknown")\n", stderr)
    exit(1)
}
RunLoop.main.run()
