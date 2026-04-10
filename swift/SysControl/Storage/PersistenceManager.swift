import Foundation

/// Persists chat sessions to JSON files in ~/.syscontrol/swift_chats/.
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

    // MARK: - Atomic Write

    /// Writes data atomically: writes to a temp file then replaces the target.
    private func atomicWrite(_ data: Data, to url: URL) throws {
        let tmpURL = url.appendingPathExtension("tmp")
        try data.write(to: tmpURL)
        _ = try FileManager.default.replaceItemAt(url, withItemAt: tmpURL)
    }

    // MARK: - Session List

    private var indexURL: URL { baseDir.appendingPathComponent("_index.json") }

    func saveSessionList(_ sessions: [ChatSession]) {
        let ids = sessions.map { $0.id.uuidString }
        guard let data = try? encoder.encode(ids) else { return }
        do {
            try atomicWrite(data, to: indexURL)
        } catch {
            FileHandle.standardError.write(
                Data("[SysControl] Failed to save session index: \(error.localizedDescription)\n".utf8)
            )
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
        do {
            try atomicWrite(data, to: url)
        } catch {
            FileHandle.standardError.write(
                Data("[SysControl] Failed to save session \(session.id): \(error.localizedDescription)\n".utf8)
            )
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
