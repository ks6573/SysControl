import Foundation

/// A single message in a chat conversation.
struct ChatMessage: Identifiable, Codable, Equatable {
    let id: UUID
    let role: Role
    var content: String
    let timestamp: Date
    var toolNames: [String]?
    var isError: Bool
    var chartImagePaths: [String]?
    var attachedFilePath: String?
    var toolCalls: [ToolCall]?

    enum Role: String, Codable {
        case user
        case assistant
        case tool
        case system
    }

    init(role: Role, content: String, toolNames: [String]? = nil, isError: Bool = false) {
        self.id = UUID()
        self.role = role
        self.content = content
        self.timestamp = Date()
        self.toolNames = toolNames
        self.isError = isError
    }
}

/// One executed MCP tool call attached to an assistant turn — rendered as
/// an expandable inline card. `result` is nil while the call is in-flight.
struct ToolCall: Identifiable, Codable, Equatable {
    let id: UUID
    let name: String
    var result: String?
    let startedAt: Date

    init(name: String) {
        self.id = UUID()
        self.name = name
        self.result = nil
        self.startedAt = Date()
    }
}
