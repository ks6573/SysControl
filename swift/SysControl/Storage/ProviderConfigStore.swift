import Foundation

/// Persists provider settings in the same location used by the Python GUI.
struct ProviderConfigStore {
    private let configURL: URL = {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".syscontrol", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("gui_config.json")
    }()

    private let decoder = JSONDecoder()
    private let encoder: JSONEncoder = {
        let jsonEncoder = JSONEncoder()
        jsonEncoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return jsonEncoder
    }()

    func load() -> ProviderConfiguration? {
        guard let data = try? Data(contentsOf: configURL) else { return nil }
        return try? decoder.decode(ProviderConfiguration.self, from: data)
    }

    func save(_ config: ProviderConfiguration) {
        guard let data = try? encoder.encode(config) else { return }
        try? data.write(to: configURL)
    }
}
