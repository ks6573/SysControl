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
            sidebarList
            Divider().opacity(0.4)
            footer
        }
        .background(VisualEffectBackground(material: .sidebar))
        .navigationSplitViewColumnWidth(min: 260, ideal: 292, max: 380)
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
        HStack(spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Theme.diagnosticAccent.opacity(0.16))
                Image(systemName: "cpu")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.diagnosticAccent)
            }
            .frame(width: 26, height: 26)

            VStack(alignment: .leading, spacing: 1) {
                Text("SysControl")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.primary)
                Text("System Observatory")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()
            Button {
                withAnimation(Theme.motion) {
                    appState.createNewSession()
                }
            } label: {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 26, height: 26)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("New Chat (⌘N)")
        }
        .padding(.horizontal, 14)
        .padding(.top, 16)
        .padding(.bottom, 8)
    }

    @ViewBuilder
    private var footer: some View {
        VStack(spacing: 8) {
            updateBanner
            connectionStatus
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private var connectionStatus: some View {
        let state = sidebarConnectionState

        HStack(spacing: 9) {
            ZStack {
                Circle()
                    .fill(state.tint.opacity(0.16))
                Image(systemName: state.icon)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(state.tint)
            }
            .frame(width: 24, height: 24)

            VStack(alignment: .leading, spacing: 1) {
                Text(state.title)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.primary.opacity(0.9))
                    .lineLimit(1)
                Text(state.detail)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Theme.statusFill)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Theme.statusStroke, lineWidth: 1)
        }
    }

    private var sidebarConnectionState: SidebarConnectionState {
        if appState.isConnected {
            return SidebarConnectionState(
                icon: "checkmark.circle.fill",
                tint: .green,
                title: "Backend online",
                detail: "\(appState.toolCount) tools · \(appState.modelName)"
            )
        }

        if let error = appState.connectionError {
            return SidebarConnectionState(
                icon: "exclamationmark.triangle.fill",
                tint: .red,
                title: "Backend offline",
                detail: error
            )
        }

        return SidebarConnectionState(
            icon: "antenna.radiowaves.left.and.right",
            tint: .orange,
            title: "Connecting",
            detail: "Starting local bridge"
        )
    }

    @ViewBuilder
    private var updateBanner: some View {
        if case .available(let version, _) = appState.updateService.status {
            Button {
                appState.updateService.performUpdate()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down.circle.fill")
                        .foregroundStyle(Theme.accent)
                        .font(.system(size: 12))
                    Text("v\(version) available")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Theme.accent)
                    Spacer()
                    Text(appState.updateService.isSourceInstall ? "Update" : "Download")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.accent.opacity(0.8))
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(Theme.accent.opacity(0.1))
                )
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    private var sidebarList: some View {
        List {
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
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.6)
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
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

private struct SidebarConnectionState {
    let icon: String
    let tint: Color
    let title: String
    let detail: String
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

private struct SessionGroupLabelRow: View {
    let title: String

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .tracking(0.6)
                .foregroundStyle(.secondary)
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

    private var backgroundFill: Color {
        if isSelected { return Theme.rowSelected }
        if isHovering { return Theme.rowHover }
        return .clear
    }

    private var rowIcon: String {
        if session.isStreaming { return "waveform.path.ecg" }
        if session.isPinned { return "pin.fill" }
        if session.messages.isEmpty { return "plus.message" }
        return "bubble.left.and.bubble.right"
    }

    private var detailText: String {
        if session.isStreaming {
            if let activeTool = session.activeToolNames.first {
                return "Running \(activeTool)"
            }
            return "Generating response"
        }
        if session.messages.isEmpty {
            return "Ready for diagnostics"
        }
        return "\(session.messages.count) messages · \(session.createdAt.sidebarLabel)"
    }

    var body: some View {
        HStack(spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(isSelected ? Theme.diagnosticAccent.opacity(0.18) : Color.primary.opacity(0.055))
                Image(systemName: rowIcon)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(isSelected ? Theme.diagnosticAccent : .secondary)
            }
            .frame(width: 22, height: 22)

            VStack(alignment: .leading, spacing: 2) {
                Text(displayTitle)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(.primary.opacity(isSelected ? 1 : 0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)

                Text(detailText)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button {
                onTogglePin()
            } label: {
                Image(systemName: session.isPinned ? "pin.slash" : "pin")
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 22, height: 22)
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
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 22, height: 22)
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
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(backgroundFill)
        )
        .overlay(alignment: .leading) {
            if isSelected {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(Theme.diagnosticAccent)
                    .frame(width: 3)
                    .padding(.vertical, 7)
            }
        }
        .animation(.easeInOut(duration: 0.12), value: isHovering)
        .animation(.easeInOut(duration: 0.12), value: isSelected)
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
        if isSelected { return Theme.rowSelected }
        if isHovering { return Theme.rowHover }
        return .clear
    }

    var body: some View {
        HStack(spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(isSelected ? Theme.accent.opacity(0.18) : Color.primary.opacity(0.055))
                Image(systemName: "doc.text")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(isSelected ? Theme.accent : .secondary)
            }
            .frame(width: 22, height: 22)

            VStack(alignment: .leading, spacing: 2) {
                Text(displayTitle)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(.primary.opacity(isSelected ? 1 : 0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)

                Text(chat.dateLabel)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button(role: .destructive) {
                onDelete()
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 22, height: 22)
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
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(backgroundFill)
        )
        .overlay(alignment: .leading) {
            if isSelected {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(Theme.accent)
                    .frame(width: 3)
                    .padding(.vertical, 7)
            }
        }
        .animation(.easeInOut(duration: 0.12), value: isHovering)
        .animation(.easeInOut(duration: 0.12), value: isSelected)
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
