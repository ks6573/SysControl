import SwiftUI

@main
struct SysControlApp: App {
    @State private var appState = AppState()

    // Remember the window frame across launches so users don't lose their
    // preferred layout.  We store width × height as a serialized string.
    @AppStorage("syscontrol.windowFrame") private var windowFrame: String = ""

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .frame(minWidth: 880, minHeight: 620)
                .tint(Theme.accent)
                .background(WindowFramePersistence(frame: $windowFrame))
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unified(showsTitle: false))
        .defaultSize(width: 1100, height: 750)
        .commands {
            CommandGroup(after: .appInfo) {
                let updateService = appState.updateService
                Button("Check for Updates...") {
                    Task { await updateService.checkForUpdates(force: true) }
                }
                .keyboardShortcut("u", modifiers: [.command, .shift])
            }
            CommandGroup(replacing: .newItem) {
                Button("New Chat") {
                    appState.createNewSession()
                }
                .keyboardShortcut("n")
                Button("New Chat (keep pinned)") {
                    appState.createNewSession()
                }
                .keyboardShortcut("k", modifiers: [.command, .shift])
            }
            // ── Chat actions ────────────────────────────────────────────────
            CommandMenu("Chat") {
                Button("Regenerate Last Response") {
                    appState.regenerateLast()
                }
                .keyboardShortcut("r", modifiers: [.command])
                .disabled(appState.activeSession?.messages.contains(where: { $0.role == .user }) != true)

                Button("Export Conversation…") {
                    exportActiveSession(appState: appState)
                }
                .keyboardShortcut("e", modifiers: [.command])
                .disabled(appState.activeSession?.messages.isEmpty != false)

                Divider()

                Button("Archive Session") {
                    if let session = appState.activeSession {
                        appState.setSessionArchived(session, archived: true)
                    }
                }
                .keyboardShortcut("w", modifiers: [.command])
                .disabled(appState.activeSession == nil)

                Divider()

                ForEach(1...9, id: \.self) { index in
                    sessionShortcut(index: index)
                }
            }
        }

        Settings {
            SettingsView()
                .environment(appState)
        }
    }

    @ViewBuilder
    private func sessionShortcut(index: Int) -> some View {
        Button("Session \(index)") {
            appState.selectSession(at: index)
        }
        .keyboardShortcut(KeyEquivalent(Character("\(index)")), modifiers: [.command])
    }

    private func exportActiveSession(appState: AppState) {
        let panel = NSSavePanel()
        panel.title = "Export Conversation"
        panel.allowedContentTypes = [.init(filenameExtension: "md") ?? .plainText]
        let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        let defaultName = appState.activeSession?.title.replacingOccurrences(of: "/", with: "-") ?? "syscontrol-session"
        panel.nameFieldStringValue = "\(defaultName)-\(stamp).md"
        if panel.runModal() == .OK, let url = panel.url {
            appState.exportActiveSession(to: url)
        }
    }
}

/// Backs the window's NSWindow into `@AppStorage` so size+position survive
/// relaunches.  Uses a transparent background NSViewRepresentable to grab the
/// host window at first appear, then listens for resize / move notifications.
private struct WindowFramePersistence: NSViewRepresentable {
    @Binding var frame: String

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            context.coordinator.attach(to: window, binding: $frame)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        // No-op; coordinator handles observation.
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject {
        private var observers: [NSObjectProtocol] = []
        private weak var window: NSWindow?
        private var binding: Binding<String>?

        func attach(to window: NSWindow, binding: Binding<String>) {
            self.window = window
            self.binding = binding
            // Restore frame from persisted string if present.
            if let restored = NSRect(from: binding.wrappedValue) {
                window.setFrame(restored, display: true, animate: false)
            }
            let nc = NotificationCenter.default
            observers.append(nc.addObserver(forName: NSWindow.didMoveNotification,
                                            object: window, queue: .main) { [weak self] _ in
                self?.persist()
            })
            observers.append(nc.addObserver(forName: NSWindow.didResizeNotification,
                                            object: window, queue: .main) { [weak self] _ in
                self?.persist()
            })
        }

        private func persist() {
            guard let window, let binding else { return }
            binding.wrappedValue = window.frame.stringRepresentation
        }

        deinit {
            for token in observers { NotificationCenter.default.removeObserver(token) }
        }
    }
}

private extension NSRect {
    init?(from string: String) {
        let parts = string.split(separator: ",").map(String.init)
        guard parts.count == 4,
              let x = Double(parts[0]), let y = Double(parts[1]),
              let w = Double(parts[2]), let h = Double(parts[3]),
              w > 200, h > 200 else { return nil }
        self.init(x: x, y: y, width: w, height: h)
    }
    var stringRepresentation: String {
        "\(origin.x),\(origin.y),\(size.width),\(size.height)"
    }
}
