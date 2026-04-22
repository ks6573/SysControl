import SwiftUI
import Observation

/// Central app state — owns backend lifecycle, session state, and chat history.
@Observable
final class AppState {
    var sessions: [ChatSession] = []
    var activeSessionID: UUID?
    var savedChats: [SavedChat] = []
    var selectedSavedChat: SavedChat?
    var selectedSavedChatContent: String = ""

    var backendStatus: BackendStatus = .connecting
    var toolCount: Int = 0
    var modelName: String = ""
    var connectionError: String?

    var needsOnboarding: Bool = false

    var providerConfiguration: ProviderConfiguration

    let updateService = UpdateService()

    private(set) var backend: BackendService?
    private let persistence = PersistenceManager()
    private let history = ChatHistoryManager()
    private let providerStore = ProviderConfigStore()
    private var pendingSavedChatRefreshWorkItem: DispatchWorkItem?
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?
    private var hydratedSessionIDs: Set<UUID> = []
    private var isShuttingDownBackend = false
    private var savedChatsRefreshNonce: UInt = 0

    // Token batching: accumulate tokens and flush every 50ms to reduce redraws
    private var tokenBuffer: String = ""
    private var tokenFlushWorkItem: DispatchWorkItem?

    /// Backward-compatible computed property used by ChatView's InputBar disable check.
    var isConnected: Bool {
        if case .ready = backendStatus { return true }
        return false
    }

    var activeSession: ChatSession? {
        sessions.first { $0.id == activeSessionID }
    }

    init() {
        let savedConfig = providerStore.load()
        providerConfiguration = savedConfig ?? .localDefault
        needsOnboarding = (savedConfig == nil)

        sessions = persistence.loadSessions()
        if sessions.isEmpty {
            let session = ChatSession()
            sessions = [session]
            activeSessionID = session.id
            persistence.saveSessionList(sessions)
        } else {
            activeSessionID = sessions.first?.id
        }
        refreshSavedChats()
    }

    // MARK: - Onboarding

    func completeOnboarding(_ config: ProviderConfiguration) {
        applyProviderConfiguration(config)
        needsOnboarding = false
    }

    // MARK: - Session Management

    func createNewSession(autoSaveCurrent: Bool = true) {
        if autoSaveCurrent {
            autoSaveActiveSession()
        }

        let session = ChatSession()
        sessions.insert(session, at: 0)
        activeSessionID = session.id
        selectedSavedChat = nil
        selectedSavedChatContent = ""
        persistence.saveSession(session)
        persistence.saveSessionList(sessions)
    }

    func selectSession(_ session: ChatSession) {
        activeSessionID = session.id
        selectedSavedChat = nil
        selectedSavedChatContent = ""
    }

    func deleteSession(_ session: ChatSession) {
        sessions.removeAll { $0.id == session.id }
        persistence.deleteSession(session)
        if activeSessionID == session.id {
            activeSessionID = sessions.first?.id
            selectedSavedChat = nil
            selectedSavedChatContent = ""
            if sessions.isEmpty {
                createNewSession(autoSaveCurrent: false)
                return
            }
        }
        hydratedSessionIDs.remove(session.id)
        persistence.saveSessionList(sessions)
    }

    func setSessionPinned(_ session: ChatSession, pinned: Bool) {
        guard let index = sessions.firstIndex(where: { $0.id == session.id }) else { return }
        let target = sessions[index]
        target.isPinned = pinned

        // Keep sidebar ordering predictable after pin changes.
        sessions.sort { lhs, rhs in
            if lhs.isPinned != rhs.isPinned {
                return lhs.isPinned && !rhs.isPinned
            }
            return lhs.createdAt > rhs.createdAt
        }

        persistence.saveSession(target)
        persistence.saveSessionList(sessions)
    }

    // MARK: - Saved Markdown Chats

