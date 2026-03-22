import SwiftUI

@main
struct SysControlApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .frame(minWidth: 900, minHeight: 640)
        }
        .windowStyle(.titleBar)
        .defaultSize(width: 1100, height: 750)
        .commands {
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
