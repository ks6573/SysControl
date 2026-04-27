import Foundation
import AppKit
import SwiftUI

/// Render markdown asynchronously with small debouncing and in-memory caching.
struct LazyMarkdownText: View {
    let content: String
    let style: MarkdownRenderStyle
    let font: Font
    let foreground: Color
    let debounceMilliseconds: UInt64
    let largeTextThreshold: Int
    let highlightQuery: String
    let isFocusedMatch: Bool
    private let autoParagraphMinLength = 180

    @State private var rendered: AttributedString?
    @State private var renderTask: Task<Void, Never>?
    @State private var renderedBlocks: [MarkdownBlock]?
    @State private var renderedBlockSource: String = ""
    // `preprocessForReadability` is a ~175-line splitter; cache so `body`
    // re-evaluations don't repeat the work for unchanged content.
    @State private var displayCache: (source: String, displayText: String) = ("", "")

    init(
        content: String,
        style: MarkdownRenderStyle = .inline,
        font: Font = .system(size: 14),
        foreground: Color = .primary,
        debounceMilliseconds: UInt64 = 90,
        largeTextThreshold: Int = 6000,
        highlightQuery: String = "",
        isFocusedMatch: Bool = false
    ) {
        self.content = content
        self.style = style
        self.font = font
        self.foreground = foreground
        self.debounceMilliseconds = debounceMilliseconds
        self.largeTextThreshold = largeTextThreshold
        self.highlightQuery = highlightQuery
        self.isFocusedMatch = isFocusedMatch
    }

    var body: some View {
        let displayText = displayCache.source == content
            ? displayCache.displayText
            : preprocessForReadability(content)
        Group {
            if style == .block {
                if let renderedBlocks, !renderedBlockSource.isEmpty {
                    RichMarkdownBlockView(
                        blocks: renderedBlocks,
                        font: font,
                        foreground: foreground,
                        highlightQuery: highlightQuery,
                        isFocusedMatch: isFocusedMatch
                    )
                } else {
                    Text(highlightedPlainText(displayText))
                }
            } else {
                if shouldParseMarkdown(displayText) {
                    if let rendered {
                        Text(highlighted(rendered, source: displayText))
                    } else {
                        Text(highlightedPlainText(displayText))
                    }
                } else {
                    Text(highlightedPlainText(displayText))
                }
            }
        }
        .font(font)
        .foregroundStyle(foreground)
        .lineSpacing(style == .block ? 4 : 2)
        .textSelection(.enabled)
        .onAppear {
            primeDisplayCache()
            scheduleRender()
        }
        .onChange(of: content) { _, _ in
            primeDisplayCache()
            scheduleRender()
        }
        .onDisappear {
            renderTask?.cancel()
        }
    }

    private func highlightedPlainText(_ text: String) -> AttributedString {
        SearchHighlightRenderer.attributed(from: text, query: highlightQuery, focused: isFocusedMatch)
    }

    private func highlighted(_ attributed: AttributedString, source: String) -> AttributedString {
        SearchHighlightRenderer.apply(
            to: attributed,
            source: source,
            query: highlightQuery,
            focused: isFocusedMatch
        )
    }

    private func primeDisplayCache() {
        if displayCache.source == content { return }
        displayCache = (content, preprocessForReadability(content))
    }

