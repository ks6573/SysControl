import SwiftUI

@main
struct SysControlApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .frame(minWidth: 880, minHeight: 620)
                .tint(Theme.accent)
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unified(showsTitle: false))
        .defaultSize(width: 1100, height: 750)
        .commands {
            CommandGroup(after: .appInfo) {
                let updateService = appState.updateService
                Button("Check for Updates...") {
                    Task { await updateService.checkForUpdates(force: true) }
                }
                .keyboardShortcut("u", modifiers: [.command, .shift])
            }
            CommandGroup(replacing: .newItem) {
                Button("New Chat") {
                    appState.createNewSession()
                }
                .keyboardShortcut("n")
            }
        }

        Settings {
            SettingsView()
                .environment(appState)
        }
    }
}
