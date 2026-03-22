import Foundation

/// Sidebar metadata for a markdown chat saved in ~/.syscontrol/chat_history.
struct SavedChat: Identifiable, Hashable {
    let path: URL
    let filename: String
    let title: String
    let dateLabel: String

    var id: String { path.path }
}