    private func scheduleRender() {
        renderTask?.cancel()
        primeDisplayCache()
        let original = content
        let snapshot = displayCache.displayText
        if snapshot.isEmpty {
            rendered = AttributedString("")
            renderedBlocks = []
            renderedBlockSource = ""
            return
        }

        if style == .block {
            let delay: UInt64 = snapshot.count > largeTextThreshold
                ? debounceMilliseconds
                : max(20, debounceMilliseconds / 3)

            renderTask = Task(priority: .utility) {
                try? await Task.sleep(nanoseconds: delay * 1_000_000)
                if Task.isCancelled { return }
                let blocks = MarkdownBlockParser.parse(snapshot)
                if Task.isCancelled { return }
                await MainActor.run {
                    if original == content {
                        renderedBlocks = blocks
                        renderedBlockSource = snapshot
                    }
                }
            }
            return
        }

        if !shouldParseMarkdown(snapshot) {
            rendered = nil
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
                if original == content {
                    rendered = parsed
                }
            }
        }
    }

    private func preprocessForReadability(_ text: String) -> String {
        let normalized = normalizeEscapedMarkdown(
            text.replacingOccurrences(of: "\r\n", with: "\n")
        )
        if normalized.count < autoParagraphMinLength
            || hasMarkdownSyntax(normalized)
            || normalized.contains("\n")
            || normalized.contains("\n\n") {
            return normalized
        }

        let sentences = splitIntoSentences(normalized)
        guard sentences.count >= 4 else { return normalized }

        let chunkSize: Int
        switch sentences.count {
        case 0...6:
            chunkSize = 2
        case 7...11:
            chunkSize = 3
        default:
            chunkSize = 4
        }
        var chunks: [String] = []
        var index = 0
        while index < sentences.count {
            let end = min(index + chunkSize, sentences.count)
            let paragraph = sentences[index..<end].joined(separator: " ")
            chunks.append(paragraph)
            index = end
        }
        return chunks.joined(separator: "\n\n")
    }

    private func normalizeEscapedMarkdown(_ text: String) -> String {
        guard style == .block else { return text }
        let escapedMarkers = ["\\*", "\\_", "\\`", "\\#", "\\|"]
        let hitCount = escapedMarkers.reduce(0) { partial, marker in
            partial + text.components(separatedBy: marker).count - 1
        }
        guard hitCount >= 2 else { return text }

        return text
            .replacingOccurrences(of: "\\*", with: "*")
            .replacingOccurrences(of: "\\_", with: "_")
            .replacingOccurrences(of: "\\`", with: "`")
            .replacingOccurrences(of: "\\#", with: "#")
            .replacingOccurrences(of: "\\|", with: "|")
    }

    private func splitIntoSentences(_ text: String) -> [String] {
        let pattern = #"(?<=[.!?])\s+"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return [text]
        }

        let nsRange = NSRange(text.startIndex..<text.endIndex, in: text)
        let matches = regex.matches(in: text, options: [], range: nsRange)
        if matches.isEmpty {
            return [text]
        }

        var sentences: [String] = []
        var cursor = text.startIndex
        for match in matches {
            guard let range = Range(match.range, in: text) else { continue }
            let sentence = text[cursor..<range.lowerBound].trimmingCharacters(in: .whitespacesAndNewlines)
            if !sentence.isEmpty {
                sentences.append(String(sentence))
            }
            cursor = range.upperBound
        }
        let tail = text[cursor...].trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty {
            sentences.append(String(tail))
        }
        return sentences
    }

    private func hasMarkdownSyntax(_ text: String) -> Bool {
        text.contains("`")
            || text.contains("*")
            || text.contains("_")
            || text.contains("[")
            || text.contains("#")
            || text.contains("- ")
            || text.contains("1. ")
            || text.contains(">")
            || text.contains("|")
            || text.contains("```")
    }

    private func hasLikelyMarkdownTable(_ text: String) -> Bool {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard lines.count >= 2 else { return false }

        var pipeRowCount = 0
        var hasSeparatorRow = false

        for lineSub in lines {
            let line = String(lineSub).trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }

            if line.contains("|") {
                pipeRowCount += 1
            }

            // Matches rows like: | --- | ---: | :---: |
            let compact = line.replacingOccurrences(of: " ", with: "")
            if compact.hasPrefix("|"),
               compact.hasSuffix("|"),
               compact.contains("---") {
                let allowed = CharacterSet(charactersIn: "|:-")
                if compact.unicodeScalars.allSatisfy({ allowed.contains($0) }) {
                    hasSeparatorRow = true
                }
            }
        }

        return pipeRowCount >= 2 && hasSeparatorRow
    }

    private func shouldParseMarkdown(_ text: String) -> Bool {
        if text.count < 16 {
            return text.contains("`")
                || text.contains("*")
                || text.contains("_")
                || text.contains("[")
        }
        if style == .block {
            // Apple's AttributedString markdown renderer tends to flatten GFM tables.
            // For table-heavy content, preserve raw markdown with line breaks.
            if hasLikelyMarkdownTable(text) {
                return false
            }
            return true
        }
        return hasMarkdownSyntax(text)
    }
}

