import SwiftUI
import UniformTypeIdentifiers

/// Left sidebar: current sessions + saved markdown chats.
struct SidebarView: View {
    @Environment(AppState.self) private var appState
    @State private var isImporterPresented = false
    @State private var sessionToDelete: ChatSession?
    @State private var savedChatToDelete: SavedChat?

    private var markdownType: UTType {
        UTType(filenameExtension: "md") ?? .plainText
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
            Section("Chats") {
                ForEach(appState.sessions) { session in
                    Button {
                        appState.selectSession(session)
                    } label: {
                        SessionRow(session: session)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(
                        appState.activeSessionID == session.id && appState.selectedSavedChat == nil
                            ? Color.accentColor.opacity(0.14)
                            : Color.clear
                    )
                    .contextMenu {
                        Button("Delete", role: .destructive) {
                            sessionToDelete = session
                        }
                    }
                }
            }

            Section {
                ForEach(appState.savedChats) { chat in
                    SavedChatListRow(
                        chat: chat,
                        onOpen: { appState.openSavedChat(chat) },
                        onDelete: { savedChatToDelete = chat }
                    )
                    .listRowBackground(
                        appState.selectedSavedChat?.id == chat.id
                            ? Color.accentColor.opacity(0.14)
                            : Color.clear
                    )
                }
            } header: {
                HStack {
                    Text("Other Chats")
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

private struct SessionRow: View {
    let session: ChatSession

    private var messagePreview: String? {
        guard let first = session.messages.first(where: { $0.role == .user }) else { return nil }
        let text = first.content.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : String(text.prefix(50))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(session.title)
                .font(.system(size: 13, weight: .medium))
                .lineLimit(1)
                .truncationMode(.tail)
            if let preview = messagePreview {
                Text(preview)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            HStack(spacing: 4) {
                Text(session.createdAt, style: .relative)
                if !session.messages.isEmpty {
                    Text("·")
                    Text("\(session.messages.count) messages")
                }
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
    }
}

private struct SavedChatRow: View {
    let chat: SavedChat

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(chat.title)
                .font(.system(size: 13, weight: .medium))
                .lineLimit(1)
                .truncationMode(.tail)
            Text(chat.dateLabel)
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
    }
}

private struct SavedChatListRow: View {
    let chat: SavedChat
    let onOpen: () -> Void
    let onDelete: () -> Void

    @State private var isHovering = false

    var body: some View {
        HStack(spacing: 8) {
            SavedChatRow(chat: chat)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(role: .destructive) {
                onDelete()
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 12, weight: .semibold))
                    .frame(width: 30, height: 30)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .opacity(isHovering ? 1 : 0)
            .allowsHitTesting(isHovering)
            .help("Delete chat")
            .accessibilityLabel("Delete chat")
        }
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
