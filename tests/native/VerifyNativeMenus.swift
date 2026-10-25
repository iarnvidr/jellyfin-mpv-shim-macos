import AppKit

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
        print("Native AppKit menus: actions, shortcuts, selection and tracking passed")
    }
}