private struct RichMarkdownBlockView: View {
    let blocks: [MarkdownBlock]
    let font: Font
    let foreground: Color
    let highlightQuery: String
    let isFocusedMatch: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case let .markdown(text):
                    StructuredMarkdownTextView(
                        content: text,
                        font: font,
                        foreground: foreground,
                        highlightQuery: highlightQuery,
                        isFocusedMatch: isFocusedMatch
                    )
                case let .table(table):
                    MarkdownTableView(
                        table: table,
                        highlightQuery: highlightQuery,
                        isFocusedMatch: isFocusedMatch
                    )
                }
            }
        }
    }
}

private struct StructuredMarkdownTextView: View {
    let content: String
    let font: Font
    let foreground: Color
    let highlightQuery: String
    let isFocusedMatch: Bool

    @State private var items: [StructuredLine] = []
    @State private var parseTask: Task<Void, Never>?
    @State private var renderedSource: String = ""

    var body: some View {
        Group {
            if renderedSource == content {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                        switch item {
                        case let .heading(level, text):
                            Text(inlineMarkdown(text))
                                .font(headingFont(level))
                                .foregroundStyle(foreground)
                        case let .bullet(text):
                            HStack(alignment: .top, spacing: 8) {
                                Text("•")
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(foreground.opacity(0.9))
                                    .padding(.top, 1)
                                Text(inlineMarkdown(text))
                                    .font(font)
                                    .foregroundStyle(foreground)
                            }
                        case let .numbered(index, text):
                            HStack(alignment: .top, spacing: 8) {
                                Text("\(index).")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(foreground.opacity(0.9))
                                    .padding(.top, 1)
                                Text(inlineMarkdown(text))
                                    .font(font)
                                    .foregroundStyle(foreground)
                            }
                        case let .paragraph(text):
                            Text(inlineMarkdown(text))
                                .font(font)
                                .foregroundStyle(foreground)
                                .lineSpacing(4)
                        case let .codeBlock(language, code):
                            CodeBlockView(language: language, code: code)
                        case .spacer:
                            Spacer()
                                .frame(height: 4)
                        }
                    }
                }
            } else {
                Text(content)
                    .font(font)
                    .foregroundStyle(foreground)
                    .lineSpacing(4)
            }
        }
        .onAppear(perform: scheduleParse)
        .onChange(of: content) { _, _ in
            scheduleParse()
        }
        .onDisappear {
            parseTask?.cancel()
        }
    }

    private func scheduleParse() {
        parseTask?.cancel()
        let snapshot = content
        if snapshot.isEmpty {
            items = []
            renderedSource = ""
            return
        }
        parseTask = Task(priority: .utility) {
            let parsed = StructuredMarkdownParser.parse(snapshot)
            if Task.isCancelled { return }
            await MainActor.run {
                if snapshot == content {
                    items = parsed
                    renderedSource = snapshot
                }
            }
        }
    }

    private func inlineMarkdown(_ text: String) -> AttributedString {
        SearchHighlightRenderer.apply(
            to: InlineMarkdownRenderCache.shared.render(text),
            source: text,
            query: highlightQuery,
            focused: isFocusedMatch
        )
    }

    private func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return .system(size: 22, weight: .bold)
        case 2: return .system(size: 19, weight: .semibold)
        case 3: return .system(size: 17, weight: .semibold)
        default: return .system(size: 16, weight: .semibold)
        }
    }
}

