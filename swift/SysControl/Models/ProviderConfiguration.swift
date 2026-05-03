import Foundation

/// Provider settings shared between the Python and Swift GUIs.
struct ProviderConfiguration: Codable, Equatable {
    var apiKey: String
    var baseURL: String
    var model: String
    var label: String

    static let localBaseURL = "http://localhost:11434/v1"
    static let cloudBaseURL = "https://ollama.com/v1"
    static let fallbackLocalTagsURL = "http://localhost:11434/api/tags"
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
        label: "☁ Ollama Cloud"
    )

    static var localTagsURL: String {
        ollamaTagsURL(fromOpenAIBaseURL: localBaseURL)
    }

    static func ollamaTagsURL(fromOpenAIBaseURL baseURL: String) -> String {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed) else {
            return fallbackLocalTagsURL
        }

        var segments = components.path.split(separator: "/").map(String.init)
        if segments.last?.lowercased() == "v1" {
            segments.removeLast()
        }
        segments.append("api")
        segments.append("tags")
        components.path = "/" + segments.joined(separator: "/")
        return components.string ?? fallbackLocalTagsURL
    }

    static func openAIModelsURL(fromBaseURL baseURL: String) -> String {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalized = trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed
        return "\(normalized)/models"
    }

    var isLocal: Bool {
        baseURL == Self.localBaseURL
    }
}
