import AppKit
import Foundation

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
