import Foundation

/// Markdown chat history compatible with the Python GUI:
/// ~/.syscontrol/chat_history/*.md
struct ChatHistoryManager {
    private static let titleReadLimit = 16 * 1024
    private static let metadataCache = SavedChatMetadataCache()

    private let historyDirectory: URL = {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".syscontrol/chat_history", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    func listSavedChats() -> [SavedChat] {
        let resourceKeys: [URLResourceKey] = [.contentModificationDateKey, .fileSizeKey]
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: historyDirectory,
            includingPropertiesForKeys: resourceKeys,
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }

        return urls
            .filter { $0.pathExtension.lowercased() == "md" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
            .map { url in
                let values = try? url.resourceValues(forKeys: Set(resourceKeys))
                let title = Self.metadataCache.title(
                    for: url.path,
                    modifiedAt: values?.contentModificationDate,
                    fileSize: values?.fileSize
                ) {
                    extractTitle(from: url)
                }
                return SavedChat(
                    path: url,
                    filename: url.lastPathComponent,
                    title: title,
                    dateLabel: extractDate(from: url.lastPathComponent)
                )
            }
    }

    func readChat(at path: URL) -> String {
        (try? String(contentsOf: path, encoding: .utf8)) ?? ""
    }

    func deleteChat(at path: URL) -> Bool {
        do {
            try FileManager.default.removeItem(at: path)
            Self.metadataCache.remove(path: path.path)
            return true
        } catch {
            return false
        }
    }

    func importChat(from sourcePath: URL) -> URL? {
        guard sourcePath.pathExtension.lowercased() == "md" else { return nil }
        guard FileManager.default.fileExists(atPath: sourcePath.path) else { return nil }

        let timestamp = Self.timestampFormatter.string(from: Date())
        let slug = slugify(sourcePath.deletingPathExtension().lastPathComponent)
        var destination = historyDirectory.appendingPathComponent("\(timestamp)_\(slug).md")

        var counter = 2
        while FileManager.default.fileExists(atPath: destination.path) {
            destination = historyDirectory.appendingPathComponent("\(timestamp)_\(slug)_\(counter).md")
            counter += 1
        }

        do {
            try FileManager.default.copyItem(at: sourcePath, to: destination)
            return destination
        } catch {
            return nil
        }
    }

    func saveSession(_ session: ChatSession, title: String? = nil) -> URL? {
        let visible = session.messages.filter { message in
            (message.role == .user || message.role == .assistant) && !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        guard !visible.isEmpty else { return nil }

        let hasUser = visible.contains { $0.role == .user }
        let hasAssistant = visible.contains { $0.role == .assistant }
        guard hasUser && hasAssistant else { return nil }

        let resolvedTitle: String = {
            let trimmed = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { return trimmed }
            let firstUser = visible.first { $0.role == .user }?.content ?? ""
            return deriveTitle(from: firstUser)
        }()

        let markdown = serialize(messages: visible, title: resolvedTitle)
        let timestamp = Self.timestampFormatter.string(from: Date())
        let slug = slugify(resolvedTitle)

        var destination = historyDirectory.appendingPathComponent("\(timestamp)_\(slug).md")
        var counter = 2
        while FileManager.default.fileExists(atPath: destination.path) {
            destination = historyDirectory.appendingPathComponent("\(timestamp)_\(slug)_\(counter).md")
            counter += 1
        }

        do {
            try markdown.write(to: destination, atomically: true, encoding: .utf8)
            return destination
        } catch {
            return nil
        }
    }

    private func serialize(messages: [ChatMessage], title: String) -> String {
        var result: [String] = []

        let headerDate = Self.headerFormatter.string(from: Date())
        result.append("# \(title) — \(headerDate)")
        result.append("")
        result.append("**Messages:** \(messages.count)")
        result.append("")
        result.append("---")

        for message in messages {
            switch message.role {
            case .user:
                result.append("")
                result.append("### You")
                result.append(message.content)
                result.append("")
                result.append("---")
            case .assistant:
                result.append("")
                result.append("### Assistant")
                result.append(message.content)
                result.append("")
                result.append("---")
            default:
                break
            }
        }

        return result.joined(separator: "\n")
    }

    private func deriveTitle(from text: String) -> String {
        let words = text
            .split(whereSeparator: { $0.isWhitespace })
            .prefix(6)
            .map(String.init)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if words.isEmpty { return "Chat" }
        if words.count <= 50 { return words }
        return String(words.prefix(50))
    }

    private func slugify(_ text: String) -> String {
        let lower = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        let filtered = lower.unicodeScalars.map { scalar -> Character in
            if CharacterSet.alphanumerics.contains(scalar) { return Character(scalar) }
            if CharacterSet.whitespaces.contains(scalar) || scalar == "-" { return " " }
            return " "
        }
        let normalized = String(filtered)
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: "-")
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))

