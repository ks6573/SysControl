import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// Main chat area: message list with auto-scroll + input bar at the bottom.
struct ChatView: View {
    @Environment(AppState.self) private var appState
    @State private var pendingScrollWorkItem: DispatchWorkItem?
    @State private var lastScrollAt: Date = .distantPast
    @State private var attachedFilePath: String?
    @State private var isDropTargeted: Bool = false
    @State private var isSearchVisible: Bool = false
    @State private var searchText: String = ""
    @State private var autoScrollEnabled: Bool = true
    @State private var searchMatchMessageIDs: [UUID] = []
    @State private var focusedSearchMatchIndex: Int = 0

    private var normalizedSearchQuery: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var focusedSearchMatchID: UUID? {
        guard !searchMatchMessageIDs.isEmpty else { return nil }
        let index = min(max(focusedSearchMatchIndex, 0), searchMatchMessageIDs.count - 1)
        return searchMatchMessageIDs[index]
    }

    var body: some View {
        VStack(spacing: 0) {
            // Search bar
            if isSearchVisible {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search messages…", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 13))
                        .onKeyPress(.return, phases: .down) { press in
                            if press.modifiers.contains(.shift) {
                                focusPreviousSearchMatch()
                            } else {
                                focusNextSearchMatch()
                            }
                            return .handled
                        }
                    if !normalizedSearchQuery.isEmpty {
                        Text("\(searchMatchMessageIDs.count) match\(searchMatchMessageIDs.count == 1 ? "" : "es")")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        Button {
                            focusPreviousSearchMatch()
                        } label: {
                            Image(systemName: "chevron.up")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .disabled(searchMatchMessageIDs.isEmpty)
                        .help("Previous match")

                        Button {
                            focusNextSearchMatch()
                        } label: {
                            Image(systemName: "chevron.down")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .disabled(searchMatchMessageIDs.isEmpty)
                        .help("Next match")
                    }
                    if !searchText.isEmpty {
                        Button {
                            searchText = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                    Button {
                        isSearchVisible = false
                        searchText = ""
                        searchMatchMessageIDs = []
                        focusedSearchMatchIndex = 0
                    } label: {
                        Text("Done")
                            .font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color.primary.opacity(0.04))
                Divider()
            }

            // Messages
            ZStack(alignment: .bottom) {
                if let session = appState.activeSession {
                    if session.messages.isEmpty {
                        welcomeView
                    } else {
                        messageList(session)
                    }
                }

                // Bottom scrim — fades content behind the input bar.
                LinearGradient(
                    colors: [
                        Color(nsColor: .windowBackgroundColor).opacity(0),
                        Color(nsColor: .windowBackgroundColor).opacity(0.85),
                        Color(nsColor: .windowBackgroundColor),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .frame(height: 36)
                .allowsHitTesting(false)
            }

            if case .ready = appState.backendStatus { } else {
                ConnectionStatusBanner(status: appState.backendStatus) {
                    appState.retryConnection()
                }
            }

            // Input bar — no divider, blends into the scroll fade above.
            InputBar(
                onSend: { text, filePath in
                    autoScrollEnabled = true
                    appState.sendMessage(text, attachedFilePath: filePath)
                },
                onCancel: { appState.cancelRequest() },
                isStreaming: appState.activeSession?.isStreaming == true,
                attachedFilePath: $attachedFilePath
            )
            .disabled(!appState.isConnected)
        }
        .overlay {
            if isDropTargeted {
                dropOverlay
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $isDropTargeted) { providers in
            handleDrop(providers)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .onKeyPress(characters: CharacterSet(charactersIn: "f"), phases: .down) { press in
            guard press.modifiers.contains(.command) else { return .ignored }
            isSearchVisible.toggle()
            if !isSearchVisible {
                searchText = ""
                searchMatchMessageIDs = []
                focusedSearchMatchIndex = 0
            }
            return .handled
        }
        .onKeyPress(characters: CharacterSet(charactersIn: "g"), phases: .down) { press in
            guard isSearchVisible, press.modifiers.contains(.command) else { return .ignored }
            if press.modifiers.contains(.shift) {
                focusPreviousSearchMatch()
            } else {
                focusNextSearchMatch()
            }
            return .handled
        }
        .onChange(of: appState.activeSessionID) { _, _ in
            autoScrollEnabled = true
            focusedSearchMatchIndex = 0
            searchMatchMessageIDs = []
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text(toolbarTitle)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.primary.opacity(0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: 380)
            }
            ToolbarItemGroup(placement: .primaryAction) {
                modelBadge
                Button {
                    isSearchVisible.toggle()
                    if !isSearchVisible {
                        searchText = ""
                        searchMatchMessageIDs = []
                        focusedSearchMatchIndex = 0
                    }
                } label: {
                    Image(systemName: "magnifyingglass")
                }
                .help("Search messages (⌘F)")
                .keyboardShortcut("f", modifiers: .command)
            }
        }
    }

    private var toolbarTitle: String {
        if let title = appState.activeSession?.title, !title.isEmpty, title != "New Chat" {
            return title
        }
        return "SysControl"
    }

    private var modelBadge: some View {
        let cfg = appState.providerConfiguration
        let icon = cfg.isLocal ? "desktopcomputer" : "cloud"
        return HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .medium))
            Text(cfg.model)
                .font(.system(size: 11, weight: .medium))
                .lineLimit(1)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(
            Capsule().fill(Color.primary.opacity(0.07))
        )
        .help("\(cfg.label) · \(cfg.model) — change in Settings (⌘,)")
    }

    // MARK: - Messages

    private func messageList(_ session: ChatSession) -> some View {
        let matchingIDs = Set(searchMatchMessageIDs)
        let focusedMatchID = focusedSearchMatchID

        return ScrollViewReader { proxy in
            ChatMessageListContent(
                session: session,
                searchQuery: normalizedSearchQuery,
                matchingIDs: matchingIDs,
                focusedMatchID: focusedMatchID,
                showStreamingIndicator: isAwaitingFirstToken(session)
            )
            .simultaneousGesture(
                DragGesture(minimumDistance: 6)
                    .onChanged { _ in
                        autoScrollEnabled = false
                    }
            )
            .overlay(alignment: .bottomTrailing) {
                if !autoScrollEnabled, !session.messages.isEmpty {
                    Button {
                        autoScrollEnabled = true
                        if session.isStreaming {
                            scheduleScroll(proxy: proxy, target: "streaming-indicator", animated: true, debounce: 0)
                        } else if let last = session.messages.last {
                            scheduleScroll(proxy: proxy, target: last.id, animated: true, debounce: 0)
                        }
                    } label: {
                        Label("Jump to latest", systemImage: "arrow.down")
                            .font(.system(size: 12, weight: .semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(
                                Capsule(style: .continuous)
                                    .fill(.ultraThinMaterial)
                            )
                    }
                    .buttonStyle(.plain)
                    .padding(.trailing, 16)
                    .padding(.bottom, 12)
                }
            }
            .onAppear {
                refreshSearchMatches(for: session)
            }
            .onChange(of: isSearchVisible) { _, _ in
                refreshSearchMatches(for: session)
            }
            .onChange(of: searchText) { _, _ in
                refreshSearchMatches(for: session)
            }
            .onChange(of: session.messages) { _, _ in
                refreshSearchMatches(for: session)
            }
            .onChange(of: focusedSearchMatchIndex) { _, _ in
                guard let focusedID = focusedSearchMatchID else { return }
                autoScrollEnabled = false
                scheduleScroll(proxy: proxy, target: focusedID, animated: true, debounce: 0)
            }
            .onChange(of: session.messages.count) { _, _ in
                guard autoScrollEnabled else { return }
                if session.isStreaming {
                    scheduleScroll(proxy: proxy, target: "streaming-indicator", animated: true, debounce: 0.03)
                } else if let last = session.messages.last {
                    scheduleScroll(proxy: proxy, target: last.id, animated: true, debounce: 0.03)
                }
            }
            .onChange(of: session.messages.last?.content) { _, _ in
                // Auto-scroll during streaming
                if session.isStreaming && autoScrollEnabled {
                    scheduleScroll(proxy: proxy, target: "streaming-indicator", animated: false, debounce: 0.05)
                }
            }
            .onChange(of: session.activeToolNames) { _, _ in
                if !session.activeToolNames.isEmpty && autoScrollEnabled,
                   let last = session.messages.last {
                    scheduleScroll(proxy: proxy, target: last.id, animated: false, debounce: 0.05)
                }
            }
            .onDisappear {
                pendingScrollWorkItem?.cancel()
            }
        }
    }

    private func refreshSearchMatches(for session: ChatSession) {
        let query = normalizedSearchQuery
        guard isSearchVisible, !query.isEmpty else {
            searchMatchMessageIDs = []
            focusedSearchMatchIndex = 0
            return
        }

        let previousFocusedID = focusedSearchMatchID
        let matches = session.messages.compactMap { message -> UUID? in
            guard message.role == .assistant || message.role == .user else { return nil }
            guard message.content.range(
                of: query,
                options: [.caseInsensitive, .diacriticInsensitive]
            ) != nil else { return nil }
            return message.id
        }
        searchMatchMessageIDs = matches

        guard !matches.isEmpty else {
            focusedSearchMatchIndex = 0
            return
        }
        if let previousFocusedID,
           let existingIndex = matches.firstIndex(of: previousFocusedID) {
            focusedSearchMatchIndex = existingIndex
        } else {
            focusedSearchMatchIndex = 0
        }
    }

    private func focusNextSearchMatch() {
        guard !searchMatchMessageIDs.isEmpty else { return }
        autoScrollEnabled = false
        focusedSearchMatchIndex = (focusedSearchMatchIndex + 1) % searchMatchMessageIDs.count
    }

    private func focusPreviousSearchMatch() {
        guard !searchMatchMessageIDs.isEmpty else { return }
        autoScrollEnabled = false
        focusedSearchMatchIndex = (focusedSearchMatchIndex - 1 + searchMatchMessageIDs.count)
            % searchMatchMessageIDs.count
    }

    // MARK: - Welcome

    private var welcomeView: some View {
        VStack(spacing: 18) {
            Spacer()
            VStack(spacing: 8) {
                Text(greeting)
                    .font(.system(size: 30, weight: .medium, design: .serif))
                    .foregroundStyle(.primary.opacity(0.85))
                    .multilineTextAlignment(.center)
                Text("How can I help with your system?")
                    .font(.system(size: 14))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.bottom, 8)

            starterPrompts
                .frame(maxWidth: 620)

            Spacer()
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var starterPrompts: some View {
        let prompts: [(icon: String, label: String, prompt: String)] = [
            ("cpu", "CPU usage right now", "Show me current CPU usage broken down by process."),
            ("memorychip", "Memory pressure", "Check memory pressure and what's using the most RAM."),
            ("internaldrive", "Disk space overview", "How much disk space is free, and which directories are largest?"),
            ("bolt", "Top energy hogs", "Which processes are using the most energy and CPU right now?"),
        ]
        return LazyVGrid(
            columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
            spacing: 10
        ) {
            ForEach(prompts, id: \.label) { item in
                StarterPromptCard(
                    icon: item.icon,
                    label: item.label,
                    onTap: {
                        autoScrollEnabled = true
                        appState.sendMessage(item.prompt)
                    }
                )
            }
        }
    }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        let timeOfDay: String
        switch hour {
        case 5..<12:  timeOfDay = "morning"
        case 12..<17: timeOfDay = "afternoon"
        case 17..<22: timeOfDay = "evening"
        default:      timeOfDay = "night"
        }
        let name = NSFullUserName().split(separator: " ").first.map(String.init) ?? ""
        return name.isEmpty ? "Good \(timeOfDay)" : "Good \(timeOfDay), \(name)"
    }

    private func scheduleScroll(
        proxy: ScrollViewProxy,
        target: AnyHashable,
        animated: Bool,
        debounce: TimeInterval
    ) {
        pendingScrollWorkItem?.cancel()
        let work = DispatchWorkItem {
            let minInterval: TimeInterval = 0.06
            let now = Date()
            if now.timeIntervalSince(lastScrollAt) < minInterval {
                return
            }
            if animated {
                withAnimation(.easeOut(duration: 0.12)) {
                    proxy.scrollTo(target, anchor: .bottom)
                }
            } else {
                proxy.scrollTo(target, anchor: .bottom)
            }
            lastScrollAt = Date()
        }
        pendingScrollWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + debounce, execute: work)
    }

    private func isAwaitingFirstToken(_ session: ChatSession) -> Bool {
        guard session.isStreaming else { return false }
        guard let latestAssistant = session.messages.last(where: { $0.role == .assistant }) else {
            return true
        }
        return latestAssistant.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    // MARK: - File Drop

    private static let supportedExtensions: Set<String> = [
        "pdf", "xlsx", "xls", "csv", "docx", "doc", "txt", "md", "rst", "text",
    ]

    private var dropOverlay: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.ultraThinMaterial)
            VStack(spacing: 10) {
                Image(systemName: "arrow.down.doc.fill")
                    .font(.system(size: 36))
                    .foregroundStyle(.secondary)
                Text("Drop file to attach")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                Text("PDF, Word, Excel, CSV, or text files")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(16)
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        guard provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) else {
            return false
        }
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
            guard let data = item as? Data,
                  let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
            let ext = url.pathExtension.lowercased()
            guard Self.supportedExtensions.contains(ext) else { return }
            Task { @MainActor in
                attachedFilePath = url.path
            }
        }
        return true
    }
}

private struct ChatMessageListContent: View {
    let session: ChatSession
    let searchQuery: String
    let matchingIDs: Set<UUID>
    let focusedMatchID: UUID?
    let showStreamingIndicator: Bool

    var body: some View {
        ScrollView {
            HStack(spacing: 0) {
                Spacer(minLength: 0)
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(session.messages) { message in
                        ChatMessageRow(
                            message: message,
                            isStreaming: session.isStreaming
                                && message.role == .assistant
                                && message.id == session.messages.last?.id,
                            searchQuery: searchQuery,
                            isSearchMatch: matchingIDs.contains(message.id),
                            isFocusedSearchMatch: focusedMatchID == message.id
                        )
                        .id(message.id)
                    }

                    if session.isStreaming && showStreamingIndicator {
                        ThinkingIndicator()
                            .id("streaming-indicator")
                    }
                }
                .frame(maxWidth: Theme.readingColumn, alignment: .leading)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 24)
            .padding(.top, 24)
            .padding(.bottom, 96)
        }
    }
}

private struct ChatMessageRow: View {
    let message: ChatMessage
    let isStreaming: Bool
    let searchQuery: String
    let isSearchMatch: Bool
    let isFocusedSearchMatch: Bool

    var body: some View {
        MessageBubble(
            message: message,
            isStreaming: isStreaming,
            searchQuery: searchQuery,
            isSearchMatch: isSearchMatch,
            isFocusedSearchMatch: isFocusedSearchMatch
        )
    }
}

// MARK: - Connection Status Banner

private struct ConnectionStatusBanner: View {
    let status: BackendStatus
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(dotColor)
                .frame(width: 7, height: 7)
            Text(statusText)
                .font(.system(size: 12))
                .foregroundStyle(.primary.opacity(0.8))
            Spacer()
            if case .failed = status {
                Button("Retry") { onRetry() }
                    .font(.system(size: 12))
                    .buttonStyle(.plain)
                    .foregroundStyle(.red)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 7)
        .background(bannerColor.opacity(0.12))
    }

    private var dotColor: Color {
        switch status {
        case .connecting:    return .yellow
        case .ready:         return .green
        case .reconnecting:  return .orange
        case .failed:        return .red
        }
    }

    private var bannerColor: Color {
        switch status {
        case .connecting:    return .yellow
        case .ready:         return .green
        case .reconnecting:  return .orange
        case .failed:        return .red
        }
    }

    private var statusText: String {
        switch status {
        case .connecting:
            return "Connecting to backend..."
        case .ready:
            return "Connected"
        case .reconnecting(let attempt):
            return "Reconnecting... (attempt \(attempt)/5)"
        case .failed(let message):
            return message
        }
    }
}

// MARK: - Typing Indicator

private struct StarterPromptCard: View {
    let icon: String
    let label: String
    let onTap: () -> Void

    @State private var isHovering = false

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Theme.accent.opacity(0.9))
                    .frame(width: 22)
                Text(label)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary.opacity(0.85))
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 4)
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary.opacity(isHovering ? 1 : 0.45))
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.primary.opacity(isHovering ? 0.08 : 0.05))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.primary.opacity(isHovering ? 0.14 : 0.08), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .onHover { isHovering = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovering)
    }
}

private struct ThinkingIndicator: View {
    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(Color.primary.opacity(0.6))
                .frame(width: 7, height: 7)
                .symbolEffect(.pulse, options: .repeating)
            Text("Thinking")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }
}
