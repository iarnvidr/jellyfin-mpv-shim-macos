import AppKit
import Network
import Darwin

// Shared by the Dock host and the process that owns the video window. AppKit
// routes key equivalents to the latter even when the former owns the Dock.
final class PlayerMenuBar: NSObject, NSMenuDelegate {
    private let perform: (String) -> Void
    private let quit: () -> Void
    private var tracking = 0
    private var pending: [String: Any]?
    private var lastModel: Data?
    private var installedMenu: NSMenu?
    var isTracking: Bool { tracking > 0 }

    init(perform: @escaping (String) -> Void, quit: @escaping () -> Void) {
        self.perform = perform
        self.quit = quit
        super.init()
        update(["application": [], "menus": ["File", "Edit", "Playback", "Audio", "Subtitles", "Video", "Window", "Help"].map {
            ["title": $0, "items": [["title": "Starting Jellyfin Player…", "enabled": false]]]
        }])
    }

    private func native(_ title: String, _ selector: Selector, _ key: String = "", target: AnyObject? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: key)
        item.target = target ?? NSApp
        return item
    }

    private func populate(_ menu: NSMenu, _ entries: [[String: Any]]) {
        menu.autoenablesItems = false
        menu.delegate = self
        for entry in entries {
            guard let title = entry["title"] as? String else { menu.addItem(.separator()); continue }
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: entry["key"] as? String ?? "")
            if let children = entry["items"] as? [[String: Any]] {
                let submenu = NSMenu(title: title)
                populate(submenu, children)
                item.submenu = submenu
                item.isEnabled = !children.isEmpty
            } else {
                item.action = #selector(command(_:))
                item.target = self
                item.representedObject = entry["command"] as? String
                item.isEnabled = entry["enabled"] as? Bool ?? false
                item.state = (entry["checked"] as? Bool ?? false) ? .on : .off
                var modifiers: NSEvent.ModifierFlags = []
                for name in entry["modifiers"] as? [String] ?? ["command"] {
                    switch name {
                    case "command": modifiers.insert(.command)
                    case "control": modifiers.insert(.control)
                    case "option": modifiers.insert(.option)
                    case "shift": modifiers.insert(.shift)
                    default: break
                    }
                }
                item.keyEquivalentModifierMask = modifiers
            }
            menu.addItem(item)
        }
    }

    func update(_ model: [String: Any]) {
        // Never replace a menu under the pointer while the user is choosing.
        if tracking > 0 { pending = model; return }
        guard let data = try? JSONSerialization.data(withJSONObject: model, options: [.sortedKeys]) else { return }
        if data == lastModel && NSApp.mainMenu === installedMenu { return }
        lastModel = data
        let bar = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "Jellyfin Player")
        appMenu.addItem(native("About Jellyfin Player", #selector(NSApplication.orderFrontStandardAboutPanel(_:))))
        appMenu.addItem(.separator())
        populate(appMenu, model["application"] as? [[String: Any]] ?? [])
        appMenu.addItem(.separator())
        let services = NSMenu(title: "Services")
        let serviceItem = NSMenuItem(title: "Services", action: nil, keyEquivalent: "")
        serviceItem.submenu = services
        appMenu.addItem(serviceItem)
        NSApp.servicesMenu = services
        appMenu.addItem(.separator())
        appMenu.addItem(native("Hide Jellyfin Player", #selector(NSApplication.hide(_:)), "h"))
        let hideOthers = native("Hide Others", #selector(hideOtherApplications(_:)), "h", target: self)
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(native("Show All", #selector(NSApplication.unhideAllApplications(_:))))
        appMenu.addItem(.separator())
        appMenu.addItem(native("Quit Jellyfin Player", #selector(quitPlayer(_:)), "q", target: self))
        appItem.submenu = appMenu
        bar.addItem(appItem)
        for section in model["menus"] as? [[String: Any]] ?? [] {
            guard let title = section["title"] as? String else { continue }
            let menu = NSMenu(title: title)
            populate(menu, section["items"] as? [[String: Any]] ?? [])
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            item.submenu = menu
            bar.addItem(item)
            if title == "Help" { NSApp.helpMenu = menu }
        }
        NSApp.mainMenu = bar
        installedMenu = bar
        if let path = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_MENU_DIAGNOSTICS"] {
            // The distribution smoke test inspects the actual installed AppKit
            // menus in both processes, without requiring Accessibility access.
            let directory = URL(fileURLWithPath: path)
            let result: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier,
                "menus": bar.items.dropFirst().map(\.title), "model": model]
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            if let data = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted]) {
                try? data.write(to: directory.appendingPathComponent("\(ProcessInfo.processInfo.processIdentifier).json"), options: .atomic)
            }
        }
    }

    func unavailable() {
        guard let data = lastModel,
              var model = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return }
        func disable(_ entries: [[String: Any]]) -> [[String: Any]] {
            entries.map { entry in
                var item = entry
                item["enabled"] = false
                if let children = item["items"] as? [[String: Any]] { item["items"] = disable(children) }
                return item
            }
        }
        model["application"] = disable(model["application"] as? [[String: Any]] ?? [])
        model["menus"] = disable(model["menus"] as? [[String: Any]] ?? [])
        model["ready"] = false
        update(model)
    }

    @objc private func command(_ sender: NSMenuItem) {
        if let command = sender.representedObject as? String {
            if let editor = NSApp.keyWindow?.firstResponder as? NSTextView {
                let selectors: [String: Selector] = ["edit-x": #selector(NSText.cut(_:)),
                    "edit-c": #selector(NSText.copy(_:)), "edit-v": #selector(NSText.paste(_:)),
                    "edit-a": #selector(NSText.selectAll(_:)), "edit-z": Selector(("undo:")),
                    "edit-Z": Selector(("redo:"))]
                if let selector = selectors[command] { NSApp.sendAction(selector, to: editor, from: sender); return }
            }
            if let window = NSApp.keyWindow, window.windowController is NativeSettings {
                if command == "close" { window.performClose(sender); return }
                if command == "minimize" { window.performMiniaturize(sender); return }
                if command == "zoom" { window.performZoom(sender); return }
            }
            perform(command)
        }
    }

    @objc private func quitPlayer(_ sender: Any?) { quit() }
    @objc private func hideOtherApplications(_ sender: Any?) {
        // The window and Dock belong to separate processes of the same app.
        // AppKit's default hide-other-applications would hide one of them.
        let hostPID = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_HOST_PID"].flatMap(Int32.init)
            ?? ProcessInfo.processInfo.processIdentifier
        let bundle = NSRunningApplication(processIdentifier: hostPID)?.bundleURL
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular {
            if app.processIdentifier == hostPID { continue }
            if let root = bundle?.path, let path = app.bundleURL?.path,
               path == root || path.hasPrefix(root + "/") { continue }
            app.hide()
        }
    }
    func menuWillOpen(_ menu: NSMenu) {
        tracking += 1
        if let editor = NSApp.keyWindow?.firstResponder as? NSTextView {
            for item in menu.items {
                guard let command = item.representedObject as? String, command.hasPrefix("edit-") else { continue }
                switch command {
                case "edit-z": item.isEnabled = editor.undoManager?.canUndo == true
                case "edit-Z": item.isEnabled = editor.undoManager?.canRedo == true
                case "edit-c", "edit-x": item.isEnabled = editor.selectedRange().length > 0
                default: item.isEnabled = true
                }
            }
        }
    }
    func menuDidClose(_ menu: NSMenu) {
        tracking = max(0, tracking - 1)
        if tracking == 0, let model = pending { pending = nil; update(model) }
    }
}

final class NativeMenuSession {
    private let lock: URL
    private let corePID: Int
    private let queue = DispatchQueue(label: "org.jellyfin.mpvshim.native-menu")
    private var timer: Timer?
    private var polling = false
    private var bar: PlayerMenuBar!
    private var settings: NativeSettings?
    private var media: NativeMedia?
    private let isHost: Bool
    private let updates: ((String) -> [String: Any]?)?
    var isTracking: Bool { bar.isTracking }

    init(lock: URL, corePID: Int, isHost: Bool = true,
         updates: ((String) -> [String: Any]?)? = nil, quit: @escaping () -> Void) {
        self.lock = lock
        self.corePID = corePID
        self.isHost = isHost
        self.updates = updates
        if isHost {
            media = NativeMedia { [weak self] command in
                self?.request(command) { [weak self] _ in self?.refresh() }
            }
        }
        bar = PlayerMenuBar(perform: { [weak self] command in
            if command == "settings" { self?.openSettings(); return }
            if command == "updates", let updates = self?.updates { _ = updates("updates-check"); return }
            self?.request(command) { result in
                if result?["ok"] as? Bool != true { NSSound.beep() }
                self?.refresh()
            }
        }, quit: quit)
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        refresh()
    }

    deinit { timer?.invalidate() }

    func openSettings() {
        if !isHost {
            if let host = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_HOST_PID"].flatMap(Int32.init), host > 1 { kill(host, SIGURG) }
            return
        }
        if settings == nil {
            settings = NativeSettings(request: { [weak self] command, completion in
                self?.request(command, completion: completion)
            })
        }
        settings?.open()
    }

    func closePlayerWindow() { request("close") { _ in } }

    private func refresh() {
        guard !polling else { return }
        polling = true
        request("state") { [weak self] result in
            guard let self = self else { return }
            self.polling = false
            if var result = result, result["ready"] as? Bool == true {
                self.media?.update(result.removeValue(forKey: "now_playing") as? [String: Any] ?? [:])
                self.bar.update(result)
            }
            else { self.bar.unavailable() }
        }
    }

    private func request(_ command: String, completion: @escaping ([String: Any]?) -> Void) {
        if command.hasPrefix("updates-"), let updates = updates { completion(updates(command)); return }
        guard let text = try? String(contentsOf: lock, encoding: .utf8) else { completion(nil); return }
        let lines = text.components(separatedBy: .newlines)
        guard lines.count >= 3, let port = UInt16(lines[0]), let endpoint = NWEndpoint.Port(rawValue: port),
              let identityData = lines[2].data(using: .utf8),
              let identity = try? JSONSerialization.jsonObject(with: identityData) as? [String: Any],
              identity["pid"] as? Int == corePID,
              let payload = try? JSONSerialization.data(withJSONObject: ["command": command]) else { completion(nil); return }
        let connection = NWConnection(host: "127.0.0.1", port: endpoint, using: .tcp)
        var received = Data()
        var finished = false
        func finish(_ result: [String: Any]?) {
            guard !finished else { return }
            finished = true
            connection.stateUpdateHandler = nil
            connection.cancel()
            RunLoop.main.perform(inModes: [.common]) { completion(result) }
        }
        func receive() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { data, _, closed, error in
                if let data = data { received.append(data) }
                if received.count > 262144 { finish(nil); return }
                if received.last == 10 {
                    guard received.starts(with: Data("JMS1".utf8)) else { finish(nil); return }
                    finish((try? JSONSerialization.jsonObject(with: Data(received.dropFirst(4)))) as? [String: Any])
                } else if closed || error != nil { finish(nil) }
                else { receive() }
            }
        }
        connection.stateUpdateHandler = { state in
            if case .ready = state {
                var data = Data(("JMS1" + lines[1] + " MENU ").utf8)
                data.append(payload)
                data.append(10)
                connection.send(content: data, completion: .contentProcessed { error in
                    if error != nil { finish(nil) } else { receive() }
                })
            } else if case .failed = state { finish(nil) }
        }
        connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + 3) { finish(nil) }
    }
}

private var playerMenuSession: NativeMenuSession?

@_cdecl("JellyfinInstallNativeMenus")
func installPlayerNativeMenus() {
    guard playerMenuSession == nil else { return }
    let env = ProcessInfo.processInfo.environment
    guard let path = env["JELLYFIN_PLAYER_MENU_LOCK"],
          let pid = env["JELLYFIN_PLAYER_CORE_PID"].flatMap(Int.init),
          let host = env["JELLYFIN_PLAYER_HOST_PID"].flatMap(Int32.init), host > 1 else { return }
    playerMenuSession = NativeMenuSession(lock: URL(fileURLWithPath: path), corePID: pid, isHost: false) { kill(host, SIGTERM) }
}

@_cdecl("JellyfinClosePlayerWindow")
func closePlayerWindow() { playerMenuSession?.closePlayerWindow() }
