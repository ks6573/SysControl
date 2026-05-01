import SwiftUI

/// Bottom text input bar with send button. Supports multiline (Shift+Enter) and file attachments.
struct InputBar: View {
    let onSend: (String, String?) -> Void
    var onCancel: (() -> Void)?
    var isStreaming: Bool = false
    @Binding var attachedFilePath: String?

    @State private var text: String = ""
    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 0) {
            Spacer(minLength: 0)
            VStack(spacing: 8) {
                // Attached file chip
                if let filePath = attachedFilePath {
                    attachmentChip(filePath)
                }

                HStack(alignment: .bottom, spacing: 8) {
                    // Text editor
                    ZStack(alignment: .topLeading) {
                        if text.isEmpty {
                            Text(attachedFilePath != nil ? "Ask about this file…" : "Message SysControl…")
                                .foregroundStyle(.secondary.opacity(0.55))
                                .font(.system(size: 14))
                                .padding(.leading, 5)
                                .allowsHitTesting(false)
                        }

                        TextEditor(text: $text)
                            .font(.system(size: 14))
                            .scrollContentBackground(.hidden)
                            .focused($isFocused)
                            .frame(minHeight: 22, maxHeight: 160)
                            .fixedSize(horizontal: false, vertical: true)
                            .onKeyPress(.return, phases: .down) { press in
                                if press.modifiers.contains(.shift) {
                                    return .ignored
                                }
                                submitIfReady()
                                return .handled
                            }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)

                    // Send or Stop button
                    if isStreaming {
                        Button {
                            onCancel?()
                        } label: {
                            Image(systemName: "stop.fill")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.white)
                                .frame(width: 26, height: 26)
                                .background(
                                    Circle().fill(Color.red.opacity(0.85))
                                )
                        }
                        .buttonStyle(.plain)
                        .padding(.bottom, 4)
                        .padding(.trailing, 4)
                        .help("Stop generating")
                    } else {
                        Button {
                            submitIfReady()
                        } label: {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(canSend ? .white : .secondary)
                                .frame(width: 26, height: 26)
                                .background(
                                    Circle().fill(canSend ? Theme.accent : Color.primary.opacity(0.10))
                                )
                        }
                        .buttonStyle(.plain)
                        .padding(.bottom, 4)
                        .padding(.trailing, 4)
                        .help("Send message")
                        .disabled(!canSend)
                        .keyboardShortcut(.return, modifiers: .command)
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(Color(nsColor: .controlBackgroundColor).opacity(0.95))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.primary.opacity(isFocused ? 0.14 : 0.08), lineWidth: 1)
                )
                .animation(.easeInOut(duration: 0.15), value: isFocused)
            }
            .frame(maxWidth: 740)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 14)
        .padding(.top, 4)
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
            .help("Remove attachment")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule().fill(Color.primary.opacity(0.06))
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

        let filePath = attachedFilePath
        let displayText: String
        if trimmed.isEmpty && filePath != nil {
            displayText = "Read and summarize this file"
        } else {
            displayText = trimmed
        }

        attachedFilePath = nil
        onSend(displayText, filePath)
        text = ""
    }
}
