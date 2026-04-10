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
