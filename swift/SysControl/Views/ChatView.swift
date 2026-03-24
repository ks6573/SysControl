import SwiftUI
import AppKit

/// Main chat area: message list with auto-scroll + input bar at the bottom.
struct ChatView: View {
    @Environment(AppState.self) private var appState
    @State private var pendingScrollWorkItem: DispatchWorkItem?
    @State private var lastScrollAt: Date = .distantPast

    var body: some View {
        VStack(spacing: 0) {
            // Messages
            if let session = appState.activeSession {
                if session.messages.isEmpty {
                    welcomeView
                } else {
                    messageList(session)
                }
            }

            if case .ready = appState.backendStatus { } else {
                ConnectionStatusBanner(status: appState.backendStatus) {
                    appState.retryConnection()
                }
            }

            Divider()

            // Input bar
            InputBar { text in
                appState.sendMessage(text)
            }
            .disabled(appState.activeSession?.isStreaming == true || !appState.isConnected)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    // MARK: - Messages

    private func messageList(_ session: ChatSession) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(session.messages) { message in
                        MessageBubble(
                            message: message,
                            isStreaming: session.isStreaming
                                && message.role == .assistant
                                && message.id == session.messages.last?.id
                        )
                            .id(message.id)
                    }

                    if !session.activeToolNames.isEmpty {
                        ToolIndicatorRow(names: session.activeToolNames)
                            .id("tool-indicator")
                    }

                    // Streaming indicator
                    if session.isStreaming && isAwaitingFirstToken(session) {
                        HStack {
                            ThinkingIndicator()
                                .padding(.leading, 52)
                            Spacer()
                        }
                        .id("streaming-indicator")
                    }
                }
                .padding(.vertical, 16)
            }
            .onChange(of: session.messages.count) { _, _ in
                if session.isStreaming {
                    scheduleScroll(proxy: proxy, target: "streaming-indicator", animated: true, debounce: 0.03)
                } else if let last = session.messages.last {
                    scheduleScroll(proxy: proxy, target: last.id, animated: true, debounce: 0.03)
                }
            }
            .onChange(of: session.messages.last?.content) { _, _ in
                // Auto-scroll during streaming
                if session.isStreaming {
                    scheduleScroll(proxy: proxy, target: "streaming-indicator", animated: false, debounce: 0.05)
                }
            }
            .onChange(of: session.activeToolNames) { _, _ in
                if !session.activeToolNames.isEmpty {
                    scheduleScroll(proxy: proxy, target: "tool-indicator", animated: false, debounce: 0.05)
                }
            }
            .onDisappear {
                pendingScrollWorkItem?.cancel()
            }
        }
    }

    // MARK: - Welcome

    private var welcomeView: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(nsImage: NSApplication.shared.applicationIconImage)
                .resizable()
                .interpolation(.high)
                .frame(width: 84, height: 84)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .shadow(color: .black.opacity(0.15), radius: 8, y: 3)
            Text("SysControl")
                .font(.title)
                .fontWeight(.semibold)
            Text("Your AI system monitor. Ask about CPU, memory,\ndisk, network, or any system question.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
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

private struct ToolIndicatorRow: View {
    let names: [String]

    private var label: String {
        guard let first = names.first else { return "Running tool…" }
        if names.count == 1 {
            return "●  \(first)…"
        }
        return "●  \(first) +\(names.count - 1) more…"
    }

    var body: some View {
        HStack {
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(
                    Capsule().fill(Color.primary.opacity(0.07))
                )
            Spacer()
        }
        .padding(.leading, 52)
        .padding(.vertical, 2)
    }
}

private struct ThinkingIndicator: View {
    @State private var startedAt = Date()
    private let baseText = "Thinking"
    private let tickSeconds = 0.11
    private let pulseFrequency = 3.1

    var body: some View {
        TimelineView(.periodic(from: .now, by: tickSeconds)) { timeline in
            let elapsed = timeline.date.timeIntervalSince(startedAt)
            let tick = Int(elapsed / tickSeconds)
            let cycle = baseText.count + 6
            let step = tick % max(cycle, 1)

            let letters = min(baseText.count, step + 1)
            let dots = step < baseText.count ? 0 : min(3, (step - baseText.count) % 4)
            let animatedText = String(baseText.prefix(letters)) + String(repeating: ".", count: dots)

            let pulse = 0.65 + 0.35 * (sin(elapsed * pulseFrequency) * 0.5 + 0.5)

            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary.opacity(pulse))

                ZStack(alignment: .leading) {
                    Text("Thinking...")
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(.clear)
                    Text(animatedText)
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 8)
        }
        .onAppear {
            startedAt = Date()
        }
    }
}
