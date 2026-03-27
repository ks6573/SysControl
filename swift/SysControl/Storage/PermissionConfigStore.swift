import Foundation

/// Reads and writes permission flags in ~/.syscontrol/config.json.
/// The Python MCP server polls this file with a 5-second TTL cache,
/// so changes take effect on the next tool call without restarting.
struct PermissionConfigStore {
    private let configURL: URL = {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".syscontrol", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("config.json")
    }()

    /// Load all permission flags. Missing file or unknown keys return an empty dict.
    func load() -> [String: Bool] {
        guard let data = try? Data(contentsOf: configURL),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Bool]
        else { return [:] }
        return dict
    }

    /// Merge a single key change into the existing dict and persist.
    /// Other permission flags (allow_shell, etc.) are preserved.
    func set(_ key: String, _ value: Bool) {
        var permissions = load()
        permissions[key] = value
        guard let data = try? JSONSerialization.data(
            withJSONObject: permissions,
            options: [.prettyPrinted, .sortedKeys]
        ) else { return }
        try? data.write(to: configURL)
    }
}
