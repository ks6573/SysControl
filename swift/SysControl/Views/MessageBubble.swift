import AppKit
import SwiftUI

/// A single message bubble — styled by role (user, assistant, tool).
struct MessageBubble: View {
    let message: ChatMessage
    let isStreaming: Bool
    let searchQuery: String
    let isSearchMatch: Bool
    let isFocusedSearchMatch: Bool

    @State private var showCopied = false
    @State private var isHoveringAssistantBubble = false

    private let assistantMaxReadWidth: CGFloat = 760
    private let userMaxReadWidth: CGFloat = 700

    init(
        message: ChatMessage,
        isStreaming: Bool,
        searchQuery: String = "",
        isSearchMatch: Bool = false,
        isFocusedSearchMatch: Bool = false
    ) {
        self.message = message
        self.isStreaming = isStreaming
        self.searchQuery = searchQuery
        self.isSearchMatch = isSearchMatch
        self.isFocusedSearchMatch = isFocusedSearchMatch
    }

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

    private var hasSearchQuery: Bool {
        !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var hasResponseContent: Bool {
        !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var highlightedUserContent: AttributedString {
        var rendered = AttributedString(message.content)
        guard hasSearchQuery && isSearchMatch else { return rendered }

        let highlightColor = isFocusedSearchMatch
            ? NSColor.systemYellow.withAlphaComponent(0.36)
            : NSColor.systemYellow.withAlphaComponent(0.24)

        var start = message.content.startIndex
        while start < message.content.endIndex,
              let range = message.content.range(
                  of: searchQuery,
                  options: [.caseInsensitive, .diacriticInsensitive],
                  range: start..<message.content.endIndex
              ) {
            if let attrRange = Range(range, in: rendered) {
                rendered[attrRange].backgroundColor = highlightColor
            }
            start = range.upperBound
        }
        return rendered
    }

    private var bubbleHighlightStroke: Color {
        guard hasSearchQuery else { return .clear }
        if isFocusedSearchMatch {
            return Color.yellow.opacity(0.85)
        }
        if isSearchMatch {
            return Color.yellow.opacity(0.45)
        }
        return .clear
    }

    private var bubbleHighlightLineWidth: CGFloat {
        guard hasSearchQuery else { return 0 }
        if isFocusedSearchMatch { return 2 }
        if isSearchMatch { return 1.2 }
        return 0
    }

    private var bubbleHighlightBackdrop: Color {
        guard hasSearchQuery else { return .clear }
        if isFocusedSearchMatch {
            return Color.yellow.opacity(0.14)
        }
        if isSearchMatch {
            return Color.yellow.opacity(0.07)
        }
        return .clear
    }

    // MARK: - User Bubble

    private var userBubble: some View {
        HStack(alignment: .top) {
            Spacer(minLength: 80)
            VStack(alignment: .trailing, spacing: 4) {
                if let filePath = message.attachedFilePath {
                    HStack(spacing: 5) {
                        Image(systemName: "paperclip")
                            .font(.system(size: 10))
                        Text((filePath as NSString).lastPathComponent)
                            .font(.system(size: 11))
                            .lineLimit(1)
                    }
                    .foregroundStyle(.white.opacity(0.7))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 3)
                    .background(
                        Capsule().fill(Color.white.opacity(0.15))
                    )
                }
                Text(highlightedUserContent)
                    .font(.system(size: 14))
                    .foregroundStyle(.white)
                    .lineSpacing(2)
                    .textSelection(.enabled)
            }
            .frame(maxWidth: userMaxReadWidth, alignment: .trailing)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color.accentColor)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(bubbleHighlightStroke, lineWidth: bubbleHighlightLineWidth)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(bubbleHighlightBackdrop)
        )
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

            VStack(alignment: .leading, spacing: 8) {
                if message.isError {
                    Text(message.content)
                        .font(.system(size: 14))
                        .foregroundStyle(.red.opacity(0.9))
                        .lineSpacing(2)
                        .textSelection(.enabled)
                } else {
                    // Keep rendering mode stable during streaming to minimize layout jumps.
                    LazyMarkdownText(
                        content: message.content,
                        style: .block,
                        font: .system(size: 14),
                        foreground: .primary.opacity(0.92),
                        debounceMilliseconds: isStreaming ? 140 : 20,
                        largeTextThreshold: isStreaming ? 5000 : 12000,
                        highlightQuery: isSearchMatch ? searchQuery : "",
                        isFocusedMatch: isFocusedSearchMatch
                    )
                }

                // Chart images
                if let paths = message.chartImagePaths {
                    ForEach(paths, id: \.self) { path in
                        ChartImageView(path: path)
                    }
                }

                if !message.isError {
                    HStack(spacing: 10) {
                        Button {
                            copyResponse()
                        } label: {
                            Label(showCopied ? "Copied" : "Copy", systemImage: showCopied ? "checkmark.circle.fill" : "doc.on.doc")
                                .font(.caption)
                                .fontWeight(.medium)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(showCopied ? Color.green : Color.secondary)
                        .disabled(!hasResponseContent)
                        .help("Copy response")

                        if hasSearchQuery && isSearchMatch {
                            Text(isFocusedSearchMatch ? "Current match" : "Match")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(
                                    Capsule(style: .continuous)
                                        .fill(Color.yellow.opacity(isFocusedSearchMatch ? 0.3 : 0.17))
                                )
                        }

                        Spacer(minLength: 0)

                        if isStreaming {
                            Text("Streaming…")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                    .opacity(isHoveringAssistantBubble || showCopied ? 1 : 0.88)
                    .animation(.easeInOut(duration: 0.15), value: showCopied)
                }
            }
            .frame(maxWidth: assistantMaxReadWidth, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(message.isError ? Color.red.opacity(0.06) : Color.primary.opacity(0.04))
            )
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(bubbleHighlightStroke, lineWidth: bubbleHighlightLineWidth)
            }

            Spacer(minLength: 40)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(bubbleHighlightBackdrop)
        )
        .onHover { hovering in
            isHoveringAssistantBubble = hovering
        }
    }

    private func copyResponse() {
        guard hasResponseContent else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(message.content, forType: .string)
        showCopied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            showCopied = false
        }
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

/// Displays a chart image from a file path, loading asynchronously.
private struct ChartImageView: View {
    let path: String
    @State private var nsImage: NSImage?

    var body: some View {
        Group {
            if let nsImage {
                Image(nsImage: nsImage)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: 500)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            } else {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.primary.opacity(0.05))
                    .frame(width: 200, height: 120)
                    .overlay(ProgressView().scaleEffect(0.7))
            }
        }
        .padding(.vertical, 4)
        .task(id: path) {
            if let cached = ChartImageCache.shared.object(forKey: path as NSString) {
                nsImage = cached
                return
            }
            let loaded = await Task.detached(priority: .utility) {
                NSImage(contentsOfFile: path)
            }.value
            if let loaded {
                ChartImageCache.shared.setObject(loaded, forKey: path as NSString)
            }
            nsImage = loaded
        }
    }
}

private enum ChartImageCache {
    static let shared: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 120
        return cache
    }()
}
