import SwiftUI

/// Render markdown asynchronously with small debouncing and in-memory caching.
struct LazyMarkdownText: View {
    let content: String
    let style: MarkdownRenderStyle
    let font: Font
    let foreground: Color
    let debounceMilliseconds: UInt64
    let largeTextThreshold: Int

    @State private var rendered: AttributedString?
    @State private var renderTask: Task<Void, Never>?

    init(
        content: String,
        style: MarkdownRenderStyle = .inline,
        font: Font = .system(size: 14),
        foreground: Color = .primary,
        debounceMilliseconds: UInt64 = 90,
        largeTextThreshold: Int = 6000
    ) {
        self.content = content
        self.style = style
        self.font = font
        self.foreground = foreground
        self.debounceMilliseconds = debounceMilliseconds
        self.largeTextThreshold = largeTextThreshold
    }

    var body: some View {
        Group {
            if let rendered {
                Text(rendered)
            } else {
                Text(content)
            }
        }
        .font(font)
        .foregroundStyle(foreground)
        .textSelection(.enabled)
        .onAppear(perform: scheduleRender)
        .onChange(of: content) { _, _ in
            scheduleRender()
        }
        .onDisappear {
            renderTask?.cancel()
        }
    }

    private func scheduleRender() {
        renderTask?.cancel()
        let snapshot = content
        if snapshot.isEmpty {
            rendered = AttributedString("")
            return
        }

        let delay: UInt64 = snapshot.count > largeTextThreshold
            ? debounceMilliseconds
            : max(20, debounceMilliseconds / 3)

        renderTask = Task(priority: .utility) {
            try? await Task.sleep(nanoseconds: delay * 1_000_000)
            if Task.isCancelled { return }
            let parsed = await MarkdownRenderCache.shared.render(snapshot, style: style)
            if Task.isCancelled { return }
            await MainActor.run {
                if snapshot == content {
                    rendered = parsed
                }
            }
        }
    }
}

enum MarkdownRenderStyle: Sendable, Hashable {
    case inline
    case block
}

actor MarkdownRenderCache {
    static let shared = MarkdownRenderCache()

    private struct CacheKey: Hashable {
        let style: MarkdownRenderStyle
        let digest: Int
        let count: Int
        let prefix: String
    }

    private var values: [CacheKey: AttributedString] = [:]
    private var order: [CacheKey] = []
    private let maxEntries = 120

    func render(_ text: String, style: MarkdownRenderStyle) -> AttributedString {
        var hasher = Hasher()
        hasher.combine(text)
        let key = CacheKey(
            style: style,
            digest: hasher.finalize(),
            count: text.count,
            prefix: String(text.prefix(120))
        )

        if let cached = values[key] {
            return cached
        }

        let rendered: AttributedString = {
            switch style {
            case .inline:
                return (try? AttributedString(
                    markdown: text,
                    options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
                )) ?? AttributedString(text)
            case .block:
                return (try? AttributedString(markdown: text)) ?? AttributedString(text)
            }
        }()

        values[key] = rendered
        order.append(key)
        if order.count > maxEntries {
            let overflow = order.count - maxEntries
            for _ in 0..<overflow {
                let removed = order.removeFirst()
                values.removeValue(forKey: removed)
            }
        }
        return rendered
    }
}