private struct CodeBlockView: View {
    let language: String
    let code: String

    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                if !language.isEmpty {
                    Text(language)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                } else {
                    Text("code")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(code, forType: .string)
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.25) {
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc")
                        .font(.system(size: 11, weight: .medium))
                }
                .buttonStyle(.plain)
                .foregroundStyle(copied ? Color.green : Color.secondary)
                .help("Copy code block")
            }
            .padding(.horizontal, 12)
            .padding(.top, 7)
            .padding(.bottom, 4)

            ScrollView(.horizontal, showsIndicators: true) {
                Text(SyntaxHighlighter.highlight(code, language: language))
                    .font(.system(size: 12, design: .monospaced))
                    .padding(.horizontal, 12)
                    .padding(.vertical, language.isEmpty ? 10 : 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.primary.opacity(0.08))
        )
    }
}

private enum StructuredLine: Sendable {
    case heading(level: Int, text: String)
    case bullet(text: String)
    case numbered(index: String, text: String)
    case paragraph(text: String)
    case codeBlock(language: String, code: String)
    case spacer
}

private enum StructuredMarkdownParser {
    static func parse(_ text: String) -> [StructuredLine] {
        let lines = text.replacingOccurrences(of: "\r\n", with: "\n")
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map(String.init)

        var output: [StructuredLine] = []
        var paragraphBuffer: [String] = []
        var codeBuffer: [String] = []
        var codeLanguage = ""
        var inCodeBlock = false

        func flushParagraph() {
            let lines = paragraphBuffer
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            if !lines.isEmpty {
                output.append(.paragraph(text: lines.joined(separator: "\n")))
            }
            paragraphBuffer.removeAll(keepingCapacity: true)
        }

        func flushCode() {
            let code = codeBuffer.joined(separator: "\n").trimmingCharacters(in: .newlines)
            if !code.isEmpty {
                output.append(.codeBlock(language: codeLanguage, code: code))
            }
            codeBuffer.removeAll(keepingCapacity: true)
            codeLanguage = ""
        }

        for rawLine in lines {
            let line = rawLine.trimmingCharacters(in: .whitespaces)

            if line.hasPrefix("```") {
                flushParagraph()
                if inCodeBlock {
                    flushCode()
                } else {
                    // Capture language identifier from opening fence
                    let lang = String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces).lowercased()
                    codeLanguage = lang
                }
                inCodeBlock.toggle()
                continue
            }

            if inCodeBlock {
                codeBuffer.append(rawLine)
                continue
            }

            if line.isEmpty {
                flushParagraph()
                output.append(.spacer)
                continue
            }

            if let heading = parseHeading(line) {
                flushParagraph()
                output.append(heading)
                continue
            }

            if let bullet = parseBullet(line) {
                flushParagraph()
                output.append(bullet)
                continue
            }

            if let numbered = parseNumbered(line) {
                flushParagraph()
                output.append(numbered)
                continue
            }

            paragraphBuffer.append(rawLine)
        }

        flushParagraph()
        if inCodeBlock {
            flushCode()
        }
        return collapseSpacers(output)
    }

    private static func parseHeading(_ line: String) -> StructuredLine? {
        let hashes = line.prefix { $0 == "#" }
        guard !hashes.isEmpty else { return nil }
        let level = min(hashes.count, 6)
        let rest = line.drop(while: { $0 == "#" || $0 == " " })
        guard !rest.isEmpty else { return nil }
        return .heading(level: level, text: String(rest))
    }

    private static func parseBullet(_ line: String) -> StructuredLine? {
        guard line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("+ ") else {
            return nil
        }
        return .bullet(text: String(line.dropFirst(2)))
    }

    private static func parseNumbered(_ line: String) -> StructuredLine? {
        guard let dot = line.firstIndex(of: ".") else { return nil }
        let prefix = line[..<dot]
        guard !prefix.isEmpty, prefix.allSatisfy(\.isNumber) else { return nil }
        let afterDot = line[line.index(after: dot)...]
        guard afterDot.first == " " else { return nil }
        let text = String(afterDot.dropFirst())
        return .numbered(index: String(prefix), text: text)
    }

    private static func collapseSpacers(_ items: [StructuredLine]) -> [StructuredLine] {
        var result: [StructuredLine] = []
        for item in items {
            if case .spacer = item, case .spacer = result.last {
                continue
            }
            result.append(item)
        }
        if case .spacer = result.first {
            result.removeFirst()
        }
        if case .spacer = result.last {
            result.removeLast()
        }
        return result
    }
}

