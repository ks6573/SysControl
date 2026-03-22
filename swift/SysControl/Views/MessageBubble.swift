import SwiftUI

/// A single message bubble — styled by role (user, assistant, tool).
struct MessageBubble: View {
    let message: ChatMessage
    let isStreaming: Bool

    var body: some View {
        switch message.role {
        case .user:
            userBubble
        case .assistant:
            assistantBubble
        case .tool:
            toolIndicator
        case .system:
            EmptyView()
        }
    }

    // MARK: - User Bubble

    private var userBubble: some View {
        HStack(alignment: .top) {
            Spacer(minLength: 80)
            Text(message.content)
                .font(.system(size: 14))
                .foregroundStyle(.white)
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(Color.accentColor)
                )
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 4)
    }

    // MARK: - Assistant Bubble

    private var assistantBubble: some View {
        HStack(alignment: .top, spacing: 10) {
            // Avatar
            ZStack {
                Circle()
                    .fill(LinearGradient(
                        colors: [.blue.opacity(0.6), .purple.opacity(0.6)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ))
                    .frame(width: 28, height: 28)
                Text("S")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.white)
            }
            .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                if message.isError {
                    Text(message.content)
                        .font(.system(size: 14))
                        .foregroundStyle(.red.opacity(0.9))
                        .textSelection(.enabled)
                } else {
                    if isStreaming {
                        // Match the Python GUI behavior: immediate text updates
                        // with light, debounced markdown cleanup while streaming.
                        LazyMarkdownText(
                            content: message.content,
                            style: .inline,
                            font: .system(size: 14),
                            foreground: .primary.opacity(0.92),
                            debounceMilliseconds: 140,
                            largeTextThreshold: 4500
                        )
                    } else {
                        // Final pass: fuller markdown rendering once the turn completes.
                        LazyMarkdownText(
                            content: message.content,
                            style: .block,
                            font: .system(size: 14),
                            foreground: .primary.opacity(0.92),
                            debounceMilliseconds: 20,
                            largeTextThreshold: 12000
                        )
                    }
                }

                // Copy button (visible on hover via overlay)
                if !isStreaming && !message.content.isEmpty && !message.isError {
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(message.content, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    .buttonStyle(.plain)
                    .help("Copy response")
                }
            }

            Spacer(minLength: 40)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 4)
    }

    // MARK: - Tool Indicator

    private var toolIndicator: some View {
        HStack(alignment: .center, spacing: 8) {
            Spacer()
                .frame(width: 38)  // align with assistant text
            HStack(spacing: 5) {
                Image(systemName: message.content.hasPrefix("✓")
                      ? "checkmark.circle.fill" : "gear")
                    .font(.system(size: 10))
                    .foregroundStyle(message.content.hasPrefix("✓") ? .green : .orange)
                Text(message.content)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(Color.primary.opacity(0.06))
            )
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 1)
    }
}
