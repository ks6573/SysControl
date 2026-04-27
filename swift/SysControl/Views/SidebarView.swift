import SwiftUI
import UniformTypeIdentifiers

/// Left sidebar: current sessions + saved markdown chats.
struct SidebarView: View {
    @Environment(AppState.self) private var appState
    @State private var isImporterPresented = false
    @State private var sessionToDelete: ChatSession?
    @State private var savedChatToDelete: SavedChat?
    @State private var pinnedSessions: [ChatSession] = []
    @State private var recentSessionGroups: [SessionGroup] = []

    private var markdownType: UTType {
        UTType(filenameExtension: "md") ?? .plainText
    }

    private static func computePinned(_ sessions: [ChatSession]) -> [ChatSession] {
        sessions.filter(\.isPinned)
    }

    private static func computeRecentGroups(_ sessions: [ChatSession]) -> [SessionGroup] {
        var grouped: [SessionBucket: [ChatSession]] = [:]
        for session in sessions where !session.isPinned {
            let bucket = SessionBucket.bucket(for: session.createdAt)
            grouped[bucket, default: []].append(session)
        }
        return SessionBucket.allCases.compactMap { bucket in
            guard let sessions = grouped[bucket], !sessions.isEmpty else { return nil }
            return SessionGroup(bucket: bucket, sessions: sessions)
        }
    }

    private func refreshSessionGroups() {
        let sessions = appState.sessions
        pinnedSessions = Self.computePinned(sessions)
        recentSessionGroups = Self.computeRecentGroups(sessions)
    }

    /// Equatable digest of every input the cached groupings depend on.  When
    /// this changes we recompute; otherwise body re-evaluations are cheap.
    private var sessionsFingerprint: [SessionFingerprint] {
        appState.sessions.map { SessionFingerprint(id: $0.id, isPinned: $0.isPinned, createdAt: $0.createdAt) }
    }

