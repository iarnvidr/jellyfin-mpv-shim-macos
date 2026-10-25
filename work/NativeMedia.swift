import AppKit
import MediaPlayer

// System media ownership belongs to the outer Jellyfin app, not its engine.
// mpv embeds its own fallback artwork and cannot inherit the host's identity.
final class NativeMedia {
    private let send: (String) -> Void
    private let icon: NSImage
    private let center = MPNowPlayingInfoCenter.default()
    private var targets: [(MPRemoteCommand, Any)] = []
    private var commands: [String: String] = [:]
    private var epoch = ""
    private var duration = 0.0

    init(icon: NSImage? = nil, send: @escaping (String) -> Void) {
        self.send = send
        self.icon = icon ?? NSImage(contentsOf: Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/jellyfin.icns")) ?? NSApp.applicationIconImage
        let remote = MPRemoteCommandCenter.shared()
        for (command, verb) in [(remote.playCommand, "play"), (remote.pauseCommand, "pause"),
                                (remote.togglePlayPauseCommand, "toggle"), (remote.stopCommand, "stop"),
                                (remote.nextTrackCommand, "next"), (remote.previousTrackCommand, "previous"),
                                (remote.skipForwardCommand, "forward"), (remote.skipBackwardCommand, "back")] {
            command.isEnabled = false
            let target = command.addTarget { [weak self] _ in self?.systemCommand(verb) ?? .commandFailed }
            targets.append((command, target))
        }
        remote.skipForwardCommand.preferredIntervals = [10]
        remote.skipBackwardCommand.preferredIntervals = [10]
        remote.changePlaybackPositionCommand.isEnabled = false
        let target = remote.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            return self?.systemCommand("seek", position: event.positionTime) ?? .commandFailed
        }
        targets.append((remote.changePlaybackPositionCommand, target))
    }

    deinit {
        for (command, target) in targets { command.removeTarget(target) }
        center.nowPlayingInfo = nil
        center.playbackState = .stopped
    }

    private func systemCommand(_ verb: String, position: Double? = nil) -> MPRemoteCommandHandlerStatus {
        if Thread.isMainThread { return dispatch(verb, position: position) }
        return DispatchQueue.main.sync { dispatch(verb, position: position) }
    }

    func dispatch(_ verb: String, position: Double? = nil) -> MPRemoteCommandHandlerStatus {
        if verb == "seek" {
            guard !commands.isEmpty, let position = position, position.isFinite,
                  duration > 0, position >= 0, position <= duration else { return .commandFailed }
            send(epoch + ":system-seek:" + String(position))
        } else {
            guard let command = commands[verb] else { return .commandFailed }
            send(command)
        }
        return .success
    }

    func update(_ model: [String: Any]) {
        let active = model["active"] as? Bool == true
        commands = active ? model["commands"] as? [String: String] ?? [:] : [:]
        epoch = model["epoch"] as? String ?? ""
        duration = model["duration"] as? Double ?? 0
        let remote = MPRemoteCommandCenter.shared()
        for (command, verb) in [(remote.playCommand, "play"), (remote.pauseCommand, "pause"),
                                (remote.togglePlayPauseCommand, "toggle"), (remote.stopCommand, "stop"),
                                (remote.nextTrackCommand, "next"), (remote.previousTrackCommand, "previous"),
                                (remote.skipForwardCommand, "forward"), (remote.skipBackwardCommand, "back")] {
            command.isEnabled = commands[verb] != nil
        }
        remote.changePlaybackPositionCommand.isEnabled = active && duration > 0
        if active {
            let paused = model["paused"] as? Bool == true
            let icon = self.icon
            center.nowPlayingInfo = [
                MPMediaItemPropertyTitle: model["title"] as? String ?? "Jellyfin Player",
                MPMediaItemPropertyArtist: model["artist"] as? String ?? "",
                MPMediaItemPropertyAlbumTitle: model["album"] as? String ?? "",
                MPMediaItemPropertyPlaybackDuration: duration,
                MPNowPlayingInfoPropertyElapsedPlaybackTime: model["position"] as? Double ?? 0,
                MPNowPlayingInfoPropertyPlaybackRate: paused ? 0 : model["rate"] as? Double ?? 1,
                MPNowPlayingInfoPropertyDefaultPlaybackRate: 1,
                MPNowPlayingInfoPropertyMediaType: MPNowPlayingInfoMediaType.video.rawValue,
                MPMediaItemPropertyArtwork: MPMediaItemArtwork(boundsSize: icon.size) { _ in icon }]
            center.playbackState = paused ? .paused : .playing
        } else {
            center.nowPlayingInfo = nil
            center.playbackState = .stopped
        }
        if let path = ProcessInfo.processInfo.environment["JELLYFIN_PLAYER_MENU_DIAGNOSTICS"] {
            let record: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier,
                "bundle": Bundle.main.bundleIdentifier ?? "", "active": active,
                "title": center.nowPlayingInfo?[MPMediaItemPropertyTitle] as? String ?? "",
                "artwork": active ? "jellyfin" : "", "commands": Array(commands.keys).sorted()]
            if let data = try? JSONSerialization.data(withJSONObject: record) {
                try? data.write(to: URL(fileURLWithPath: path).appendingPathComponent("now-playing-host.json"), options: .atomic)
            }
        }
    }
}
