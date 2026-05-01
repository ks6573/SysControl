// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SysControl",
    platforms: [
        .macOS(.v14),
    ],
    targets: [
        .executableTarget(
            name: "SysControl",
            path: "SysControl",
            exclude: [
                "Resources",
            ],
            sources: [
                "App/SysControlApp.swift",
                "App/AppState.swift",
                "App/DesignSystem.swift",
                "Models/ChatMessage.swift",
                "Models/ChatSession.swift",
                "Models/ProviderConfiguration.swift",
                "Models/SavedChat.swift",
                "Services/BackendService.swift",
                "Services/UpdateService.swift",
                "Storage/ChatHistoryManager.swift",
                "Storage/KeychainHelper.swift",
                "Storage/PersistenceManager.swift",
                "Storage/PermissionConfigStore.swift",
                "Storage/ProviderConfigStore.swift",
                "Storage/StorageQueue.swift",
                "Views/ContentView.swift",
                "Views/SidebarView.swift",
                "Views/ChatView.swift",
                "Views/MessageBubble.swift",
                "Views/LazyMarkdownText.swift",
                "Views/InputBar.swift",
                "Views/SettingsView.swift",
                "Views/OnboardingView.swift",
            ]
        ),
    ]
)
