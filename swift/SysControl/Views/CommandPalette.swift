import SwiftUI

/// Cmd+K command palette — fuzzy chat search and quick actions.
struct CommandPalette: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss

    @State private var query: String = ""
    @State private var selectedIndex: Int = 0
    @FocusState private var isFocused: Bool

    private var trimmedQuery: String {
        query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var matchingSessions: [ChatSession] {
        let q = trimmedQuery
        if q.isEmpty {
            return Array(appState.sessions.prefix(20))
        }
        return appState.sessions.filter { session in
            session.title.lowercased().contains(q)
        }
    }

    private var matchingSavedChats: [SavedChat] {
        let q = trimmedQuery
        if q.isEmpty { return [] }
        return appState.savedChats.filter { chat in
            chat.title.lowercased().contains(q)
        }
    }

    private var actionRows: [PaletteRow] {
        var rows: [PaletteRow] = []
        rows.append(PaletteRow(
            id: "action-new",
            kind: .action,
            icon: "square.and.pencil",
            title: "New Chat",
            subtitle: "⌘N"
        ))
        rows.append(contentsOf: matchingSessions.map { session in
            PaletteRow(
                id: "session-\(session.id)",
                kind: .session(session),
                icon: session.isPinned ? "pin.fill" : "bubble.left",
                title: session.title.isEmpty ? "New Chat" : session.title,
                subtitle: relativeLabel(session.createdAt)
            )
        })
        rows.append(contentsOf: matchingSavedChats.map { chat in
            PaletteRow(
                id: "saved-\(chat.id)",
                kind: .savedChat(chat),
                icon: "tray",
                title: chat.title,
                subtitle: chat.dateLabel
            )
        })
        return rows
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 14))
                    .foregroundStyle(.secondary)
                TextField("Search chats or run an action…", text: $query)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .focused($isFocused)
                    .onKeyPress(.return) {
                        invoke(at: selectedIndex)
                        return .handled
                    }
                    .onKeyPress(.upArrow) {
                        selectedIndex = max(0, selectedIndex - 1)
                        return .handled
                    }
                    .onKeyPress(.downArrow) {
                        selectedIndex = min(actionRows.count - 1, selectedIndex + 1)
                        return .handled
                    }
                    .onKeyPress(.escape) {
                        dismiss()
                        return .handled
                    }
                Text("ESC")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color.primary.opacity(0.08))
                    )
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)

            Divider().opacity(0.4)

            if actionRows.isEmpty {
                emptyState
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 2) {
                            ForEach(Array(actionRows.enumerated()), id: \.element.id) { index, row in
                                PaletteRowView(
                                    row: row,
                                    isSelected: index == selectedIndex,
                                    onInvoke: { invoke(at: index) }
                                )
                                .id(row.id)
                                .onHover { hovering in
                                    if hovering { selectedIndex = index }
                                }
                            }
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                    }
                    .frame(maxHeight: 360)
                    .onChange(of: selectedIndex) { _, new in
                        guard new < actionRows.count else { return }
                        withAnimation(.easeInOut(duration: 0.1)) {
                            proxy.scrollTo(actionRows[new].id, anchor: .center)
                        }
                    }
                }
            }
        }
        .frame(width: 540)
        .background(VisualEffectBackground(material: .hudWindow))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Color.primary.opacity(0.12), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.30), radius: 24, y: 8)
        .onAppear { isFocused = true }
        .onChange(of: query) { _, _ in selectedIndex = 0 }
    }

    private var emptyState: some View {
        VStack(spacing: 6) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 18))
                .foregroundStyle(.tertiary)
            Text("No matches")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
    }

    private func invoke(at index: Int) {
        guard index < actionRows.count else { return }
        let row = actionRows[index]
        switch row.kind {
        case .action:
            appState.createNewSession()
        case .session(let session):
            appState.selectSession(session)
        case .savedChat(let chat):
            appState.openSavedChat(chat)
        }
        dismiss()
    }

    private func relativeLabel(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

private struct PaletteRow: Identifiable {
    let id: String
    let kind: Kind
    let icon: String
    let title: String
    let subtitle: String

    enum Kind {
        case action
        case session(ChatSession)
        case savedChat(SavedChat)
    }
}

private struct PaletteRowView: View {
    let row: PaletteRow
    let isSelected: Bool
    let onInvoke: () -> Void

    var body: some View {
        Button(action: onInvoke) {
            HStack(spacing: 10) {
                Image(systemName: row.icon)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .frame(width: 16)
                Text(row.title)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 8)
                Text(row.subtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(isSelected ? Theme.accent.opacity(0.18) : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
