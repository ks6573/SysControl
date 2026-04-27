import Foundation

/// Persists provider settings.  Non-secret fields are written as JSON to
/// ``~/.syscontrol/gui_config.json``; the API key is stored in the macOS
/// Keychain.  Plaintext keys present in older config files are migrated to
/// Keychain on first read.
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

    /// Disk shape — same field names as ``ProviderConfiguration`` (so older
    /// files load) but ``apiKey`` is optional and treated as legacy data
    /// to be migrated, not a long-term store.
    private struct Persisted: Codable {
        var apiKey: String?
        var baseURL: String
        var model: String
        var label: String
    }

    func load() -> ProviderConfiguration? {
        guard let data = try? Data(contentsOf: configURL),
              let persisted = try? decoder.decode(Persisted.self, from: data)
        else {
            return nil
        }

        let account = KeychainHelper.account(forBaseURL: persisted.baseURL)
        var apiKey = KeychainHelper.get(account: account) ?? ""

        // Migrate legacy plaintext key into Keychain, then strip it from disk.
        if apiKey.isEmpty,
           let legacy = persisted.apiKey,
           !legacy.isEmpty,
           legacy != ProviderConfiguration.localAPIKey {
            if KeychainHelper.set(legacy, account: account) {
                apiKey = legacy
                let cleaned = Persisted(
                    apiKey: nil,
                    baseURL: persisted.baseURL,
                    model: persisted.model,
                    label: persisted.label
                )
                if let cleanedData = try? encoder.encode(cleaned) {
                    try? cleanedData.write(to: configURL, options: [.atomic])
                }
            }
        }

        // Local provider doesn't need a real key — fall back to the dummy.
        if apiKey.isEmpty, persisted.baseURL == ProviderConfiguration.localBaseURL {
            apiKey = ProviderConfiguration.localAPIKey
        }

        return ProviderConfiguration(
            apiKey: apiKey,
            baseURL: persisted.baseURL,
            model: persisted.model,
            label: persisted.label
        )
    }

    func save(_ config: ProviderConfiguration) {
        let persisted = Persisted(
            apiKey: nil,
            baseURL: config.baseURL,
            model: config.model,
            label: config.label
        )
        guard let data = try? encoder.encode(persisted) else { return }
        let url = configURL
        let baseURL = config.baseURL
        let apiKey = config.apiKey
        StorageQueue.shared.async {
            let account = KeychainHelper.account(forBaseURL: baseURL)
            if baseURL == ProviderConfiguration.localBaseURL {
                KeychainHelper.delete(account: account)
            } else {
                KeychainHelper.set(apiKey, account: account)
            }
            do {
                try data.write(to: url, options: [.atomic])
            } catch {
                NSLog("[syscontrol] ProviderConfigStore.save failed: \(error)")
            }
        }
    }
}