    func refreshSavedChats() {
        savedChatsRefreshNonce &+= 1
        let refreshNonce = savedChatsRefreshNonce
        DispatchQueue.global(qos: .utility).async { [history] in
            let chats = history.listSavedChats()
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                guard refreshNonce == self.savedChatsRefreshNonce else { return }
                self.savedChats = chats
            }
        }
    }

    func openSavedChat(_ chat: SavedChat) {
        selectedSavedChat = chat
        selectedSavedChatContent = ""
        let selectedChatID = chat.id
        DispatchQueue.global(qos: .userInitiated).async { [history] in
            let content = history.readChat(at: chat.path)
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                guard self.selectedSavedChat?.id == selectedChatID else { return }
                self.selectedSavedChatContent = content
            }
        }
    }

    func closeSavedChat() {
        selectedSavedChat = nil
        selectedSavedChatContent = ""
    }

    func deleteSavedChat(_ chat: SavedChat) {
        guard history.deleteChat(at: chat.path) else { return }
        if selectedSavedChat?.id == chat.id {
            closeSavedChat()
        }
        refreshSavedChats()
    }

    func importSavedChats(from urls: [URL]) {
        guard !urls.isEmpty else { return }
        var imported = false
        for url in urls {
            if history.importChat(from: url) != nil {
                imported = true
            }
        }
        if imported {
            refreshSavedChats()
        }
    }

    func importSavedChatFromDrop(_ url: URL) {
        guard history.importChat(from: url) != nil else { return }
        scheduleSavedChatRefresh()
    }

    // MARK: - Provider Configuration

    func applyProviderConfiguration(_ configuration: ProviderConfiguration) {
        autoSaveActiveSession()
        providerConfiguration = configuration
        providerStore.save(configuration)
        modelName = configuration.model
        hydratedSessionIDs.removeAll()
        backend?.configure(
            apiKey: configuration.apiKey,
            baseURL: configuration.baseURL,
            model: configuration.model
        )
        backend?.clearSession()
        createNewSession(autoSaveCurrent: false)
    }

    // MARK: - Backend Lifecycle

    func startBackend() {
        guard backend == nil else { return }
        isShuttingDownBackend = false
        hydratedSessionIDs.removeAll()

        let service = BackendService()
        service.onReady = { [weak self] toolCount, model in
            Task { @MainActor in
                self?.backendStatus = .ready(toolCount: toolCount)
                self?.toolCount = toolCount
                self?.modelName = model
                self?.connectionError = nil
                self?.reconnectAttempt = 0

                // Auto-check for updates after backend is ready
                if let updateService = self?.updateService {
                    Task {
                        try? await Task.sleep(for: .seconds(3))
                        await updateService.checkForUpdates()
                    }
                }
            }
        }
        service.onConfigured = { [weak self] model in
            Task { @MainActor in
                self?.modelName = model
                self?.connectionError = nil
            }
        }
        service.onToken = { [weak self] text in
            Task { @MainActor in
                self?.bufferToken(text)
            }
        }
        service.onToolStarted = { [weak self] names in
            Task { @MainActor in
                self?.activeSession?.toolStarted(names)
            }
        }
        service.onToolFinished = { [weak self] name, result in
            Task { @MainActor in
                self?.activeSession?.toolFinished(name, result: result)
            }
        }
        service.onChartImage = { [weak self] path in
            Task { @MainActor in
                self?.activeSession?.appendChartImage(path)
            }
        }
        service.onTurnDone = { [weak self] _, elapsed in
            Task { @MainActor in
                self?.flushTokenBuffer()
                self?.activeSession?.finishStreaming(elapsed: elapsed)
                if let session = self?.activeSession {
                    self?.persistence.saveSession(session)
                }
            }
        }
        service.onError = { [weak self] category, message in
            Task { @MainActor in
                self?.flushTokenBuffer()
                self?.activeSession?.appendError("\(category): \(message)")
                self?.activeSession?.finishStreaming(elapsed: 0)
                self?.connectionError = "\(category): \(message)"
            }
        }
        service.onDisconnected = { [weak self] in
            Task { @MainActor in
                self?.scheduleReconnect()
            }
        }

        backend = service
        service.start()
        service.configure(
            apiKey: providerConfiguration.apiKey,
            baseURL: providerConfiguration.baseURL,
            model: providerConfiguration.model
        )
    }

    func sendMessage(_ text: String, attachedFilePath: String? = nil) {
        guard let session = activeSession else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let shouldSeedSessionHistory = !hydratedSessionIDs.contains(session.id)
        let historySeed = shouldSeedSessionHistory ? bridgeHistory(for: session) : nil

        if Self.exitPhrases.contains(trimmed.lowercased()) {
            handleGoodbye()
            return
        }

        selectedSavedChat = nil
        selectedSavedChatContent = ""

        // Display the clean user text (with optional attachment indicator)
        var userMessage = ChatMessage(role: .user, content: trimmed)
        userMessage.attachedFilePath = attachedFilePath
        session.messages.append(userMessage)
        // Auto-title from first user message
        if session.title == "New Chat" && session.messages.filter({ $0.role == .user }).count == 1 {
            let words = trimmed.split(separator: " ").prefix(6).joined(separator: " ")
            session.title = words.count > 40 ? String(words.prefix(40)) + "…" : words
        }

        // Compose backend message with file context
        let backendText: String
        if let filePath = attachedFilePath {
            let filename = (filePath as NSString).lastPathComponent
            backendText = "[Attached file: \(filename) (\(filePath))]\n\n\(trimmed)"
        } else {
            backendText = trimmed
        }

        session.beginStreaming()
        backend?.sendMessage(
            backendText,
            sessionID: session.id.uuidString,
            history: historySeed
        )
        if shouldSeedSessionHistory {
            hydratedSessionIDs.insert(session.id)
        }
        persistence.saveSession(session)
    }

    func stopBackend() {
        isShuttingDownBackend = true
        reconnectTask?.cancel()
        reconnectTask = nil
        pendingSavedChatRefreshWorkItem?.cancel()
        tokenFlushWorkItem?.cancel()
        hydratedSessionIDs.removeAll()
        autoSaveActiveSession()
        for session in sessions {
            persistence.saveSession(session)
        }
        persistence.saveSessionList(sessions)
        backend?.shutdown()
        backend = nil
    }

    // MARK: - Auto Reconnect

    private func scheduleReconnect() {
        guard !isShuttingDownBackend else { return }
        guard reconnectAttempt < 5 else {
            backendStatus = .failed(message: "Could not connect to backend")
            connectionError = "Could not connect to backend"
            return
        }
        let delay = min(30.0, pow(2.0, Double(reconnectAttempt)))
        reconnectAttempt += 1
        backendStatus = .reconnecting(attempt: reconnectAttempt)
        backend = nil
        hydratedSessionIDs.removeAll()
        reconnectTask?.cancel()
        reconnectTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(delay))
            if Task.isCancelled { return }
            startBackend()
        }
    }

    func retryConnection() {
        isShuttingDownBackend = false
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectAttempt = 0
        backendStatus = .connecting
        backend = nil
        hydratedSessionIDs.removeAll()
        startBackend()
    }

    // MARK: - Cancellation

    func cancelRequest() {
        flushTokenBuffer()
        backend?.cancelRequest()
    }

    // MARK: - Token Batching

    private func bufferToken(_ text: String) {
        tokenBuffer += text
        if tokenFlushWorkItem == nil {
            let work = DispatchWorkItem { [weak self] in
                self?.flushTokenBuffer()
            }
            tokenFlushWorkItem = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05, execute: work)
        }
    }

    private func flushTokenBuffer() {
        tokenFlushWorkItem = nil
        guard !tokenBuffer.isEmpty else { return }
        let batch = tokenBuffer
        tokenBuffer = ""
        activeSession?.appendToken(batch)
    }

    // MARK: - Auto Save

    func autoSaveActiveSession() {
        guard let session = activeSession else { return }
        guard !session.wasAutoSavedToHistory else { return }
        if history.saveSession(session, title: session.title) != nil {
            session.wasAutoSavedToHistory = true
            persistence.saveSession(session)
            refreshSavedChats()
        }
    }

    private func handleGoodbye() {
        autoSaveActiveSession()
        createNewSession(autoSaveCurrent: false)
    }

    private func scheduleSavedChatRefresh() {
        pendingSavedChatRefreshWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.refreshSavedChats()
        }
        pendingSavedChatRefreshWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: work)
    }

    private func bridgeHistory(for session: ChatSession) -> [[String: String]] {
        session.messages.compactMap { message in
            switch message.role {
            case .user, .assistant:
                let trimmed = message.content.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else { return nil }
                return ["role": message.role.rawValue, "content": message.content]
            default:
                return nil
            }
        }
    }

    private static let exitPhrases: Set<String> = [
        "exit", "quit", "bye", "goodbye", "good bye", "farewell",
        "see ya", "see you", "cya", "later", "take care", "peace",
        "done", "close", "end", "stop", ":q", "q", "adios", "adieu",
        "ttyl", "ttfn", "night", "goodnight", "good night",
    ]
}

// MARK: - BackendStatus

enum BackendStatus: Equatable {
    case connecting
    case ready(toolCount: Int)
    case reconnecting(attempt: Int)
    case failed(message: String)
}
