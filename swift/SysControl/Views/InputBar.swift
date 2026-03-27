import SwiftUI

/// Bottom text input bar with send button. Supports multiline (Shift+Enter) and file attachments.
struct InputBar: View {
    let onSend: (String) -> Void
    @Binding var attachedFilePath: String?

    @State private var text: String = ""
    @FocusState private var isFocused: Bool

    var body: some View {
        VStack(spacing: 6) {
            // Attached file chip
            if let filePath = attachedFilePath {
                attachmentChip(filePath)
            }

            HStack(alignment: .bottom, spacing: 10) {
                // Text editor
                ZStack(alignment: .topLeading) {
                    // Placeholder
                    if text.isEmpty {
                        Text(attachedFilePath != nil ? "Ask about this file…" : "Message SysControl…")
                            .foregroundStyle(.tertiary)
                            .font(.system(size: 14))
                            .padding(.leading, 5)
                            .allowsHitTesting(false)
                    }

                    TextEditor(text: $text)
                        .font(.system(size: 14))
                        .scrollContentBackground(.hidden)
                        .focused($isFocused)
                        .frame(minHeight: 20, maxHeight: 120)
                        .fixedSize(horizontal: false, vertical: true)
                        .onKeyPress(.return, phases: .down) { press in
                            if press.modifiers.contains(.shift) {
                                return .ignored  // Let shift+enter insert newline
                            }
                            submitIfReady()
                            return .handled
                        }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(Color.primary.opacity(0.1), lineWidth: 1)
                )

                // Send button
                Button {
                    submitIfReady()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 28))
                        .foregroundStyle(canSend ? Color.accentColor : Color.secondary.opacity(0.3))
                }
                .buttonStyle(.plain)
                .disabled(!canSend)
                .keyboardShortcut(.return, modifiers: .command)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .onAppear { isFocused = true }
    }

    // MARK: - Attachment Chip

    private func attachmentChip(_ path: String) -> some View {
        let filename = (path as NSString).lastPathComponent
        let icon = fileIcon(for: filename)

        return HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Text(filename)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(1)
                .truncationMode(.middle)
            Button {
                attachedFilePath = nil
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule().fill(Color.accentColor.opacity(0.12))
        )
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func fileIcon(for filename: String) -> String {
        let ext = (filename as NSString).pathExtension.lowercased()
        switch ext {
        case "pdf":                    return "doc.richtext"
        case "xlsx", "xls", "csv":     return "tablecells"
        case "docx", "doc":            return "doc.text"
        case "txt", "md", "rst":       return "doc.plaintext"
        default:                       return "doc"
        }
    }

    // MARK: - Send Logic

    private var canSend: Bool {
        let hasText = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return hasText || attachedFilePath != nil
    }

    private func submitIfReady() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || attachedFilePath != nil else { return }

        var message = ""
        if let filePath = attachedFilePath {
            let filename = (filePath as NSString).lastPathComponent
            if trimmed.isEmpty {
                message = "Read and summarize this file: \(filePath)"
            } else {
                message = "[Attached file: \(filename) (\(filePath))]\n\n\(trimmed)"
            }
            attachedFilePath = nil
        } else {
            message = trimmed
        }

        onSend(message)
        text = ""
    }
}