private enum MarkdownBlock: Sendable {
    case markdown(String)
    case table(MarkdownTableData)
}

private struct MarkdownTableData: Sendable, Hashable {
    let headers: [String]
    let rows: [[String]]
}

private enum MarkdownBlockParser {
    static func parse(_ text: String) -> [MarkdownBlock] {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var blocks: [MarkdownBlock] = []
        var markdownBuffer: [String] = []
        var i = 0

        func flushMarkdown() {
            let text = markdownBuffer.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                blocks.append(.markdown(text))
            }
            markdownBuffer.removeAll(keepingCapacity: true)
        }

        while i < lines.count {
            if let table = parseTable(lines: lines, start: i) {
                flushMarkdown()
                blocks.append(.table(table.data))
                i = table.nextIndex
                continue
            }

            markdownBuffer.append(lines[i])
            i += 1
        }

        flushMarkdown()
        return blocks
    }

    private static func parseTable(lines: [String], start: Int) -> (data: MarkdownTableData, nextIndex: Int)? {
        guard start + 1 < lines.count else { return nil }
        let headerLine = lines[start]
        let separatorLine = lines[start + 1]

        guard isTableRow(headerLine), isSeparatorRow(separatorLine) else { return nil }
        let headers = splitCells(headerLine)
        guard !headers.isEmpty else { return nil }

        var rows: [[String]] = []
        var index = start + 2
        while index < lines.count, isTableRow(lines[index]) {
            let raw = splitCells(lines[index])
            if !raw.isEmpty {
                rows.append(normalizeRow(raw, to: headers.count))
            }
            index += 1
        }

        return (MarkdownTableData(headers: headers, rows: rows), index)
    }

    private static func isTableRow(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty || trimmed.hasPrefix("```") {
            return false
        }
        return trimmed.contains("|")
    }

    private static func isSeparatorRow(_ line: String) -> Bool {
        let compact = line.replacingOccurrences(of: " ", with: "")
        guard compact.contains("|"), compact.contains("-") else { return false }
        let allowed = CharacterSet(charactersIn: "|:-")
        return compact.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    private static func splitCells(_ line: String) -> [String] {
        var text = line.trimmingCharacters(in: .whitespaces)
        if text.hasPrefix("|") {
            text.removeFirst()
        }
        if text.hasSuffix("|") {
            text.removeLast()
        }
        return text
            .split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func normalizeRow(_ row: [String], to count: Int) -> [String] {
        if row.count == count {
            return row
        }
        if row.count > count {
            return Array(row.prefix(count))
        }
        return row + Array(repeating: "", count: count - row.count)
    }
}

private struct MarkdownTableView: View {
    let table: MarkdownTableData
    let highlightQuery: String
    let isFocusedMatch: Bool

    private let headerBackground = Color.primary.opacity(0.08)
    private let rowBackground = Color.primary.opacity(0.03)
    private let altRowBackground = Color.primary.opacity(0.05)
    private let borderColor = Color.primary.opacity(0.12)

    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
                // Header row
                GridRow {
                    ForEach(Array(table.headers.enumerated()), id: \.offset) { _, header in
                        cellView(text: header, isHeader: true)
                    }
                }
                .background(headerBackground)

                Divider().gridCellUnsizedAxes(.horizontal)

                // Data rows
                ForEach(Array(table.rows.enumerated()), id: \.offset) { rowIdx, row in
                    GridRow {
                        ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                            cellView(text: cell, isHeader: false)
                        }
                    }
                    .background(rowIdx.isMultiple(of: 2) ? rowBackground : altRowBackground)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(borderColor, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    @ViewBuilder
    private func cellView(text: String, isHeader: Bool) -> some View {
        let parsed = SearchHighlightRenderer.apply(
            to: InlineMarkdownRenderCache.shared.render(text),
            source: text,
            query: highlightQuery,
            focused: isFocusedMatch
        )

        Text(parsed)
            .font(.system(size: 13, weight: isHeader ? .semibold : .regular))
            .foregroundStyle(.primary.opacity(isHeader ? 0.98 : 0.92))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .overlay(alignment: .trailing) {
                Rectangle()
                    .fill(borderColor)
                    .frame(width: 1)
            }
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(borderColor)
                    .frame(height: 1)
            }
    }
}

private enum SearchHighlightRenderer {
    static func attributed(from text: String, query: String, focused: Bool) -> AttributedString {
        apply(to: AttributedString(text), source: text, query: query, focused: focused)
    }

    static func apply(
        to attributed: AttributedString,
        source: String,
        query: String,
        focused: Bool
    ) -> AttributedString {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return attributed }

        var rendered = attributed
        let color = focused
            ? NSColor.systemYellow.withAlphaComponent(0.36)
            : NSColor.systemYellow.withAlphaComponent(0.24)
        var start = source.startIndex
        while start < source.endIndex,
              let range = source.range(
                  of: needle,
                  options: [.caseInsensitive, .diacriticInsensitive],
                  range: start..<source.endIndex
              ) {
            if let attributedRange = Range(range, in: rendered) {
                rendered[attributedRange].backgroundColor = color
            }
            start = range.upperBound
        }
        return rendered
    }
}

