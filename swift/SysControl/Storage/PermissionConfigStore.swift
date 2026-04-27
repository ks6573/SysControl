import Foundation

/// Reads and writes permission flags in ~/.syscontrol/config.json.
/// The Python MCP server polls this file with a 5-second TTL cache,
/// so changes take effect on the next tool call without restarting.
///
/// Maintains an in-memory snapshot so that ``load()`` after an async ``set()``
/// returns the just-written value instead of stale disk contents.
struct PermissionConfigStore {
    private static let cacheLock = NSLock()
    private static var cachedSnapshot: [String: Bool]?

    private let configURL: URL = {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".syscontrol", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("config.json")
    }()

    /// Load all permission flags. Missing file or unknown keys return an empty dict.
    func load() -> [String: Bool] {
        Self.cacheLock.lock()
        if let cached = Self.cachedSnapshot {
            Self.cacheLock.unlock()
            return cached
        }
        Self.cacheLock.unlock()

        let fromDisk: [String: Bool] = {
            guard let data = try? Data(contentsOf: configURL),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Bool]
            else { return [:] }
            return dict
        }()

        Self.cacheLock.lock()
        if Self.cachedSnapshot == nil { Self.cachedSnapshot = fromDisk }
        let result = Self.cachedSnapshot ?? fromDisk
        Self.cacheLock.unlock()
        return result
    }

    /// Merge a single key change into the existing dict and persist.
    /// Other permission flags (allow_shell, etc.) are preserved.
    func set(_ key: String, _ value: Bool) {
        Self.cacheLock.lock()
        var snapshot = Self.cachedSnapshot ?? {
            guard let data = try? Data(contentsOf: configURL),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Bool]
            else { return [:] }
            return dict
        }()
        if snapshot[key] == value {
            Self.cacheLock.unlock()
            return
        }
        snapshot[key] = value
        Self.cachedSnapshot = snapshot
        Self.cacheLock.unlock()

        let url = configURL
        StorageQueue.shared.async {
            guard let data = try? JSONSerialization.data(
                withJSONObject: snapshot,
                options: [.prettyPrinted, .sortedKeys]
            ) else { return }
            do {
                try data.write(to: url, options: [.atomic])
            } catch {
                NSLog("[syscontrol] PermissionConfigStore.set failed: \(error)")
            }
        }
    }
}
