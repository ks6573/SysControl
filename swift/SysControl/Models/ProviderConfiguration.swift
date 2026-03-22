import Foundation

/// Provider settings shared between the Python and Swift GUIs.
struct ProviderConfiguration: Codable, Equatable {
    var apiKey: String
    var baseURL: String
    var model: String
    var label: String

    static let localBaseURL = "http://localhost:11434/v1"
    static let cloudBaseURL = "https://ollama.com/v1"
    static let localAPIKey = "ollama"
    static let localDefaultModel = "qwen3:30b"
    static let cloudDefaultModel = "gpt-oss:120b"

    static let localDefault = ProviderConfiguration(
        apiKey: localAPIKey,
        baseURL: localBaseURL,
        model: localDefaultModel,
        label: "⚙ Local (Ollama)"
    )

    static let cloudDefault = ProviderConfiguration(
        apiKey: "",
        baseURL: cloudBaseURL,
        model: cloudDefaultModel,
        label: "☁ Cloud"
    )

    var isLocal: Bool {
        baseURL == Self.localBaseURL
    }
}