    private struct SessionFingerprint: Equatable {
        let id: UUID
        let isPinned: Bool
        let createdAt: Date
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            connectionStatus
            updateBanner
            Divider()
            sidebarList
        }
        .frame(minWidth: 280)
        .background(Color(nsColor: .controlBackgroundColor))
        .fileImporter(
            isPresented: $isImporterPresented,
            allowedContentTypes: [markdownType],
            allowsMultipleSelection: true
        ) { result in
            guard case let .success(urls) = result else { return }
            appState.importSavedChats(from: urls)
        }
        .onDrop(of: [UTType.fileURL], isTargeted: nil, perform: importDroppedFiles)
        .alert(
            "Delete Chat",
            isPresented: Binding(
                get: { sessionToDelete != nil },
                set: { if !$0 { sessionToDelete = nil } }
            )
        ) {
            Button("Cancel", role: .cancel) { sessionToDelete = nil }
            Button("Delete", role: .destructive) {
                if let session = sessionToDelete {
                    withAnimation { appState.deleteSession(session) }
                    sessionToDelete = nil
                }
            }
        } message: {
            Text("Are you sure you want to delete \"\(sessionToDelete?.title ?? "")\"?")
        }
        .alert(
            "Delete Saved Chat",
            isPresented: Binding(
                get: { savedChatToDelete != nil },
                set: { if !$0 { savedChatToDelete = nil } }
            )
        ) {
            Button("Cancel", role: .cancel) { savedChatToDelete = nil }
            Button("Delete", role: .destructive) {
                if let chat = savedChatToDelete {
                    appState.deleteSavedChat(chat)
                    savedChatToDelete = nil
                }
            }
        } message: {
            Text("Are you sure you want to delete \"\(savedChatToDelete?.title ?? "")\"?")
        }
        .onAppear { refreshSessionGroups() }
        .onChange(of: sessionsFingerprint) { _, _ in refreshSessionGroups() }
    }

    private var header: some View {
        HStack {
            Text("SysControl")
                .font(.headline)
                .fontWeight(.semibold)
            Spacer()
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    appState.createNewSession()
                }
            } label: {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 16, weight: .medium))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help("New Chat")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var connectionStatus: some View {
        if appState.isConnected {
            HStack(spacing: 6) {
                Circle()
                    .fill(.green)
                    .frame(width: 6, height: 6)
                Text("\(appState.toolCount) tools · \(appState.modelName)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
        } else if let error = appState.connectionError {
            HStack(spacing: 6) {
                Circle()
                    .fill(.red)
                    .frame(width: 6, height: 6)
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red.opacity(0.8))
                    .lineLimit(1)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
        } else {
            HStack(spacing: 6) {
                ProgressView()
                    .scaleEffect(0.5)
                    .frame(width: 10, height: 10)
                Text("Connecting…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private var updateBanner: some View {
        if case .available(let version, _) = appState.updateService.status {
            Button {
                appState.updateService.performUpdate()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down.circle.fill")
                        .foregroundStyle(.blue)
                        .font(.system(size: 12))
                    Text("v\(version) available")
                        .font(.caption)
                        .foregroundStyle(.blue)
                    Spacer()
                    Text(appState.updateService.isSourceInstall ? "Update" : "Download")
                        .font(.caption)
                        .foregroundStyle(.blue.opacity(0.8))
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    private var sidebarList: some View {
        List {
            Section {
                NewChatListRow {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        appState.createNewSession()
                    }
                }
                .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 8))
                .listRowBackground(Color.clear)
            } header: {
                sectionHeader("Chats")
            }

            if !pinnedSessions.isEmpty {
                Section {
                    ForEach(pinnedSessions) { session in
                        SessionListRow(
                            session: session,
                            isSelected: appState.activeSessionID == session.id && appState.selectedSavedChat == nil,
                            onOpen: { appState.selectSession(session) },
                            onTogglePin: {
                                appState.setSessionPinned(session, pinned: !session.isPinned)
                            },
                            onDelete: { sessionToDelete = session }
                        )
                        .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 8))
                        .listRowBackground(Color.clear)
                    }
                } header: {
                    sectionHeader("Pinned")
                }
            }

            if !recentSessionGroups.isEmpty {
                Section {
                    ForEach(recentSessionGroups) { group in
                        SessionGroupLabelRow(title: group.bucket.title)
                            .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 2, trailing: 8))
                            .listRowBackground(Color.clear)

                        ForEach(group.sessions) { session in
                            SessionListRow(
                                session: session,
                                isSelected: appState.activeSessionID == session.id && appState.selectedSavedChat == nil,
                                onOpen: { appState.selectSession(session) },
                                onTogglePin: {
                                    appState.setSessionPinned(session, pinned: !session.isPinned)
                                },
                                onDelete: { sessionToDelete = session }
                            )
                            .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 8))
                            .listRowBackground(Color.clear)
                        }
                    }
                } header: {
                    sectionHeader("Recent")
                }
            }

            Section {
                ForEach(appState.savedChats) { chat in
                    SavedChatListRow(
                        chat: chat,
                        isSelected: appState.selectedSavedChat?.id == chat.id,
                        onOpen: { appState.openSavedChat(chat) },
                        onDelete: { savedChatToDelete = chat }
                    )
                    .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 8))
                    .listRowBackground(Color.clear)
                }
            } header: {
                HStack {
                    sectionHeader("Other Chats")
                    Spacer()
                    Button {
                        isImporterPresented = true
                    } label: {
                        Image(systemName: "tray.and.arrow.down")
                    }
                    .buttonStyle(.plain)
                    .help("Import markdown chat")
                }
            }
        }
        .listStyle(.sidebar)
        .environment(\.defaultMinListRowHeight, 40)
    }

    private func sectionHeader(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(.secondary)
            .textCase(nil)
    }

    private func importDroppedFiles(_ providers: [NSItemProvider]) -> Bool {
        var handled = false

        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            handled = true
            provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                guard let data else { return }
                guard let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
                Task { @MainActor in
                    appState.importSavedChatFromDrop(url)
                }
            }
        }

        return handled
    }
}

private struct SessionGroup: Identifiable {
    let bucket: SessionBucket
    let sessions: [ChatSession]

    var id: SessionBucket {
        bucket
    }
}

private enum SessionBucket: Int, CaseIterable, Hashable {
    case today
    case yesterday
    case previous7Days
    case previous30Days
    case older

    var title: String {
        switch self {
        case .today:
            return "Today"
        case .yesterday:
            return "Yesterday"
        case .previous7Days:
            return "Previous 7 Days"
        case .previous30Days:
            return "Previous 30 Days"
        case .older:
            return "Older"
        }
    }

    static func bucket(for date: Date, calendar: Calendar = .current) -> SessionBucket {
        if calendar.isDateInToday(date) {
            return .today
        }
        if calendar.isDateInYesterday(date) {
            return .yesterday
        }

        let now = Date()
        let dayDelta = calendar.dateComponents(
            [.day],
            from: calendar.startOfDay(for: date),
            to: calendar.startOfDay(for: now)
        ).day ?? Int.max

        if dayDelta >= 0 && dayDelta <= 7 {
            return .previous7Days
        }
        if dayDelta >= 0 && dayDelta <= 30 {
            return .previous30Days
        }
        return .older
    }
}

private struct NewChatListRow: View {
    let onCreate: () -> Void

    @State private var isHovering = false

    private var backgroundFill: Color {
        isHovering ? Color.primary.opacity(0.07) : .clear
    }

    var body: some View {
        Button(action: onCreate) {
            HStack(spacing: 8) {
                Image(systemName: "plus")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)
                Text("New chat")
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(backgroundFill)
            )
            .animation(.easeInOut(duration: 0.14), value: isHovering)
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
        .onHover { hovering in
            isHovering = hovering
        }
        .accessibilityLabel("New chat")
    }
}

