import AppKit
import SwiftUI

/// Centralized design tokens — SysControl accent colors, surface tints,
/// motion curves, and reading column metrics.
///
/// Single source of truth so the chat surface stays consistent if the
/// palette evolves. Avoids scattering literal `Color.primary.opacity(...)`
/// values across views.
enum Theme {
    /// Warm action accent used for primary user intent.
    static let accent = Color(red: 0.80, green: 0.47, blue: 0.36)

    /// Cool diagnostic accent used for live system state and tool output.
    static let diagnosticAccent = Color(red: 0.25, green: 0.57, blue: 0.86)

    /// Subtle warm tint for the user bubble (light/dark adaptive).
    static let userBubble = Color.primary.opacity(0.07)

    /// Hover background for sidebar rows.
    static let rowHover = Color.primary.opacity(0.06)

    /// Selected row tint.
    static let rowSelected = diagnosticAccent.opacity(0.15)

    /// Code block fill.
    static let codeFill = Color.primary.opacity(0.06)
    static let codeStroke = Color.primary.opacity(0.10)

    /// Tool card fill.
    static let toolFill = diagnosticAccent.opacity(0.08)
    static let toolStroke = diagnosticAccent.opacity(0.18)

    /// Low-contrast status surface for compact diagnostic cards.
    static let statusFill = Color.primary.opacity(0.055)
    static let statusStroke = Color.primary.opacity(0.09)

    /// Reading column max width — keeps long lines comfortable on wide displays.
    static let readingColumn: CGFloat = 740

    /// Standard Claude-style motion.
    static let motion: Animation = .smooth(duration: 0.24, extraBounce: 0.04)
}

/// NSVisualEffectView wrapper for sidebar vibrancy.
struct VisualEffectBackground: NSViewRepresentable {
    var material: NSVisualEffectView.Material = .sidebar
    var blendingMode: NSVisualEffectView.BlendingMode = .behindWindow

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {
        view.material = material
        view.blendingMode = blendingMode
    }
}
