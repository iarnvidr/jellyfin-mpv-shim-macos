import AppKit

// AppKit controls provide native text editing, keyboard navigation, appearance
// and accessibility. The core remains the sole owner of preference validation.
final class NativeSettings: NSWindowController, NSTextFieldDelegate, NSWindowDelegate {
    typealias Transport = (String, @escaping ([String: Any]?) -> Void) -> Void
    private let request: Transport
    private let tabs = NSTabView()
    private let status = NSTextField(wrappingLabelWithString: "")
    private var fields: [String: [String: Any]] = [:]
    private var optionValues: [String: [Any]] = [:]
    private var editingMonitor: Any?

    init(request: @escaping Transport) {
        self.request = request
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 620),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Jellyfin Player Settings"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 600, height: 450)
        super.init(window: window)
        window.delegate = self
        let content = NSStackView(views: [tabs, status])
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
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    deinit { if let monitor = editingMonitor { NSEvent.removeMonitor(monitor) } }

    func open() {
        let alreadyOpen = window?.isVisible == true
        showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
        if alreadyOpen { return }
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
                    if !(control is NSButton) { row.addArrangedSubview(NSTextField(labelWithString: label)) }
                    row.addArrangedSubview(control)
                    control.widthAnchor.constraint(equalToConstant: 570).isActive = true
                    var note = field["note"] as? String ?? ""
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
        status.stringValue = "Changes are saved automatically."
        window?.recalculateKeyViewLoop()
        if let path = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_MENU_DIAGNOSTICS"] {
            let diagnostic: [String: Any] = ["native": true,
                "windowTitle": window?.title ?? "", "visible": window?.isVisible == true,
                "tabs": tabs.tabViewItems.map(\.label), "fields": fields.count]
            if let data = try? JSONSerialization.data(withJSONObject: diagnostic) {
                try? data.write(to: URL(fileURLWithPath: path).appendingPathComponent("settings.json"), options: .atomic)
            }
        }
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
        guard let data = try? JSONSerialization.data(withJSONObject: ["key": key, "value": value]),
              let json = String(data: data, encoding: .utf8) else { return }
        control.isEnabled = false
        request("settings-set:" + json) { [weak self, weak control] result in
            control?.isEnabled = true
            if result?["ok"] as? Bool == true {
                self?.status.stringValue = result?["restart"] as? Bool == true ? "Saved. Restart Jellyfin Player to apply this change." : "Saved."
            } else {
                self?.status.stringValue = result?["error"] as? String ?? "The setting could not be saved."
                NSSound.beep()
            }
        }
    }
}

private final class FlippedSettingsView: NSView {
    override var isFlipped: Bool { true }
}
