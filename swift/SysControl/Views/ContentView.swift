import SwiftUI

/// Root view — split layout with active chat sessions and saved markdown chats.
struct ContentView: View {
    @Environment(AppState.self) private var appState
    @State private var isPaletteVisible = false

    var body: some View {
        NavigationSplitView {
            SidebarView()
        } detail: {
            if let chat = appState.selectedSavedChat {
                SavedChatDetailView(
                    chat: chat,
                    content: appState.selectedSavedChatContent,
                    onClose: { appState.closeSavedChat() }
                )
            } else {
                ChatView()
            }
        }
        .navigationSplitViewStyle(.balanced)
        .sheet(isPresented: Binding(
            get: { appState.needsOnboarding },
            set: { _ in }  // non-dismissable until user completes setup
        )) {
            OnboardingView().environment(appState)
        }
        .sheet(isPresented: $isPaletteVisible) {
            CommandPalette()
                .environment(appState)
                .presentationBackground(.clear)
        }
        .background(
            Button("") {
                isPaletteVisible.toggle()
            }
            .keyboardShortcut("k", modifiers: .command)
            .opacity(0)
        )
        .onAppear {
            appState.startBackend()
        }
        .onDisappear {
            appState.stopBackend()
        }
    }

}

private struct SavedChatDetailView: View {
    let chat: SavedChat
    let content: String
    let onClose: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(chat.title)
                        .font(.headline)
                    Text(chat.dateLabel)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close") {
                    onClose()
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)

            Divider()

            ScrollView {
                LazyMarkdownText(
                    content: content,
                    style: .block,
                    font: .body,
                    foreground: .primary,
                    debounceMilliseconds: 120,
                    largeTextThreshold: 10000
                )
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 18)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}
