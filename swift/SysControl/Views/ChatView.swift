import SwiftUI

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
                        MessageBubble(message: message)
                            .id(message.id)
                    }

                    if !session.activeToolNames.isEmpty {
                        ToolIndicatorRow(names: session.activeToolNames)
                            .id("tool-indicator")
                    }

                    // Streaming indicator
                    if session.isStreaming {
                        HStack {
                            TypingIndicator()
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
            ZStack {
                Circle()
                    .fill(LinearGradient(
                        colors: [.blue.opacity(0.3), .purple.opacity(0.3)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ))
                    .frame(width: 80, height: 80)
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 32))
                    .foregroundStyle(.white.opacity(0.9))
            }
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

private struct TypingIndicator: View {
    @State private var phase: CGFloat = 0

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { i in
                Circle()
                    .fill(.secondary.opacity(0.5))
                    .frame(width: 6, height: 6)
                    .offset(y: sin(phase + Double(i) * 0.8) * 3)
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: false)) {
                phase = .pi * 2
            }
        }
        .padding(.vertical, 8)
    }
}