        if normalized.isEmpty { return "untitled" }
        return String(normalized.prefix(40))
    }

    private func extractTitle(from path: URL) -> String {
        guard let content = readPrefix(from: path, maxBytes: Self.titleReadLimit) else {
            return path.deletingPathExtension().lastPathComponent
        }

        for line in content.split(separator: "\n") {
            let text = String(line).trimmingCharacters(in: .whitespacesAndNewlines)
            if text.hasPrefix("# "), text.contains(" — ") {
                let header = text.dropFirst(2)
                let titlePart = header.split(separator: "—", maxSplits: 1).first?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                if !titlePart.isEmpty && titlePart != "Chat" {
                    return String(titlePart.prefix(50))
                }
                break
            }
        }

        var inUserSection = false
        for line in content.split(separator: "\n") {
            let text = String(line).trimmingCharacters(in: .whitespacesAndNewlines)
            if text == "### You" {
                inUserSection = true
                continue
            }
            if inUserSection && !text.isEmpty {
                return String(text.prefix(50))
            }
        }

        return path.deletingPathExtension().lastPathComponent
    }

    private func readPrefix(from path: URL, maxBytes: Int) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: path) else { return nil }
        defer { try? handle.close() }
        guard let data = try? handle.read(upToCount: maxBytes), !data.isEmpty else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func extractDate(from filename: String) -> String {
        let prefix = String(filename.prefix(17))
        guard let date = Self.filenameFormatter.date(from: prefix) else {
            return filename
        }

        let calendar = Calendar.current
        if calendar.isDateInToday(date) {
            return "Today \(Self.timeOnlyFormatter.string(from: date))"
        }
        if calendar.isDateInYesterday(date) {
            return "Yesterday \(Self.timeOnlyFormatter.string(from: date))"
        }
        return Self.fallbackDateFormatter.string(from: date)
    }

    private static let timestampFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HHmmss"
        return formatter
    }()

    private static let filenameFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HHmmss"
        return formatter
    }()

    private static let headerFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMMM dd, yyyy hh:mm a"
        return formatter
    }()

    private static let timeOnlyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "hh:mm a"
        return formatter
    }()

    private static let fallbackDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM dd, yyyy"
        return formatter
    }()
}

private final class SavedChatMetadataCache {
    private struct Entry {
        let modifiedAt: Date?
        let fileSize: Int?
        let title: String
    }

    private var entries: [String: Entry] = [:]
    private let lock = NSLock()

    func title(for path: String, modifiedAt: Date?, fileSize: Int?, loader: () -> String) -> String {
        lock.lock()
        if let cached = entries[path],
           cached.modifiedAt == modifiedAt,
           cached.fileSize == fileSize {
            let title = cached.title
            lock.unlock()
            return title
        }
        lock.unlock()

        let loaded = loader()

        lock.lock()
        entries[path] = Entry(modifiedAt: modifiedAt, fileSize: fileSize, title: loaded)
        if entries.count > 1000 {
            entries.removeAll(keepingCapacity: true)
        }
        lock.unlock()
        return loaded
    }

    func remove(path: String) {
        lock.lock()
        entries.removeValue(forKey: path)
        lock.unlock()
    }
}
