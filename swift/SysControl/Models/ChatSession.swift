import Foundation
import Observation

/// A chat session containing an ordered list of messages.
@Observable
final class ChatSession: Identifiable, Codable {
    let id: UUID
    var title: String
    var messages: [ChatMessage]
    let createdAt: Date
    var isPinned: Bool = false
    var isStreaming: Bool = false
    var activeToolNames: [String] = []
    var wasAutoSavedToHistory: Bool = false

    // Transient streaming state (not persisted)
    private var _streamingMessageID: UUID?
    private var _streamingMessageIndex: Int?

    init(title: String = "New Chat") {
        self.id = UUID()
        self.title = title
        self.messages = []
        self.createdAt = Date()
    }

    // MARK: - Codable

    enum CodingKeys: String, CodingKey {
        case id, title, messages, createdAt, isPinned, wasAutoSavedToHistory
    }

    required init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        messages = try c.decode([ChatMessage].self, forKey: .messages)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        isPinned = try c.decodeIfPresent(Bool.self, forKey: .isPinned) ?? false
        wasAutoSavedToHistory = try c.decodeIfPresent(Bool.self, forKey: .wasAutoSavedToHistory) ?? false
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(title, forKey: .title)
        try c.encode(messages, forKey: .messages)
        try c.encode(createdAt, forKey: .createdAt)
        try c.encode(isPinned, forKey: .isPinned)
        try c.encode(wasAutoSavedToHistory, forKey: .wasAutoSavedToHistory)
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
        _streamingMessageIndex = messages.count - 1
    }

    func appendToken(_ text: String) {
        guard let idx = _streamingMessageIndex,
              idx < messages.count,
              messages[idx].id == _streamingMessageID else { return }
        messages[idx].content += text
    }

    func toolStarted(_ names: [String]) {
        activeToolNames = names
        guard let idx = _streamingMessageIndex,
              idx < messages.count,
              messages[idx].id == _streamingMessageID else { return }
        var existing = messages[idx].toolCalls ?? []
        for name in names where !existing.contains(where: { $0.name == name && $0.result == nil }) {
            existing.append(ToolCall(name: name))
        }
        messages[idx].toolCalls = existing
    }

    func toolFinished(_ name: String, result: String) {
        activeToolNames = []
        guard let idx = _streamingMessageIndex,
              idx < messages.count,
              messages[idx].id == _streamingMessageID else { return }
        guard var calls = messages[idx].toolCalls else { return }
        if let pendingIdx = calls.firstIndex(where: { $0.name == name && $0.result == nil }) {
            calls[pendingIdx].result = result
        } else {
            var call = ToolCall(name: name)
            call.result = result
            calls.append(call)
        }
        messages[idx].toolCalls = calls
    }

    func appendChartImage(_ path: String) {
        // Validate: must be in temp dir with an expected prefix, and file must exist
        let resolved = (path as NSString).resolvingSymlinksInPath
        let tmpDir = (NSTemporaryDirectory() as NSString).resolvingSymlinksInPath
        let basename = (resolved as NSString).lastPathComponent
        let allowedPrefix = basename.hasPrefix("syscontrol_chart_")
            || basename.hasPrefix("syscontrol_artifact_")
        guard resolved.hasPrefix(tmpDir + "/"),
              allowedPrefix,
              FileManager.default.fileExists(atPath: resolved) else { return }

        // Attach image artifact to the current streaming message, or create a new one
        if let idx = _streamingMessageIndex,
           idx < messages.count,
           messages[idx].id == _streamingMessageID {
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
        _streamingMessageIndex = nil
        activeToolNames = []
    }
}
