import Foundation
import Observation

/// A chat session containing an ordered list of messages.
@Observable
final class ChatSession: Identifiable, Codable {
    let id: UUID
    var title: String
    var messages: [ChatMessage]
    let createdAt: Date
    var isStreaming: Bool = false
    var activeToolNames: [String] = []
    var wasAutoSavedToHistory: Bool = false

    // Transient streaming state (not persisted)
    private var _streamingMessageID: UUID?

    init(title: String = "New Chat") {
        self.id = UUID()
        self.title = title
        self.messages = []
        self.createdAt = Date()
    }

    // MARK: - Codable

    enum CodingKeys: String, CodingKey {
        case id, title, messages, createdAt
    }

    required init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        messages = try c.decode([ChatMessage].self, forKey: .messages)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(title, forKey: .title)
        try c.encode(messages, forKey: .messages)
        try c.encode(createdAt, forKey: .createdAt)
    }

    // MARK: - Message Management

    func addUserMessage(_ text: String) {
        messages.append(ChatMessage(role: .user, content: text))
        // Auto-title from first user message
        if title == "New Chat" && messages.filter({ $0.role == .user }).count == 1 {
            let words = text.split(separator: " ").prefix(6).joined(separator: " ")
            title = words.count > 40 ? String(words.prefix(40)) + "…" : words
        }
    }

    func beginStreaming() {
        isStreaming = true
        activeToolNames = []
        let msg = ChatMessage(role: .assistant, content: "")
        _streamingMessageID = msg.id
        messages.append(msg)
    }

    func appendToken(_ text: String) {
        guard let sid = _streamingMessageID,
              let idx = messages.lastIndex(where: { $0.id == sid }) else { return }
        messages[idx].content += text
    }

    func toolStarted(_ names: [String]) {
        activeToolNames = names
    }

    func toolFinished(_ name: String, result: String) {
        _ = (name, result)
        activeToolNames = []
    }

    func appendChartImage(_ path: String) {
        // Attach chart to the current streaming message, or create a new one
        if let sid = _streamingMessageID,
           let idx = messages.lastIndex(where: { $0.id == sid }) {
            if messages[idx].chartImagePaths == nil {
                messages[idx].chartImagePaths = [path]
            } else {
                messages[idx].chartImagePaths?.append(path)
            }
        } else {
            var msg = ChatMessage(role: .assistant, content: "")
            msg.chartImagePaths = [path]
            messages.append(msg)
        }
    }

    func appendError(_ message: String) {
        messages.append(ChatMessage(role: .assistant, content: message, isError: true))
    }

    func finishStreaming(elapsed: TimeInterval) {
        _ = elapsed
        isStreaming = false
        _streamingMessageID = nil
        activeToolNames = []
    }
}
