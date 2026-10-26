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

        func record(_ name: String, _ pass: Bool?, _ detail: String) {
            let entry = ["name": name, "pass": pass as Any, "detail": detail] as [String: Any]
            results.append(entry)
            if pass == false { allPassed = false }
            let status = pass == nil ? "STATUS" : (pass! ? "PASS" : "FAIL")
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
        var relocationBusy = false

        func mockTransport(_ command: String, _ completion: @escaping ([String: Any]?) -> Void) {
            transportLog.append(command)
            if command == "settings-state" {
                let bfs = serverState["browser_fullscreen"] as? Bool ?? false
                let fields: [[String: Any]] = [
                    ["key": "enabled", "title": "Enabled", "kind": "bool", "value": serverState["enabled"]!, "nullable": false, "enabled": true, "restart": false, "note": ""],
                    ["key": "speed", "title": "Speed", "kind": "float", "value": 1.25, "nullable": false, "enabled": true, "restart": false, "note": ""],
                    ["key": "fullscreen", "title": "Playback Fullscreen", "kind": "bool", "value": serverState["fullscreen"]!, "nullable": false, "enabled": !bfs, "restart": false, "note": ""],
                    ["key": "browser_fullscreen", "title": "Fullscreen Library Browser", "kind": "bool", "value": bfs, "nullable": false, "enabled": true, "restart": false, "note": ""],
                    ["key": "ui_scale", "title": "Interface Scale", "kind": "float", "value": serverState["ui_scale"]!, "nullable": true, "enabled": true, "restart": true, "note": "Requires restart"],
                    ["key": "sync_path", "title": "Download Folder", "kind": "directory", "value": "/downloads", "nullable": true, "enabled": true, "restart": false, "note": ""]
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
                    else if key == "sync_path" {
                        serverState["sync_path"] = value
                        relocationBusy = true
                        completion(["ok": true, "busy": true])
                        return
                    }
                    completion(["ok": true, "restart": key == "ui_scale"])
                } else { completion(["ok": false, "error": "bad payload"]) }
            } else if command == "settings-relocation-state" {
                if relocationBusy {
                    relocationBusy = false
                    completion(["ok": true, "busy": false, "message": "Moved"])
                } else {
                    completion(["ok": true, "busy": false, "message": "Moved"])
                }
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
        record("bool_checkbox_json_bool", nil, "START")
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
        record("nullable_cleared_json_null", nil, "START")
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
        record("fullscreen_conditional_initial", nil, "START")
        let fsCheckbox = allControls.first(where: { $0.identifier?.rawValue == "fullscreen" }) as? NSButton
        let bfsCheckbox = allControls.first(where: { $0.identifier?.rawValue == "browser_fullscreen" }) as? NSButton

        if let fs = fsCheckbox, let bfs = bfsCheckbox {
            let pass = fs.isEnabled && bfs.state == .off
            record("fullscreen_conditional_initial", pass, "fullscreen enabled=\(fs.isEnabled), browser_fullscreen=\(bfs.state == .on)")

            record("fullscreen_conditional_disabled", nil, "START")
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

            record("fullscreen_conditional_reenabled", nil, "START")
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

        // CASE 5 - SKIPPED: cannot access PlayerMenuBar from NativeSettings context to verify actual item.isEnabled
        record("edit_menu_follows_focus", nil, "START")
        record("edit_menu_follows_focus", nil, "SKIPPED: cannot access PlayerMenuBar menu item enablement from NativeSettings probe; would require cross-component fixture not available here")

        // CASE 4: updates tab survives relocation rebuild
        record("updates_tab_survives_rebuild", nil, "START")
        if let syncPathControl = allControls.first(where: { $0.identifier?.rawValue == "sync_path" }) as? NSButton {
            let startJson = try! JSONSerialization.data(withJSONObject: ["key": "sync_path", "value": "/new-downloads"], options: [.sortedKeys])
            let startJsonStr = String(data: startJson, encoding: .utf8)!
            record("updates_tab_survives_rebuild_start_json", nil, startJsonStr)

            if let tabsMirror = Mirror(reflecting: prefs).children.first(where: { $0.label == "tabs" }),
               let tabView = tabsMirror.value as? NSTabView {
                let updatesItem = tabView.tabViewItems.first { $0.identifier as? String == "updates" }
                if let updatesItem = updatesItem {
                    tabView.selectTabViewItem(updatesItem)
                    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))

                    prefs.save(syncPathControl, key: "sync_path", value: "/new-downloads")
                    RunLoop.current.run(until: Date(timeIntervalSinceNow: 1.2))

                    let stillSelected = tabView.selectedTabViewItem?.identifier as? String == "updates"
                    record("updates_tab_survives_rebuild", stillSelected, "Updates tab selected after rebuild: \(stillSelected)")
                } else {
                    record("updates_tab_survives_rebuild", false, "Updates tab not found")
                }
            } else {
                record("updates_tab_survives_rebuild", false, "tabs not accessible")
            }
        }

        print("Report written to \(outputPath)")
        let completed = results.filter { $0["pass"] as? Bool != nil }
        let passed = completed.filter { $0["pass"] as! Bool }.count
        print("SUMMARY: \(passed)/\(completed.count) completed passed")
        fflush(stdout)
        exit(allPassed ? 0 : 1)
    }
}
