import Foundation

/// Persists chat sessions to JSON files in ~/.syscontrol/swift_chats/.
///
/// Concurrent ``saveSession`` / ``saveSessionList`` calls land in submission
/// order via the shared ``StorageQueue`` instead of racing.
struct PersistenceManager {
    private let baseDir: URL = {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".syscontrol/swift_chats")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    // MARK: - Session List

    private var indexURL: URL { baseDir.appendingPathComponent("_index.json") }

    func saveSessionList(_ sessions: [ChatSession]) {
        let ids = sessions.map { $0.id.uuidString }
        guard let data = try? encoder.encode(ids) else { return }
        let target = indexURL
        StorageQueue.shared.async {
            do {
                try data.write(to: target, options: [.atomic])
            } catch {
                FileHandle.standardError.write(
                    Data("[SysControl] Failed to save session index: \(error.localizedDescription)\n".utf8)
                )
            }
        }
    }

    func loadSessions() -> [ChatSession] {
        guard let data = try? Data(contentsOf: indexURL),
              let ids = try? decoder.decode([String].self, from: data) else {
            return []
        }
        return ids.compactMap { idString -> ChatSession? in
            guard let uuid = UUID(uuidString: idString) else { return nil }
            return loadSession(id: uuid)
        }
    }

    // MARK: - Individual Sessions

    func saveSession(_ session: ChatSession) {
        let url = baseDir.appendingPathComponent("\(session.id.uuidString).json")
        guard let data = try? encoder.encode(session) else { return }
        let sessionID = session.id
        StorageQueue.shared.async {
            do {
                try data.write(to: url, options: [.atomic])
            } catch {
                FileHandle.standardError.write(
                    Data("[SysControl] Failed to save session \(sessionID): \(error.localizedDescription)\n".utf8)
                )
            }
        }
    }

    func loadSession(id: UUID) -> ChatSession? {
        let url = baseDir.appendingPathComponent("\(id.uuidString).json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? decoder.decode(ChatSession.self, from: data)
    }

    func deleteSession(_ session: ChatSession) {
        let url = baseDir.appendingPathComponent("\(session.id.uuidString).json")
        try? FileManager.default.removeItem(at: url)
    }
}
