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

    var isConnected: Bool = false
    var toolCount: Int = 0
    var modelName: String = ""
    var connectionError: String?

    var providerConfiguration: ProviderConfiguration

    private(set) var backend: BackendService?
    private let persistence = PersistenceManager()
    private let history = ChatHistoryManager()
    private let providerStore = ProviderConfigStore()
    private var pendingSavedChatRefreshWorkItem: DispatchWorkItem?

    var activeSession: ChatSession? {
        sessions.first { $0.id == activeSessionID }
    }

    init() {
        providerConfiguration = providerStore.load() ?? .localDefault
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
        backend?.clearSession()
        persistence.saveSession(session)
        persistence.saveSessionList(sessions)
    }

    func selectSession(_ session: ChatSession) {
        activeSessionID = session.id
        selectedSavedChat = nil
        selectedSavedChatContent = ""
        backend?.clearSession()
    }

    func deleteSession(_ session: ChatSession) {
        sessions.removeAll { $0.id == session.id }
        persistence.deleteSession(session)
        if activeSessionID == session.id {
            activeSessionID = sessions.first?.id
            selectedSavedChat = nil
            selectedSavedChatContent = ""
            backend?.clearSession()
            if sessions.isEmpty {
                createNewSession(autoSaveCurrent: false)
                return
            }
        }
        persistence.saveSessionList(sessions)
    }

    // MARK: - Saved Markdown Chats

    func refreshSavedChats() {
        savedChats = history.listSavedChats()
    }

    func openSavedChat(_ chat: SavedChat) {
        selectedSavedChat = chat
        selectedSavedChatContent = history.readChat(at: chat.path)
    }

    func closeSavedChat() {
        selectedSavedChat = nil
        selectedSavedChatContent = ""
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

        let service = BackendService()
        service.onReady = { [weak self] toolCount, model in
            Task { @MainActor in
                self?.isConnected = true
                self?.toolCount = toolCount
                self?.modelName = model
                self?.connectionError = nil
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
                self?.activeSession?.appendToken(text)
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
        service.onTurnDone = { [weak self] _, elapsed in
            Task { @MainActor in
                self?.activeSession?.finishStreaming(elapsed: elapsed)
                if let session = self?.activeSession {
                    self?.persistence.saveSession(session)
                }
            }
        }
        service.onError = { [weak self] category, message in
            Task { @MainActor in
                self?.activeSession?.appendError("\(category): \(message)")
                self?.activeSession?.finishStreaming(elapsed: 0)
                self?.connectionError = "\(category): \(message)"
            }
        }
        service.onDisconnected = { [weak self] in
            Task { @MainActor in
                self?.isConnected = false
                self?.connectionError = "Backend disconnected"
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

    func sendMessage(_ text: String) {
        guard let session = activeSession else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        if Self.exitPhrases.contains(trimmed.lowercased()) {
            handleGoodbye()
            return
        }

        selectedSavedChat = nil
        selectedSavedChatContent = ""
        session.addUserMessage(trimmed)
        session.beginStreaming()
        backend?.sendMessage(trimmed)
        persistence.saveSession(session)
    }

    func stopBackend() {
        autoSaveActiveSession()
        for session in sessions {
            persistence.saveSession(session)
        }
        persistence.saveSessionList(sessions)
        backend?.shutdown()
        backend = nil
    }

    // MARK: - Auto Save

    func autoSaveActiveSession() {
        guard let session = activeSession else { return }
        guard !session.wasAutoSavedToHistory else { return }
        if history.saveSession(session, title: session.title) != nil {
            session.wasAutoSavedToHistory = true
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

    private static let exitPhrases: Set<String> = [
        "exit", "quit", "bye", "goodbye", "good bye", "farewell",
        "see ya", "see you", "cya", "later", "take care", "peace",
        "done", "close", "end", "stop", ":q", "q", "adios", "adieu",
        "ttyl", "ttfn", "night", "goodnight", "good night",
    ]
}
