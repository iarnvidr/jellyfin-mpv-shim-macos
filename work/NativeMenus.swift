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
    private let diagnostics: MenuStateDiagnostics
    private let updates: ((String) -> [String: Any]?)?
    var isTracking: Bool { bar.isTracking }

    init(lock: URL, corePID: Int, isHost: Bool = true, sessionID: String,
         updates: ((String) -> [String: Any]?)? = nil, quit: @escaping () -> Void) {
        self.lock = lock
        self.corePID = corePID
        self.isHost = isHost
        self.diagnostics = MenuStateDiagnostics(role: isHost ? "host" : "engine", corePID: corePID, sessionID: sessionID)
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
        if settings?.window?.isVisible != true { diagnostics.freeze() }
        if settings == nil {
            settings = NativeSettings(copyDiagnostics: { [weak self] in self?.diagnostics.copyFrozen() }, request: { [weak self] command, completion in
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
    playerMenuSession = NativeMenuSession(lock: URL(fileURLWithPath: path), corePID: pid, isHost: false, sessionID: env["JELLYFIN_PLAYER_SESSION_ID"] ?? "missing") { kill(host, SIGTERM) }
}

@_cdecl("JellyfinClosePlayerWindow")
func closePlayerWindow() { playerMenuSession?.closePlayerWindow() }

// Local, bounded observations only. Never changes AppKit presentation or activation.
final class MenuStateDiagnostics {
    private let role: String
    private let identity: [String: Any]
    private let directory: URL
    private var storageSafe = false
    private let io = DispatchQueue(label: "org.jellyfin.mpvshim.menu-state")
    private var history: [[String: Any]] = []
    private var initial: [String: Any]?
    private var lastState = Data()
    private var total = 0
    private var lastPersistedMonotonic = -Double.infinity
    private var timer: Timer?
    private var observation: NSKeyValueObservation?
    private var notifications: [NSObjectProtocol] = []
    private var frozen = ""
    private let writeLock = NSLock()
    private var writeInFlight = false
    private var pendingWrite: (Data, URL)?
    private let limit = 16

    init(role: String, corePID: Int, sessionID: String) {
        self.role = role
        let env = ProcessInfo.processInfo.environment
        let pid = Int(ProcessInfo.processInfo.processIdentifier)
        identity = ["role": role, "pid": pid, "hostPID": role == "host" ? pid : (Int(env["JELLYFIN_PLAYER_HOST_PID"] ?? "") ?? 0),
                    "corePID": corePID, "sessionID": sessionID,
                    "processLaunchTime": NSRunningApplication.current.launchDate?.timeIntervalSince1970 ?? 0,
                    "roleVersion": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"]
        directory = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/Jellyfin Player/menu-state", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        if let attributes = try? FileManager.default.attributesOfItem(atPath: directory.path),
           attributes[.type] as? FileAttributeType == .typeDirectory,
           (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == geteuid() {
            try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
            storageSafe = true
        }
        sample(reason: "initial")
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.sample(reason: "sample") }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        for name in [NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification,
                     NSApplication.didChangeScreenParametersNotification, NSWindow.didBecomeKeyNotification,
                     NSWindow.didEnterFullScreenNotification, NSWindow.didExitFullScreenNotification] {
            notifications.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.sample(reason: "notification")
            })
        }
        observation = NSApp.observe(\.currentSystemPresentationOptions, options: [.new]) { [weak self] _, _ in
            if Thread.isMainThread { self?.sample(reason: "effectivePresentation") }
            else { DispatchQueue.main.async { self?.sample(reason: "effectivePresentation") } }
        }
    }
    deinit { timer?.invalidate(); notifications.forEach { NotificationCenter.default.removeObserver($0) } }

    private func rect(_ r: NSRect) -> [Double] { [r.origin.x, r.origin.y, r.width, r.height] }
    private func preference(_ key: String) -> [String: Any] {
        guard let value = CFPreferencesCopyValue(key as CFString, kCFPreferencesAnyApplication,
                                                kCFPreferencesCurrentUser, kCFPreferencesCurrentHost)
                ?? CFPreferencesCopyValue(key as CFString, kCFPreferencesAnyApplication,
                                          kCFPreferencesCurrentUser, kCFPreferencesAnyHost) else { return ["type": "missing"] }
        if CFGetTypeID(value) == CFBooleanGetTypeID() { return ["type": "boolean", "value": (value as! NSNumber).boolValue] }
        if CFGetTypeID(value) == CFNumberGetTypeID() { return ["type": "number", "value": (value as! NSNumber).doubleValue] }
        return ["type": "unsupported"]
    }
    private func osBuild() -> String {
        var size = 0
        guard sysctlbyname("kern.osversion", nil, &size, nil, 0) == 0, size > 0, size < 64 else { return "unavailable" }
        var bytes = [CChar](repeating: 0, count: size)
        guard sysctlbyname("kern.osversion", &bytes, &size, nil, 0) == 0 else { return "unavailable" }
        let value = String(cString: bytes)
        return value.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == ".") } ? value : "unavailable"
    }
    private func state() -> [String: Any] {
        let os = ProcessInfo.processInfo.operatingSystemVersion
        let windows = NSApp.windows.sorted { a, b in
            let x = (a.isKeyWindow ? 4 : 0) + (a.isVisible ? 2 : 0) + (a.isMainWindow ? 1 : 0)
            let y = (b.isKeyWindow ? 4 : 0) + (b.isVisible ? 2 : 0) + (b.isMainWindow ? 1 : 0)
            return x == y ? a.windowNumber < b.windowNumber : x > y
        }.prefix(8).map { w -> [String: Any] in
            ["number": w.windowNumber, "frame": rect(w.frame), "styleMask": w.styleMask.rawValue,
             "screenDisplayID": (w.screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value ?? 0,
             "level": w.level.rawValue, "onActiveSpace": w.isOnActiveSpace, "visible": w.isVisible,
             "key": w.isKeyWindow, "main": w.isMainWindow, "miniaturized": w.isMiniaturized, "zoomed": w.isZoomed]
        }
        let screens = NSScreen.screens.prefix(8).map { s -> [String: Any] in
            let a = s.safeAreaInsets
            return ["displayID": (s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value ?? 0,
                    "frame": rect(s.frame), "visibleFrame": rect(s.visibleFrame), "scale": s.backingScaleFactor,
                    "safeArea": [a.top, a.left, a.bottom, a.right]]
        }
        let mouse = NSEvent.mouseLocation
        return ["requestedPresentation": NSApp.presentationOptions.rawValue,
                "effectivePresentation": NSApp.currentSystemPresentationOptions.rawValue,
                "menuBarVisibleReported": NSMenu.menuBarVisible(), "mainMenuItemCount": NSApp.mainMenu?.numberOfItems ?? 0,
                "activationPolicy": NSApp.activationPolicy().rawValue, "active": NSApp.isActive, "hidden": NSApp.isHidden,
                "frontmostPID": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0,
                "osVersion": [os.majorVersion, os.minorVersion, os.patchVersion], "osBuild": osBuild(),
                "engineProperties": ["status": "unavailable"],
                "windows": windows, "windowsOmitted": max(0, NSApp.windows.count - 8),
                "screens": screens, "screensOmitted": max(0, NSScreen.screens.count - 8),
                "mouse": [mouse.x, mouse.y],
                "preferences": ["_HIHideMenuBar": preference("_HIHideMenuBar"),
                                "AppleMenuBarVisibleInFullscreen": preference("AppleMenuBarVisibleInFullscreen")]]
    }
    private func document(at time: Double) -> [String: Any] {
        ["schema": 1, "identity": identity, "lastObservedMonotonic": time,
         "history": history, "initial": initial ?? [:], "totalTransitions": total]
    }
    func sample(reason: String) {
        precondition(Thread.isMainThread)
        let now = ProcessInfo.processInfo.systemUptime
        let current = state()
        // Mouse location belongs in observations but must not turn pointer motion into a transition log.
        var semantic = current
        semantic.removeValue(forKey: "mouse")
        let encoded = (try? JSONSerialization.data(withJSONObject: semantic, options: [.sortedKeys])) ?? Data()
        let changed = encoded != lastState
        if changed {
            let entry: [String: Any] = ["monotonic": now, "wallTime": Date().timeIntervalSince1970,
                                        "reason": reason, "state": current]
            if initial == nil { initial = entry }
            history.append(entry)
            if history.count > limit { history.removeFirst(history.count - limit) }
            total += 1
            lastState = encoded
        }
        // Persist transitions immediately, but idle heartbeat only every 10 seconds.
        guard storageSafe, changed || now - lastPersistedMonotonic >= 10 else { return }
        guard let data = try? JSONSerialization.data(withJSONObject: document(at: now), options: [.sortedKeys]), data.count <= 262144 else { return }
        lastPersistedMonotonic = now
        let url = directory.appendingPathComponent(role + ".json")
        writeLock.lock()
        if writeInFlight { pendingWrite = (data, url); writeLock.unlock(); return }
        writeInFlight = true
        writeLock.unlock()
        enqueueWrite(data, url)
    }
    private func enqueueWrite(_ data: Data, _ url: URL) {
        io.async {
            defer {
                self.writeLock.lock()
                let next = self.pendingWrite
                self.pendingWrite = nil
                if next == nil { self.writeInFlight = false }
                self.writeLock.unlock()
                if let next = next { self.enqueueWrite(next.0, next.1) }
            }
            do {
                // Create with owner-only permissions BEFORE writing any bytes; rename atomically.
                let temporary = url.appendingPathExtension("tmp")
                let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_NOFOLLOW, 0o600)
                guard fd >= 0 else { return }
                guard flock(fd, LOCK_EX | LOCK_NB) == 0, fchmod(fd, 0o600) == 0,
                      ftruncate(fd, 0) == 0 else { Darwin.close(fd); return }
                let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
                do {
                    try handle.write(contentsOf: data)
                    if rename(temporary.path, url.path) != 0 { unlink(temporary.path) }
                    try handle.close()
                } catch { try? handle.close(); unlink(temporary.path) }
            } catch { /* No arbitrary error/path strings are collected. */ }
        }
    }

    private func readPeer(_ url: URL) -> Data? {
        guard storageSafe else { return nil }
        let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard fd >= 0 else { return nil }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_uid == geteuid(), info.st_size <= 262144 else { return nil }
        guard let data = try? handle.read(upToCount: 262145), data.count <= 262144 else { return nil }
        return data
    }
    // Reject, rather than forward, unknown peer fields. No arbitrary strings can enter a copied report.
    private func validPeer(_ value: Any, kind: String) -> Bool {
        let keys: [String: Set<String>] = [
            "document": ["schema", "identity", "lastObservedMonotonic", "history", "initial", "totalTransitions"],
            "identity": ["role", "pid", "hostPID", "corePID", "sessionID", "processLaunchTime", "roleVersion"],
            "entry": ["monotonic", "wallTime", "reason", "state"],
            "state": ["requestedPresentation", "effectivePresentation", "menuBarVisibleReported", "mainMenuItemCount", "activationPolicy", "active", "hidden", "frontmostPID", "osVersion", "osBuild", "engineProperties", "windows", "windowsOmitted", "screens", "screensOmitted", "mouse", "preferences"],
            "window": ["number", "frame", "styleMask", "screenDisplayID", "level", "onActiveSpace", "visible", "key", "main", "miniaturized", "zoomed"],
            "screen": ["displayID", "frame", "visibleFrame", "scale", "safeArea"],
            "preferences": ["_HIHideMenuBar", "AppleMenuBarVisibleInFullscreen"],
            "engineProperties": ["status"]]
        guard let object = value as? [String: Any] else { return false }
        if kind == "preference" {
            guard let type = object["type"] as? String, ["missing", "unsupported", "boolean", "number"].contains(type),
                  Set(object.keys) == ((type == "boolean" || type == "number") ? Set(["type", "value"]) : Set(["type"])) else { return false }
            guard let number = object["value"] as? NSNumber else { return object["value"] == nil }
            return number.doubleValue.isFinite && ((CFGetTypeID(number) == CFBooleanGetTypeID()) == (type == "boolean"))
        }
        guard let allowed = keys[kind], Set(object.keys) == allowed else { return false }
        if kind == "document", object["schema"] as? Int != 1 { return false }
        if kind == "identity" {
            for key in ["pid", "hostPID", "corePID"] {
                guard let n = object[key] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
                      n.doubleValue.rounded(.towardZero) == n.doubleValue,
                      n.doubleValue >= 2, n.doubleValue <= Double(Int32.max) else { return false }
            }
        }
        for (key, item) in object {
            let nested = ["identity": "identity", "initial": "entry", "state": "state", "preferences": "preferences", "engineProperties": "engineProperties", "_HIHideMenuBar": "preference", "AppleMenuBarVisibleInFullscreen": "preference"]
            if let child = nested[key] { if !validPeer(item, kind: child) { return false }; continue }
            if ["history", "windows", "screens"].contains(key) {
                guard let list = item as? [Any], list.count <= (key == "history" ? 16 : 8) else { return false }
                let child = key == "history" ? "entry" : (key == "windows" ? "window" : "screen")
                if !list.allSatisfy({ validPeer($0, kind: child) }) { return false }; continue
            }
            let stringKeys: Set<String> = ["role", "sessionID", "reason", "status", "roleVersion", "osBuild"]
            let arrayLengths = ["frame": 4, "visibleFrame": 4, "safeArea": 4, "mouse": 2, "osVersion": 3]
            let booleanKeys: Set<String> = ["menuBarVisibleReported", "active", "hidden", "onActiveSpace", "visible", "key", "main", "miniaturized", "zoomed"]
            if stringKeys.contains(key), !(item is String) { return false }
            if let count = arrayLengths[key] {
                guard let array = item as? [NSNumber], array.count == count,
                      array.allSatisfy({ $0.doubleValue.isFinite && CFGetTypeID($0) != CFBooleanGetTypeID() }) else { return false }
                continue
            }
            if let text = item as? String {
                switch key {
                case "role": if !["host", "engine"].contains(text) { return false }
                case "sessionID": if UUID(uuidString: text) == nil { return false }
                case "reason": if !["initial", "sample", "beforeSettings", "effectivePresentation", "notification"].contains(text) { return false }
                case "status": if text != "unavailable" { return false }
                case "roleVersion", "osBuild": if text.count > 64 || !text.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }) { return false }
                default: return false
                }
            } else if let number = item as? NSNumber {
                if !number.doubleValue.isFinite || ((CFGetTypeID(number) == CFBooleanGetTypeID()) != booleanKeys.contains(key)) { return false }
            } else { return false }
        }
        return true
    }

    // Called in the host BEFORE constructing or showing Settings, including direct SIGURG routes.
    func freeze() {
        precondition(Thread.isMainThread)
        sample(reason: "beforeSettings")
        let cutoff = ProcessInfo.processInfo.systemUptime
        var own = document(at: cutoff)
        let peerRole = role == "host" ? "engine" : "host"
        var peer: [String: Any] = ["status": "missing"]
        let url = directory.appendingPathComponent(peerRole + ".json")
        if FileManager.default.fileExists(atPath: url.path) { peer = ["status": "unreadableOrInvalid"] }
        if let data = readPeer(url),
           let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
           validPeer(value, kind: "document"),
           let id = value["identity"] as? [String: Any] {
            let same = ["sessionID", "hostPID", "corePID"].allSatisfy { String(describing: id[$0] ?? "") == String(describing: identity[$0] ?? "") }
            if same, UUID(uuidString: identity["sessionID"] as? String ?? "") != nil,
               id["role"] as? String == peerRole, let pid = id["pid"] as? Int, pid > 1 {
                let host = NSRunningApplication(processIdentifier: Int32(identity["hostPID"] as? Int ?? 0))
                let expected = peerRole == "engine" ? host?.bundleURL?.appendingPathComponent("Contents/Resources/mpv.app") : host?.bundleURL
                let application = NSRunningApplication(processIdentifier: Int32(pid))
                let launch = id["processLaunchTime"] as? Double ?? 0
                let matches = NSWorkspace.shared.runningApplications.filter { $0.bundleURL == expected }
                guard let expected = expected, application?.bundleURL == expected,
                      launch > 0, abs((application?.launchDate?.timeIntervalSince1970 ?? 0) - launch) < 0.01 else {
                    finishFreeze(own: own, peer: ["status": "processIdentityMismatch"], cutoff: cutoff); return
                }
                guard matches.count == 1 else {
                    finishFreeze(own: own, peer: ["status": "ambiguous", "candidatePIDs": matches.map { $0.processIdentifier }], cutoff: cutoff); return
                }
                let observed = value["lastObservedMonotonic"] as? Double ?? 0
                peer = ["status": kill(Int32(pid), 0) != 0 ? "exited" : (observed > cutoff ? "newerThanCutoff" : (cutoff - observed > 15 ? "stale" : "available")),
                        "ageSeconds": max(0, cutoff - observed), "document": value]
            } else { peer = ["status": "identityMismatch"] }
        }
        finishFreeze(own: own, peer: peer, cutoff: cutoff)
    }
    private func finishFreeze(own original: [String: Any], peer originalPeer: [String: Any], cutoff: Double) {
        var own = original
        var peer = originalPeer
        func bounded(_ source: [String: Any]) -> [String: Any] {
            var result = source
            let records = (source["history"] as? [[String: Any]] ?? []).filter { ($0["monotonic"] as? Double ?? .infinity) <= cutoff }
            result["history"] = Array(records.suffix(8))
            result["omittedTransitions"] = max(0, (source["totalTransitions"] as? Int ?? records.count) - min(8, records.count) - 1)
            return result
        }
        own = bounded(own)
        if let doc = peer["document"] as? [String: Any] {
            if let initial = doc["initial"] as? [String: Any],
               (initial["monotonic"] as? Double ?? .infinity) > cutoff {
                peer = ["status": "newerThanCutoff"]
            } else { peer["document"] = bounded(doc) }
        }
        var report: [String: Any] = ["schema": 1, "capture": "beforeSettings", "nonAtomic": true,
                                   "cutoffMonotonic": cutoff, "own": own, "peer": peer]
        // Whole valid JSON only: reduce history further if unusual display/window counts exceed the clipboard bound.
        for count in [8, 4, 1, 0] {
            func reduce(_ doc: inout [String: Any]) {
                let entries = doc["history"] as? [[String: Any]] ?? []
                doc["history"] = Array(entries.suffix(count))
                doc["clipboardOmittedTransitions"] = entries.count - min(count, entries.count)
            }
            var a = own; reduce(&a); report["own"] = a
            var b = peer
            if var doc = b["document"] as? [String: Any] { reduce(&doc); b["document"] = doc }
            report["peer"] = b
            if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), data.count <= 65536 {
                frozen = String(decoding: data, as: UTF8.self); return
            }
        }
        frozen = "{\"schema\":1,\"status\":\"reportTooLarge\"}"
    }
    func copyFrozen() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(frozen, forType: .string)
    }
}
