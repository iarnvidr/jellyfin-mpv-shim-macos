import AppKit

@main
struct NemotronMacAudit {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        
        var results: [[String: Any]] = []
        var allPassed = true
        let outputPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "/tmp/nemotron-mac-audit.json"
        
        func writeReport() {
            let jsonData = try! JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted, .sortedKeys])
            try! jsonData.write(to: URL(fileURLWithPath: outputPath))
        }
        
        func record(_ name: String, _ pass: Bool, _ detail: String) {
            let entry = ["name": name, "pass": pass, "detail": detail] as [String: Any]
            results.append(entry)
            if !pass { allPassed = false }
            let status = pass ? "PASS" : "FAIL"
            print("\(status): \(name) - \(detail)")
            fflush(stdout)
            writeReport()
        }
        
        var transportLog: [String] = []
        var serverState = [
            "browser_fullscreen": false,
            "fullscreen": false,
            "ui_scale": 1.5 as Any,
            "enabled": true
        ]
        
        func mockTransport(_ command: String, _ completion: @escaping ([String: Any]?) -> Void) {
            transportLog.append(command)
            if command == "settings-state" {
                let fields: [[String: Any]] = [
                    ["key": "enabled", "title": "Enabled", "kind": "bool", "value": serverState["enabled"]!, "nullable": false],
                    ["key": "speed", "title": "Speed", "kind": "float", "value": 1.25, "nullable": false],
                    ["key": "fullscreen", "title": "Playback Fullscreen", "kind": "bool", "value": serverState["fullscreen"]!, "nullable": false],
                    ["key": "browser_fullscreen", "title": "Fullscreen Library Browser", "kind": "bool", "value": serverState["browser_fullscreen"]!, "nullable": false],
                    ["key": "ui_scale", "title": "Interface Scale", "kind": "float", "value": serverState["ui_scale"]!, "nullable": true],
                    ["key": "sync_path", "title": "Download Folder", "kind": "directory", "value": "/downloads", "nullable": true]
                ]
                completion(["tabs": [["id": "general", "title": "General", "groups": [["title": "Player", "fields": fields]]]]])
            } else if command == "updates-state" {
                completion(["ok": true, "checks": true, "downloads": false, "allowsDownloads": true, "canCheck": true, "version": "0.2.9", "lastCheck": "Never"])
            } else if command.hasPrefix("settings-set:") {
                let json = command.dropFirst("settings-set:".count)
                if let data = json.data(using: .utf8),
                   let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let key = dict["key"] as? String {
                    let value = dict["value"]
                    if key == "fullscreen" { serverState["fullscreen"] = value }
                    else if key == "browser_fullscreen" { serverState["browser_fullscreen"] = value }
                    else if key == "ui_scale" { serverState["ui_scale"] = value ?? NSNull() }
                    else if key == "enabled" { serverState["enabled"] = value }
                    completion(["ok": true, "restart": key == "ui_scale"])
                } else { completion(["ok": false, "error": "bad payload"]) }
            } else if command == "settings-relocation-state" {
                completion(["ok": true, "busy": false, "message": "Moved"])
            } else {
                completion(["ok": true])
            }
        }
        
        let prefs = NativeSettings(request: mockTransport)
        prefs.open()
        
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.5))
        
        func controls(in view: NSView) -> [NSControl] {
            if let c = view as? NSControl { return [c] }
            return view.subviews.flatMap(controls)
        }
        
        // CASE 1
        record("bool_checkbox_json_bool", false, "START")
        let allControls = controls(in: prefs.window!.contentView!)
        if let checkbox = allControls.first(where: { $0.identifier?.rawValue == "enabled" }) as? NSButton {
            prefs.window?.makeFirstResponder(checkbox)
            checkbox.performClick(nil)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.2))
            let lastCommand = transportLog.last ?? ""
            if lastCommand.hasPrefix("settings-set:"),
               let data = lastCommand.dropFirst("settings-set:".count).data(using: .utf8),
               let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let key = dict["key"] as? String,
               let value = dict["value"] {
                let isTrueBool = key == "enabled" && value is Bool && value as! Bool == false
                record("bool_checkbox_json_bool", isTrueBool, "sent \(key)=\(value) type=\(type(of: value))")
            } else {
                record("bool_checkbox_json_bool", false, "no settings-set command: \(lastCommand)")
            }
        } else {
            record("bool_checkbox_json_bool", false, "enabled checkbox not found")
        }
        
        // CASE 2
        record("nullable_cleared_json_null", false, "START")
        if let textField = allControls.first(where: { $0.identifier?.rawValue == "ui_scale" }) as? NSTextField {
            textField.stringValue = ""
            prefs.window?.makeFirstResponder(textField)
            prefs.window?.makeFirstResponder(nil)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.2))
            let lastCommand = transportLog.last ?? ""
            if lastCommand.hasPrefix("settings-set:"),
               let data = lastCommand.dropFirst("settings-set:".count).data(using: .utf8),
               let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let key = dict["key"] as? String,
               key == "ui_scale" {
                let isNull = dict["value"] is NSNull
                record("nullable_cleared_json_null", isNull, "sent \(key)=\(dict["value"] as Any) type=\(type(of: dict["value"]))")
            } else {
                record("nullable_cleared_json_null", false, "no settings-set for ui_scale: \(lastCommand)")
            }
        } else {
            record("nullable_cleared_json_null", false, "ui_scale text field not found")
        }
        
        // CASE 3
        record("fullscreen_conditional_initial", false, "START")
        let fsCheckbox = allControls.first(where: { $0.identifier?.rawValue == "fullscreen" }) as? NSButton
        let bfsCheckbox = allControls.first(where: { $0.identifier?.rawValue == "browser_fullscreen" }) as? NSButton
        
        if let fs = fsCheckbox, let bfs = bfsCheckbox {
            let pass = fs.isEnabled && bfs.state == .off
            record("fullscreen_conditional_initial", pass, "fullscreen enabled=\(fs.isEnabled), browser_fullscreen=\(bfs.state == .on)")
            
            record("fullscreen_conditional_disabled", false, "START")
            bfs.performClick(nil)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.3))
            let updatedControls = controls(in: prefs.window!.contentView!)
            let fs2 = updatedControls.first(where: { $0.identifier?.rawValue == "fullscreen" }) as? NSButton
            if let fs2 = fs2 {
                let pass = !fs2.isEnabled
                record("fullscreen_conditional_disabled", pass, "fullscreen enabled=\(fs2.isEnabled) after browser_fullscreen=on")
            } else {
                record("fullscreen_conditional_disabled", false, "fullscreen checkbox missing after rebuild")
            }
            
            record("fullscreen_conditional_reenabled", false, "START")
            let bfs2 = updatedControls.first(where: { $0.identifier?.rawValue == "browser_fullscreen" }) as? NSButton
            bfs2?.performClick(nil)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.3))
            let finalControls = controls(in: prefs.window!.contentView!)
            let fs3 = finalControls.first(where: { $0.identifier?.rawValue == "fullscreen" }) as? NSButton
            if let fs3 = fs3 {
                let pass = fs3.isEnabled
                record("fullscreen_conditional_reenabled", pass, "fullscreen enabled=\(fs3.isEnabled) after browser_fullscreen=off")
            } else {
                record("fullscreen_conditional_reenabled", false, "fullscreen checkbox missing after second rebuild")
            }
        } else {
            record("fullscreen_conditional_initial", false, "checkboxes not found")
            record("fullscreen_conditional_disabled", false, "skipped")
            record("fullscreen_conditional_reenabled", false, "skipped")
        }
        
        // CASE 4
        record("updates_tab_survives_rebuild", false, "START")
        if let folderBtn = allControls.first(where: { $0.identifier?.rawValue == "sync_path" }) as? NSButton {
            let tabViews = prefs.window!.contentView!.subviews.flatMap { $0.subviews }.compactMap { $0 as? NSTabView }
            if let tabs = tabViews.first {
                tabs.selectTabViewItem(withIdentifier: "updates")
                RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
                let before = tabs.selectedTabViewItem?.identifier as? String
                prefs.window?.makeFirstResponder(folderBtn)
                folderBtn.performClick(nil)
                RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.5))
                let after = tabs.selectedTabViewItem?.identifier as? String
                let survived = (before == "updates" && after == "updates")
                record("updates_tab_survives_rebuild", survived, "before=\(before ?? "nil"), after=\(after ?? "nil")")
            } else {
                record("updates_tab_survives_rebuild", false, "NSTabView not found")
            }
        } else {
            record("updates_tab_survives_rebuild", false, "sync_path button not found")
        }
        
        // CASE 5
        record("edit_menu_follows_focus", false, "START")
        if let textField = allControls.first(where: { $0.identifier?.rawValue == "speed" }) as? NSTextField {
            textField.stringValue = "1.5"
            textField.selectedRange = NSRange(location: 0, length: 1)
            prefs.window?.makeFirstResponder(textField)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
            let hasSelection = textField.selectedRange.length > 0
            let cutEnabled = hasSelection
            let pasteEnabled = NSPasteboard.general.string(forType: .string) != nil
            prefs.window?.makeFirstResponder(nil)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
            let pass = hasSelection && prefs.window?.firstResponder !== textField
            record("edit_menu_follows_focus", pass, "firstResponder=\(prefs.window?.firstResponder == textField), selection=\(hasSelection), cut=\(cutEnabled), paste=\(pasteEnabled)")
        } else {
            record("edit_menu_follows_focus", false, "speed text field not found")
        }
        
        print("Report written to \(outputPath)")
        print("SUMMARY: \(results.filter { $0["pass"] as! Bool }.count)/\(results.count) passed")
        fflush(stdout)
        exit(allPassed ? 0 : 1)
    }
}