private final class InlineMarkdownRenderCache {
    static let shared = InlineMarkdownRenderCache()

    private let maxEntries = 600
    private var values: [String: AttributedString] = [:]
    private var order: [String] = []
    private let lock = NSLock()

    func render(_ text: String) -> AttributedString {
        lock.lock()
        if let cached = values[text] {
            lock.unlock()
            return cached
        }
        lock.unlock()

        let rendered = (try? AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)

        lock.lock()
        values[text] = rendered
        order.append(text)
        if order.count > maxEntries {
            let overflow = order.count - maxEntries
            if overflow > 0 {
                for _ in 0..<overflow {
                    let key = order.removeFirst()
                    values.removeValue(forKey: key)
                }
            }
        }
        lock.unlock()
        return rendered
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

// MARK: - Syntax Highlighting

/// Lightweight regex-based syntax highlighter for common languages.
private enum SyntaxHighlighter {
    /// Returns an attributed string with syntax coloring applied.
    static func highlight(_ code: String, language: String) -> AttributedString {
        let rules = rules(for: language)
        guard !rules.isEmpty else {
            return AttributedString(code)
        }

        var result = AttributedString(code)
        let nsRange = NSRange(code.startIndex..., in: code)

        for rule in rules {
            guard let regex = rule.regex else { continue }
            for match in regex.matches(in: code, range: nsRange) {
                guard let range = Range(match.range, in: code),
                      let attrRange = Range(range, in: result) else { continue }
                result[attrRange].foregroundColor = rule.color
            }
        }

        return result
    }

    private struct Rule {
        let pattern: String
        let color: NSColor
        var options: NSRegularExpression.Options = []

        /// Compiled regex, cached per (pattern, options) combo.  Compilation
        /// is ~1–5 ms each — caching avoids paying that on every render.
        var regex: NSRegularExpression? { RegexCache.shared.regex(pattern: pattern, options: options) }
    }

    private final class RegexCache: @unchecked Sendable {
        static let shared = RegexCache()
        private let lock = NSLock()
        private var cache: [String: NSRegularExpression] = [:]

        func regex(pattern: String, options: NSRegularExpression.Options) -> NSRegularExpression? {
            let key = "\(options.rawValue):\(pattern)"
            lock.lock()
            if let cached = cache[key] {
                lock.unlock()
                return cached
            }
            lock.unlock()
            guard let compiled = try? NSRegularExpression(pattern: pattern, options: options) else {
                return nil
            }
            lock.lock()
            cache[key] = compiled
            lock.unlock()
            return compiled
        }
    }

    // Shared token patterns
    private static let stringPattern = #"(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"#
    private static let numberPattern = #"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"#

    private static func rules(for language: String) -> [Rule] {
        let commentColor = NSColor.systemGreen
        let stringColor = NSColor.systemOrange
        let keywordColor = NSColor.systemPink
        let numberColor = NSColor.systemPurple
        let typeColor = NSColor.systemCyan

        switch language {
        case "python", "py":
            return [
                Rule(pattern: #"#.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: #"(?:"""[\s\S]*?"""|'''[\s\S]*?''')"#, color: stringColor),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|yield|lambda|raise|pass|break|continue|and|or|not|in|is|True|False|None|async|await|self)\b"#, color: keywordColor),
            ]
        case "swift":
            return [
                Rule(pattern: #"//.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:func|var|let|class|struct|enum|protocol|import|return|if|else|guard|for|while|switch|case|default|break|continue|throw|throws|try|catch|async|await|self|Self|nil|true|false|private|public|internal|static|override|init|deinit|where|in|some|any)\b"#, color: keywordColor),
                Rule(pattern: #"\b(?:String|Int|Bool|Double|Float|Array|Dictionary|Set|Optional|Result|Void|UUID|Date|URL|Data)\b"#, color: typeColor),
            ]
        case "javascript", "js", "typescript", "ts", "jsx", "tsx":
            return [
                Rule(pattern: #"//.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: #"`(?:[^`\\]|\\.)*`"#, color: stringColor),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:function|const|let|var|return|if|else|for|while|do|switch|case|default|break|continue|throw|try|catch|finally|class|extends|import|export|from|async|await|new|this|typeof|instanceof|null|undefined|true|false|yield|of|in)\b"#, color: keywordColor),
                Rule(pattern: #"\b(?:interface|type|enum|namespace|declare|readonly|keyof|infer|never|unknown|any)\b"#, color: typeColor),
            ]
        case "bash", "sh", "shell", "zsh":
            return [
                Rule(pattern: #"#.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:if|then|else|elif|fi|for|while|do|done|case|esac|in|function|return|exit|local|export|source|alias|unset|shift|trap|eval|exec|set|unset|readonly|declare)\b"#, color: keywordColor),
            ]
        case "json":
            return [
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:true|false|null)\b"#, color: keywordColor),
            ]
        case "rust", "rs":
            return [
                Rule(pattern: #"//.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:fn|let|mut|const|struct|enum|impl|trait|pub|use|mod|self|Self|return|if|else|for|while|loop|match|break|continue|async|await|move|where|type|true|false|unsafe|extern|crate|super|ref|as|in|dyn)\b"#, color: keywordColor),
            ]
        case "go", "golang":
            return [
                Rule(pattern: #"//.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: #"`[^`]*`"#, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"\b(?:func|var|const|type|struct|interface|package|import|return|if|else|for|range|switch|case|default|break|continue|go|defer|select|chan|map|make|new|nil|true|false|fallthrough)\b"#, color: keywordColor),
            ]
        case "css", "scss":
            return [
                Rule(pattern: #"/\*[\s\S]*?\*/"#, color: commentColor),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
                Rule(pattern: #"[.#][\w-]+"#, color: keywordColor),
            ]
        case "html", "xml", "svg":
            return [
                Rule(pattern: #"<!--[\s\S]*?-->"#, color: commentColor),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: #"</?[\w-]+"#, color: keywordColor),
                Rule(pattern: #"/?\s*>"#, color: keywordColor),
            ]
        default:
            // Generic: highlight strings, numbers, and C-style comments
            if language.isEmpty { return [] }
            return [
                Rule(pattern: #"//.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: #"#.*$"#, color: commentColor, options: .anchorsMatchLines),
                Rule(pattern: stringPattern, color: stringColor),
                Rule(pattern: numberPattern, color: numberColor),
            ]
        }
    }
}
