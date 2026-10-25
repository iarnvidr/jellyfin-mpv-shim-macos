import AppKit
import MediaPlayer

@main
struct VerifyNativeMenus {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        var commands: [String] = []
        var quit = false
        let bar = PlayerMenuBar(perform: { commands.append($0) }, quit: { quit = true })
        let model: [String: Any] = [
            "application": [["title": "Settings…", "command": "settings", "enabled": true, "key": ","]],
            "menus": [
                ["title": "Playback", "items": [["title": "Pause", "command": "7:pause", "enabled": true, "key": "p"]]],
                ["title": "Audio", "items": [["title": "English", "command": "7:set-audio:2", "enabled": true, "checked": true]]]
            ]]
        bar.update(model)
        app.mainMenu = NSMenu()
        bar.update(model)
        // mpv may install its stock menu after AppKit's launch notification.
        // Recover even though the player state itself has not changed.
        let menu = app.mainMenu!
        precondition(menu.items.dropFirst().map(\.title) == ["Playback", "Audio"])
        let playback = menu.item(withTitle: "Playback")!.submenu!
        playback.performActionForItem(at: 0)
        precondition(commands == ["7:pause"])
        let audio = menu.item(withTitle: "Audio")!.submenu!.items[0]
        precondition(audio.state == .on)
        let settings = menu.items[0].submenu!.item(withTitle: "Settings…")!
        precondition(settings.keyEquivalent == "," && settings.keyEquivalentModifierMask == .command)
        menu.items[0].submenu!.performActionForItem(at: menu.items[0].submenu!.index(of: settings))
        precondition(commands.last == "settings")
        bar.menuWillOpen(playback)
        bar.update(["application": [], "menus": [["title": "Playback", "items": [["title": "Play", "enabled": false]]]]])
        precondition(app.mainMenu === menu, "do not replace a menu while it is tracking")
        bar.menuDidClose(playback)
        precondition(app.mainMenu!.item(withTitle: "Playback")!.submenu!.items[0].title == "Play")
        let application = app.mainMenu!.items[0].submenu!
        application.performActionForItem(at: application.numberOfItems - 1)
        precondition(quit)
        var requests: [String] = []
        let preferences = NativeSettings { command, completion in
            requests.append(command)
            if command == "settings-state" {
                completion(["tabs": [["id": "general", "title": "General", "groups": [[
                    "title": "Player", "fields": [
                        ["key": "enabled", "title": "Enabled", "kind": "bool", "value": true],
                        ["key": "speed", "title": "Speed", "kind": "float", "value": 1.25],
                        ["key": "choice", "title": "Choice", "kind": "str", "value": "b", "options": [["A", "a"], ["B", "b"]]]]]]]]])
            } else { completion(["ok": true]) }
        }
        preferences.open()
        func controls(_ view: NSView) -> [NSControl] {
            (view as? NSControl).map { [$0] } ?? view.subviews.flatMap(controls)
        }
        let nativeControls = controls(preferences.window!.contentView!)
        let checkbox = nativeControls.first { $0.identifier?.rawValue == "enabled" } as! NSButton
        let popup = nativeControls.first { $0.identifier?.rawValue == "choice" } as! NSPopUpButton
        let text = nativeControls.first { $0.identifier?.rawValue == "speed" } as! NSTextField
        precondition(popup.titleOfSelectedItem == "B" && text.stringValue == "1.25")
        checkbox.performClick(nil)
        precondition(requests.last!.hasPrefix("settings-set:"))
        precondition(preferences.window?.windowController === preferences)
        preferences.close()
        let icon = NSImage(size: NSSize(width: 64, height: 64))
        icon.lockFocus()
        NSColor.purple.setFill()
        NSRect(x: 0, y: 0, width: 64, height: 64).fill()
        icon.unlockFocus()
        var systemCommands: [String] = []
        let media = NativeMedia(icon: icon) { systemCommands.append($0) }
        media.update(["active": true, "epoch": "7", "title": "Monk", "duration": 120.0,
                      "position": 30.0, "rate": 1.0, "paused": false,
                      "commands": ["play": "7:system-play", "pause": "7:system-pause"]])
        let info = MPNowPlayingInfoCenter.default().nowPlayingInfo!
        precondition(info[MPMediaItemPropertyTitle] as? String == "Monk")
        let artwork = info[MPMediaItemPropertyArtwork] as! MPMediaItemArtwork
        precondition(artwork.image(at: icon.size)?.tiffRepresentation == icon.tiffRepresentation)
        precondition(media.dispatch("pause") == .success && systemCommands.last == "7:system-pause")
        precondition(media.dispatch("seek", position: 40) == .success && systemCommands.last == "7:system-seek:40.0")
        precondition(media.dispatch("seek", position: 121) == .commandFailed)
        media.update(["active": false])
        precondition(MPNowPlayingInfoCenter.default().nowPlayingInfo == nil)
        precondition(media.dispatch("play") == .commandFailed)
        print("Native Now Playing: supplied artwork, real title, system commands, seek bounds and stop cleanup passed")
        print("Native Settings: native controls, persisted values, enum selection and save transport passed")
        print("Native AppKit menus: actions, shortcuts, selection and tracking passed")
    }
}