private struct SessionGroupLabelRow: View {
    let title: String

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.tertiary)
                .textCase(.uppercase)
            Spacer()
        }
        .padding(.horizontal, 8)
    }
}

private struct SessionListRow: View {
    let session: ChatSession
    let isSelected: Bool
    let onOpen: () -> Void
    let onTogglePin: () -> Void
    let onDelete: () -> Void

    @State private var isHovering = false

    private var displayTitle: String {
        let normalized = session.title.replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized.isEmpty ? "New Chat" : normalized
    }

    private var metadata: String {
        if session.messages.isEmpty {
            return session.createdAt.sidebarLabel
        }
        return "\(session.createdAt.sidebarLabel) · \(session.messages.count) messages"
    }

    private var backgroundFill: Color {
        if isSelected {
            return Color.accentColor.opacity(0.18)
        }
        if isHovering {
            return Color.primary.opacity(0.07)
        }
        return .clear
    }

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: isHovering || isSelected ? 3 : 0) {
                Text(displayTitle)
                    .font(.system(size: 14, weight: isSelected ? .semibold : .medium))
                    .lineLimit(1)
                    .truncationMode(.tail)

                if isHovering || isSelected {
                    Text(metadata)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button {
                onTogglePin()
            } label: {
                Image(systemName: session.isPinned ? "pin.slash" : "pin")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 26, height: 26)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .opacity(isHovering || session.isPinned ? 1 : 0)
            .allowsHitTesting(isHovering || session.isPinned)
            .help(session.isPinned ? "Unpin chat" : "Pin chat")
            .accessibilityLabel(session.isPinned ? "Unpin chat" : "Pin chat")

            Button(role: .destructive) {
                onDelete()
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 26, height: 26)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .opacity(isHovering ? 1 : 0)
            .allowsHitTesting(isHovering)
            .help("Delete chat")
            .accessibilityLabel("Delete chat")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(backgroundFill)
        )
        .animation(.easeInOut(duration: 0.14), value: isHovering)
        .animation(.easeInOut(duration: 0.14), value: isSelected)
        .contentShape(Rectangle())
        .onTapGesture {
            onOpen()
        }
        .onHover { hovering in
            isHovering = hovering
        }
        .contextMenu {
            Button(session.isPinned ? "Unpin" : "Pin") {
                onTogglePin()
            }
            Button("Delete", role: .destructive) {
                onDelete()
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Chat \(displayTitle)\(session.isPinned ? ", pinned" : "")")
        .accessibilityAction {
            onOpen()
        }
    }
}

private struct SavedChatListRow: View {
    let chat: SavedChat
    let isSelected: Bool
    let onOpen: () -> Void
    let onDelete: () -> Void

    @State private var isHovering = false

    private var displayTitle: String {
        let normalized = chat.title.replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized.isEmpty ? "Saved Chat" : normalized
    }

    private var backgroundFill: Color {
        if isSelected {
            return Color.accentColor.opacity(0.18)
        }
        if isHovering {
            return Color.primary.opacity(0.07)
        }
        return .clear
    }

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: isHovering || isSelected ? 3 : 0) {
                Text(displayTitle)
                    .font(.system(size: 14, weight: isSelected ? .semibold : .medium))
                    .lineLimit(1)
                    .truncationMode(.tail)

                if isHovering || isSelected {
                    Text(chat.dateLabel)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .accessibilityHidden(true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button(role: .destructive) {
                onDelete()
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .opacity(isHovering ? 1 : 0)
            .allowsHitTesting(isHovering)
            .help("Delete chat")
            .accessibilityLabel("Delete chat")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(backgroundFill)
        )
        .animation(.easeInOut(duration: 0.14), value: isHovering)
        .animation(.easeInOut(duration: 0.14), value: isSelected)
        .contentShape(Rectangle())
        .onTapGesture {
            onOpen()
        }
        .onHover { hovering in
            isHovering = hovering
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Saved chat \(chat.title)")
        .accessibilityAction {
            onOpen()
        }
        .contextMenu {
            Button("Delete", role: .destructive) {
                onDelete()
            }
        }
    }
}

private extension Date {
    var sidebarLabel: String {
        let calendar = Calendar.current
        let now = Date()

        if calendar.isDateInToday(self) {
            return formatted(date: .omitted, time: .shortened)
        }
        if calendar.isDateInYesterday(self) {
            return "Yesterday"
        }

        let dayDelta = calendar.dateComponents(
            [.day],
            from: calendar.startOfDay(for: self),
            to: calendar.startOfDay(for: now)
        ).day ?? Int.max

        if dayDelta >= 0 && dayDelta < 7 {
            return "\(dayDelta)d ago"
        }

        if calendar.isDate(self, equalTo: now, toGranularity: .year) {
            return formatted(.dateTime.month(.abbreviated).day())
        }
        return formatted(.dateTime.month(.abbreviated).day().year())
    }
}
