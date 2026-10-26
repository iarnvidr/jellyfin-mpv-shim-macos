import AppKit

// AppKit controls provide native text editing, keyboard navigation, appearance
// and accessibility. The core remains the sole owner of preference validation.
final class NativeSettings: NSWindowController, NSTextFieldDelegate, NSWindowDelegate {
    typealias Transport = (String, @escaping ([String: Any]?) -> Void) -> Void
    private let request: Transport
    private let copyDiagnostics: () -> Void
    private let tabs = NSTabView()
    private let status = NSTextField(wrappingLabelWithString: "")
    private var fields: [String: [String: Any]] = [:]
    private var optionValues: [String: [Any]] = [:]
    private var editingMonitor: Any?
    private var updateState: [String: Any] = [:]
    private var updateTimer: Timer?
    private var updateChecks: NSButton?
    private var updateDownloads: NSButton?
    private var updateNow: NSButton?
    private var updateLastCheck: NSTextField?

    init(copyDiagnostics: @escaping () -> Void = {}, request: @escaping Transport) {
        self.copyDiagnostics = copyDiagnostics
        self.request = request
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 620),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Jellyfin Player Settings"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 600, height: 450)
        super.init(window: window)
        window.delegate = self
        let copy = NSButton(title: "Copy Diagnostics", target: self, action: #selector(copyLocalDiagnostics))
        copy.setAccessibilityIdentifier("copy-diagnostics")
        let content = NSStackView(views: [tabs, status, copy])
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 12
        content.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 20),
            content.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -20),
            content.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 20),
            content.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -20),
            tabs.widthAnchor.constraint(equalTo: content.widthAnchor),
            tabs.heightAnchor.constraint(greaterThanOrEqualToConstant: 300),
            status.heightAnchor.constraint(greaterThanOrEqualToConstant: 32)
        ])
        window.center()
        editingMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak window] event in
            guard event.window === window, event.modifierFlags.contains(.command),
                  let editor = window?.firstResponder as? NSTextView else { return event }
            let shift = event.modifierFlags.contains(.shift)
            let actions = ["x": "cut:", "c": "copy:", "v": "paste:", "a": "selectAll:", "z": shift ? "redo:" : "undo:"]
            if let action = actions[event.charactersIgnoringModifiers?.lowercased() ?? ""] {
                NSApp.sendAction(Selector(action), to: editor, from: nil)
                return nil
            }
            return event
        }
        let timer = Timer(timeInterval: 2, repeats: true) { [weak self] _ in
            guard let self = self, self.window?.isVisible == true else { return }
            self.request("updates-state") { [weak self] model in
                if let model = model, model["ok"] as? Bool == true { self?.buildUpdates(model) }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        updateTimer = timer
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    deinit {
        updateTimer?.invalidate()
        if let monitor = editingMonitor { NSEvent.removeMonitor(monitor) }
    }

    @objc private func copyLocalDiagnostics() {
        copyDiagnostics()
        status.stringValue = "Local diagnostics copied. No screenshots or server details are included."
    }

    func open() {
        let alreadyOpen = window?.isVisible == true
        showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        if alreadyOpen {
            request("updates-state") { [weak self] model in
                if let model = model, model["ok"] as? Bool == true { self?.buildUpdates(model) }
            }
            return
        }
        request("settings-state") { [weak self] model in
            guard let self = self else { return }
            guard let model = model, let sections = model["tabs"] as? [[String: Any]] else {
                self.status.stringValue = "Settings are unavailable while the player is starting."
                return
            }
            self.build(sections)
        }
    }

    private func build(_ sections: [[String: Any]]) {
        let selected = tabs.selectedTabViewItem?.identifier as? String
        tabs.tabViewItems.forEach { tabs.removeTabViewItem($0) }
        fields.removeAll()
        optionValues.removeAll()
        for section in sections {
            let item = NSTabViewItem(identifier: section["id"])
            item.label = section["title"] as? String ?? "Settings"
            let rows = NSStackView()
            rows.orientation = .vertical
            rows.alignment = .leading
            rows.spacing = 12
            rows.edgeInsets = NSEdgeInsets(top: 20, left: 16, bottom: 20, right: 16)
            for group in section["groups"] as? [[String: Any]] ?? [] {
                let heading = NSTextField(labelWithString: group["title"] as? String ?? "")
                heading.font = .boldSystemFont(ofSize: NSFont.systemFontSize)
                rows.addArrangedSubview(heading)
                for field in group["fields"] as? [[String: Any]] ?? [] {
                    guard let key = field["key"] as? String else { continue }
                    fields[key] = field
                    let label = field["title"] as? String ?? key
                    let options = field["options"] as? [[Any]] ?? []
                    let control: NSControl
                    if !options.isEmpty {
                        let popup = NSPopUpButton()
                        popup.addItems(withTitles: options.map { $0.first as? String ?? "" })
                        optionValues[key] = options.map { $0[1] }
                        if let index = options.firstIndex(where: { ($0[1] as? NSObject)?.isEqual(field["value"]) == true }) {
                            popup.selectItem(at: index)
                        }
                        popup.target = self
                        popup.action = #selector(changed(_:))
                        control = popup
                    } else if field["kind"] as? String == "directory" {
                        control = NSButton(title: "Move Downloads to Folder…", target: self, action: #selector(chooseFolder(_:)))
                    } else if field["kind"] as? String == "bool" {
                        let button = NSButton(checkboxWithTitle: label, target: self, action: #selector(changed(_:)))
                        button.state = field["value"] as? Bool == true ? .on : .off
                        control = button
                    } else {
                        let text = NSTextField()
                        let value = field["value"]
                        text.stringValue = value == nil || value is NSNull ? "" : String(describing: value!)
                        text.placeholderString = field["nullable"] as? Bool == true ? "Automatic" : nil
                        text.delegate = self
                        control = text
                    }
                    control.identifier = NSUserInterfaceItemIdentifier(key)
                    control.isEnabled = field["enabled"] as? Bool ?? true
                    control.setAccessibilityLabel(label)
                    control.toolTip = field["note"] as? String
                    let row = NSStackView()
                    row.orientation = .vertical
                    row.alignment = .leading
                    row.spacing = 4
                    if !(control is NSButton) || field["kind"] as? String == "directory" { row.addArrangedSubview(NSTextField(labelWithString: label)) }
                    row.addArrangedSubview(control)
                    control.widthAnchor.constraint(equalToConstant: 570).isActive = true
                    var note = field["note"] as? String ?? ""
                    if field["kind"] as? String == "directory" {
                        note = "Current folder: \(field["value"] as? String ?? "Automatic")\n" + note
                    }
                    if field["restart"] as? Bool == true { note += " Changes take effect after restarting Jellyfin Player." }
                    if !note.isEmpty {
                        let caption = NSTextField(wrappingLabelWithString: note)
                        caption.textColor = .secondaryLabelColor
                        caption.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
                        caption.widthAnchor.constraint(equalToConstant: 570).isActive = true
                        row.addArrangedSubview(caption)
                    }
                    rows.addArrangedSubview(row)
                }
            }
            let scroll = NSScrollView()
            scroll.hasVerticalScroller = true
            scroll.drawsBackground = false
            rows.translatesAutoresizingMaskIntoConstraints = false
            let flipped = FlippedSettingsView()
            flipped.addSubview(rows)
            rows.leadingAnchor.constraint(equalTo: flipped.leadingAnchor).isActive = true
            rows.topAnchor.constraint(equalTo: flipped.topAnchor).isActive = true
            rows.trailingAnchor.constraint(equalTo: flipped.trailingAnchor).isActive = true
            rows.bottomAnchor.constraint(equalTo: flipped.bottomAnchor).isActive = true
            flipped.translatesAutoresizingMaskIntoConstraints = false
            scroll.documentView = flipped
            flipped.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor).isActive = true
            item.view = scroll
            tabs.addTabViewItem(item)
        }
        if let selected = selected { tabs.selectTabViewItem(withIdentifier: selected) }
        request("updates-state") { [weak self] model in
            if let model = model, model["ok"] as? Bool == true { self?.buildUpdates(model) }
        }
        status.stringValue = "Changes are saved automatically."
        window?.recalculateKeyViewLoop()
        if let path = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_MENU_DIAGNOSTICS"] {
            let diagnostic: [String: Any] = ["native": true,
                "windowTitle": window?.title ?? "", "visible": window?.isVisible == true,
                "tabs": tabs.tabViewItems.map(\.label), "fields": fields.count,
                "fieldKeys": Array(fields.keys).sorted(), "updater": updateState]
            if let data = try? JSONSerialization.data(withJSONObject: diagnostic) {
                try? data.write(to: URL(fileURLWithPath: path).appendingPathComponent("settings.json"), options: .atomic)
            }
        }
    }

    private func buildUpdates(_ model: [String: Any]) {
        updateState = model
        if tabs.tabViewItems.contains(where: { $0.identifier as? String == "updates" }) {
            updateChecks?.state = model["checks"] as? Bool == true ? .on : .off
            updateDownloads?.state = model["downloads"] as? Bool == true ? .on : .off
            updateDownloads?.isEnabled = model["allowsDownloads"] as? Bool == true
            updateNow?.isEnabled = model["canCheck"] as? Bool == true
            updateLastCheck?.stringValue = "Last checked: \(model["lastCheck"] as? String ?? "Never")"
            return
        }
        let item = NSTabViewItem(identifier: "updates")
        item.label = "Updates"
        let version = NSTextField(labelWithString: "Jellyfin Player \(model["version"] as? String ?? "")")
        version.font = .boldSystemFont(ofSize: NSFont.systemFontSize)
        let checks = NSButton(checkboxWithTitle: "Automatically check for updates", target: self, action: #selector(updatePreference(_:)))
        checks.identifier = NSUserInterfaceItemIdentifier("checks")
        checks.state = model["checks"] as? Bool == true ? .on : .off
        let downloads = NSButton(checkboxWithTitle: "Automatically download and install updates", target: self, action: #selector(updatePreference(_:)))
        downloads.identifier = NSUserInterfaceItemIdentifier("downloads")
        downloads.state = model["downloads"] as? Bool == true ? .on : .off
        downloads.isEnabled = model["allowsDownloads"] as? Bool == true
        let check = NSButton(title: "Check for Updates…", target: self, action: #selector(checkForUpdates(_:)))
        check.isEnabled = model["canCheck"] as? Bool == true
        let last = NSTextField(labelWithString: "Last checked: \(model["lastCheck"] as? String ?? "Never")")
        last.textColor = .secondaryLabelColor
        updateChecks = checks
        updateDownloads = downloads
        updateNow = check
        updateLastCheck = last
        let rows = NSStackView(views: [version, checks, downloads, check, last])
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 16
        rows.translatesAutoresizingMaskIntoConstraints = false
        let view = NSView()
        view.addSubview(rows)
        NSLayoutConstraint.activate([
            rows.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            rows.topAnchor.constraint(equalTo: view.topAnchor, constant: 24),
            rows.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -20)
        ])
        item.view = view
        tabs.addTabViewItem(item)
    }

    @objc private func updatePreference(_ sender: NSButton) {
        guard let key = sender.identifier?.rawValue else { return }
        request("updates-\(key):\(sender.state == .on ? "on" : "off")") { [weak self] model in
            if let model = model, model["ok"] as? Bool == true { self?.buildUpdates(model) }
        }
    }

    @objc private func checkForUpdates(_ sender: NSButton) {
        request("updates-check") { _ in }
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        if let control = notification.object as? NSControl { changed(control) }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.makeFirstResponder(nil)
        return true
    }

    @objc private func changed(_ control: NSControl) {
        guard let key = control.identifier?.rawValue, let field = fields[key] else { return }
        let value: Any
        if let popup = control as? NSPopUpButton, let options = optionValues[key],
           options.indices.contains(popup.indexOfSelectedItem) { value = options[popup.indexOfSelectedItem] }
        else if let button = control as? NSButton { value = button.state == .on }
        else if let text = control as? NSTextField {
            value = text.stringValue.isEmpty && field["nullable"] as? Bool == true ? NSNull() : text.stringValue
        } else { return }
        save(control, key: key, value: value)
    }

    @objc private func chooseFolder(_ control: NSControl) {
        guard let window = window, let key = control.identifier?.rawValue else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Move Downloads"
        panel.message = "Existing downloads will move to the selected folder."
        panel.beginSheetModal(for: window) { [weak self, weak control] response in
            if response == .OK, let path = panel.url?.path, let control = control {
                self?.save(control, key: key, value: path)
            }
        }
    }

    private func save(_ control: NSControl, key: String, value: Any) {
        guard let data = try? JSONSerialization.data(withJSONObject: ["key": key, "value": value]),
              let json = String(data: data, encoding: .utf8) else { return }
        control.isEnabled = false
        request("settings-set:" + json) { [weak self, weak control] result in
            if result?["busy"] as? Bool == true {
                self?.status.stringValue = "Moving downloads…"
                self?.pollRelocation(control)
                return
            }
            control?.isEnabled = true
            if result?["ok"] as? Bool == true {
                self?.status.stringValue = result?["restart"] as? Bool == true ? "Saved. Restart Jellyfin Player to apply this change." : "Saved."
            } else {
                self?.status.stringValue = result?["error"] as? String ?? "The setting could not be saved."
                NSSound.beep()
            }
        }
    }

    private func pollRelocation(_ control: NSControl?) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self, weak control] in
            self?.request("settings-relocation-state") { [weak self, weak control] result in
                if result?["busy"] as? Bool == true { self?.pollRelocation(control); return }
                control?.isEnabled = true
                self?.status.stringValue = result?["message"] as? String ?? result?["error"] as? String ?? "Could not check the download move."
                if result?["ok"] as? Bool == true {
                    self?.request("settings-state") { [weak self] model in
                        if let tabs = model?["tabs"] as? [[String: Any]] { self?.build(tabs) }
                    }
                }
            }
        }
    }
}

private final class FlippedSettingsView: NSView {
    override var isFlipped: Bool { true }
}
