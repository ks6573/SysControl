import AppKit
import SwiftUI

/// A single message — styled by role (user, assistant, tool).
/// Assistant text is unboxed and flows directly on the window background;
/// user messages get a soft tinted bubble.
struct MessageBubble: View {
    let message: ChatMessage
    let isStreaming: Bool
    let searchQuery: String
    let isSearchMatch: Bool
    let isFocusedSearchMatch: Bool

    @State private var showCopied = false
    @State private var isHoveringAssistant = false

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
            assistantBlock
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
        if isFocusedSearchMatch { return Color.yellow.opacity(0.85) }
        if isSearchMatch { return Color.yellow.opacity(0.45) }
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
        if isFocusedSearchMatch { return Color.yellow.opacity(0.14) }
        if isSearchMatch { return Color.yellow.opacity(0.07) }
        return .clear
    }

    // MARK: - User Bubble

    private var userBubble: some View {
        HStack(alignment: .top) {
            Spacer(minLength: 60)
            VStack(alignment: .trailing, spacing: 5) {
                if let filePath = message.attachedFilePath {
                    HStack(spacing: 5) {
                        Image(systemName: "paperclip")
                            .font(.system(size: 10))
                        Text((filePath as NSString).lastPathComponent)
                            .font(.system(size: 11))
                            .lineLimit(1)
                    }
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 3)
                    .background(
                        Capsule().fill(Color.primary.opacity(0.06))
                    )
                }
                Text(highlightedUserContent)
                    .font(.system(size: 14))
                    .foregroundStyle(.primary)
                    .lineSpacing(2)
                    .textSelection(.enabled)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Theme.userBubble)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(bubbleHighlightStroke, lineWidth: bubbleHighlightLineWidth)
            }
        }
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(bubbleHighlightBackdrop)
        )
    }

    // MARK: - Assistant Block (no bubble, no avatar)

    private var assistantBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            if message.isError {
                Text(message.content)
                    .font(.system(size: 14))
                    .foregroundStyle(.red.opacity(0.9))
                    .lineSpacing(2)
                    .textSelection(.enabled)
            } else {
                LazyMarkdownText(
                    content: message.content,
                    style: .block,
                    font: .system(size: 14),
                    foreground: .primary,
                    debounceMilliseconds: isStreaming ? 140 : 20,
                    largeTextThreshold: isStreaming ? 5000 : 12000,
                    highlightQuery: isSearchMatch ? searchQuery : "",
                    isFocusedMatch: isFocusedSearchMatch
                )
            }

            if let paths = message.chartImagePaths {
                ForEach(paths, id: \.self) { path in
                    ChartImageView(path: path)
                }
            }

            if !message.isError {
                actionRow
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 8)
        .padding(.horizontal, 4)
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(bubbleHighlightStroke, lineWidth: bubbleHighlightLineWidth)
        }
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(bubbleHighlightBackdrop)
        )
        .onHover { hovering in
            isHoveringAssistant = hovering
        }
    }

    private var actionRow: some View {
        HStack(spacing: 12) {
            Button {
                copyResponse()
            } label: {
                Label(showCopied ? "Copied" : "Copy", systemImage: showCopied ? "checkmark" : "doc.on.doc")
                    .labelStyle(.iconOnly)
                    .font(.system(size: 12))
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(showCopied ? Color.green : Color.secondary)
            .disabled(!hasResponseContent)
            .help(showCopied ? "Copied" : "Copy response")

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
        }
        .opacity(isHoveringAssistant || showCopied ? 1 : 0)
        .animation(.easeInOut(duration: 0.12), value: isHoveringAssistant)
        .animation(.easeInOut(duration: 0.12), value: showCopied)
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
        HStack(spacing: 6) {
            Image(systemName: message.content.hasPrefix("✓")
                  ? "checkmark.circle.fill" : "gear")
                .font(.system(size: 10))
                .foregroundStyle(message.content.hasPrefix("✓") ? .green : .orange)
            Text(message.content)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(
            Capsule().fill(Theme.toolFill)
        )
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
                    .frame(maxWidth: 540)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay {
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.primary.opacity(0.08), lineWidth: 1)
                    }
            } else {
                RoundedRectangle(cornerRadius: 10)
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
