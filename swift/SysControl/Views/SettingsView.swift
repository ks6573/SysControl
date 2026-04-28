import SwiftUI

/// Provider configuration UI with Python GUI parity.
struct SettingsView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss

    @State private var provider: ProviderKind = .local
    @State private var localModel: String = ProviderConfiguration.localDefaultModel
    @State private var cloudAPIKey: String = ""
    @State private var cloudBaseURL: String = ProviderConfiguration.cloudBaseURL
    @State private var cloudModel: String = ProviderConfiguration.cloudDefaultModel

    @State private var localModels: [String] = []
    @State private var validationError: String?
    @State private var isRefreshingModels = false
    @State private var allowDeepResearch: Bool = false
    @State private var connectionTestResult: ConnectionTestResult?
    @State private var isTestingConnection = false

    private let permissionStore = PermissionConfigStore()

    enum ConnectionTestResult {
        case success(String)
        case failure(String)
    }

    enum ProviderKind: String, CaseIterable {
        case local
        case cloud
    }

    var body: some View {
        Form {
            Section("Provider") {
                Picker("Provider", selection: $provider) {
                    Text("Local (Ollama)").tag(ProviderKind.local)
                    Text("Cloud (Ollama Cloud)").tag(ProviderKind.cloud)
                }
                .pickerStyle(.segmented)
            }

            if provider == .local {
                Section("Local Settings") {
                    HStack(alignment: .firstTextBaseline) {
                        Picker("Model", selection: $localModel) {
                            ForEach(localModels, id: \.self) { model in
                                Text(model).tag(model)
                            }
                        }
                        .labelsHidden()
                        .frame(maxWidth: .infinity, alignment: .leading)

                        Button("Refresh") {
                            Task { await refreshLocalModels() }
                        }
                        .disabled(isRefreshingModels)
                    }

                    TextField("Manual model override", text: $localModel)
                        .help("Any locally installed Ollama model")
                }
            } else {
                Section("Cloud Settings") {
                    SecureField("API Key", text: $cloudAPIKey)
                    TextField("Base URL", text: $cloudBaseURL)
                    TextField("Model", text: $cloudModel)
                }
            }

            if let validationError {
                Section {
                    Text(validationError)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }

            Section("Tools") {
                Toggle(isOn: $allowDeepResearch) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Deep Research")
                        Text("Multi-step web research with source verification. Takes 1–3 minutes.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: allowDeepResearch) { _, newValue in
                    permissionStore.set("allow_deep_research", newValue)
                }
            }

            Section("About & Updates") {
                LabeledContent("Version", value: appState.updateService.currentVersion)

                HStack {
                    updateStatusLabel
                    Spacer()
                    updateActionButtons
                }
            }

            Section {
                HStack(spacing: 12) {
                    Button("Test Connection") {
                        Task { await testConnection() }
                    }
                    .disabled(isTestingConnection)

                    if isTestingConnection {
                        ProgressView()
                            .scaleEffect(0.6)
                            .frame(width: 14, height: 14)
                    } else if let result = connectionTestResult {
                        switch result {
                        case .success(let info):
                            HStack(spacing: 4) {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(.green)
                                Text(info)
                                    .foregroundStyle(.green)
                            }
                            .font(.caption)
                        case .failure(let error):
                            HStack(spacing: 4) {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.red)
                                Text(error)
                                    .foregroundStyle(.red)
                            }
                            .font(.caption)
                            .lineLimit(2)
                        }
                    }

                    Spacer()

                    Button("Apply & Reconnect") {
                        apply()
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 500, height: 560)
        .navigationTitle("Settings")
        .onAppear {
            loadCurrentConfiguration()
            Task { await refreshLocalModels() }
        }
    }

    @ViewBuilder
    private var updateStatusLabel: some View {
        switch appState.updateService.status {
        case .idle:
            Text("Not checked yet")
                .font(.caption)
                .foregroundStyle(.secondary)
        case .checking:
            HStack(spacing: 6) {
                ProgressView()
                    .scaleEffect(0.5)
                    .frame(width: 10, height: 10)
                Text("Checking...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        case .upToDate:
            HStack(spacing: 4) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.caption)
                Text("Up to date")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        case .available(let version, _):
            HStack(spacing: 4) {
                Image(systemName: "arrow.down.circle.fill")
                    .foregroundStyle(.blue)
                    .font(.caption)
                Text("v\(version) available")
                    .font(.caption)
                    .foregroundStyle(.blue)
            }
        case .updating:
            HStack(spacing: 6) {
                ProgressView()
                    .scaleEffect(0.5)
                    .frame(width: 10, height: 10)
                Text("Updating...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        case .failed(let message):
            HStack(spacing: 4) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.caption)
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
    }

    @ViewBuilder
    private var updateActionButtons: some View {
        let status = appState.updateService.status

        switch status {
        case .checking, .updating:
            EmptyView()
        case .available:
            HStack(spacing: 8) {
                Button(appState.updateService.isSourceInstall ? "Update Now" : "Download") {
                    appState.updateService.performUpdate()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        default:
            Button("Check Now") {
                Task { await appState.updateService.checkForUpdates(force: true) }
            }
            .controlSize(.small)
        }
    }

    private func loadCurrentConfiguration() {
        let config = appState.providerConfiguration
        if config.isLocal {
            provider = .local
            localModel = config.model
        } else {
            provider = .cloud
            cloudAPIKey = config.apiKey
            cloudBaseURL = config.baseURL
            cloudModel = config.model
        }
        allowDeepResearch = permissionStore.load()["allow_deep_research"] ?? false
    }

    private func apply() {
        validationError = nil

        let configuration: ProviderConfiguration
        switch provider {
        case .local:
            let model = localModel.trimmingCharacters(in: .whitespacesAndNewlines)
            configuration = ProviderConfiguration(
                apiKey: ProviderConfiguration.localAPIKey,
                baseURL: ProviderConfiguration.localBaseURL,
                model: model.isEmpty ? ProviderConfiguration.localDefaultModel : model,
                label: "⚙ Local (Ollama)"
            )

        case .cloud:
            let key = cloudAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if key.isEmpty {
                validationError = "Please enter your Ollama Cloud API key."
                return
            }
            let base = cloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
            let model = cloudModel.trimmingCharacters(in: .whitespacesAndNewlines)
            configuration = ProviderConfiguration(
                apiKey: key,
                baseURL: base.isEmpty ? ProviderConfiguration.cloudBaseURL : base,
                model: model.isEmpty ? ProviderConfiguration.cloudDefaultModel : model,
                label: "☁ Cloud"
            )
        }

        appState.applyProviderConfiguration(configuration)
        dismiss()
    }

    private func testConnection() async {
        isTestingConnection = true
        connectionTestResult = nil
        defer { isTestingConnection = false }

        let baseURL: String
        if provider == .local {
            baseURL = ProviderConfiguration.localBaseURL
        } else {
            let trimmed = cloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
            baseURL = trimmed.isEmpty ? ProviderConfiguration.cloudBaseURL : trimmed
        }

        // Use /api/tags for local Ollama, /models for OpenAI-compatible APIs.
        let testURL: String
        if provider == .local {
            testURL = ProviderConfiguration.localTagsURL
        } else {
            testURL = ProviderConfiguration.openAIModelsURL(fromBaseURL: baseURL)
        }

        guard let url = URL(string: testURL) else {
            connectionTestResult = .failure("Invalid URL")
            return
        }

        do {
            var request = URLRequest(url: url)
            request.timeoutInterval = 5
            if provider == .cloud {
                let key = cloudAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
                if !key.isEmpty {
                    request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
                }
            }
            let (_, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                connectionTestResult = .success("Connected")
            } else {
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                connectionTestResult = .failure("HTTP \(code)")
            }
        } catch {
            connectionTestResult = .failure(error.localizedDescription)
        }
    }

    private func refreshLocalModels() async {
        guard !isRefreshingModels else { return }
        isRefreshingModels = true
        defer { isRefreshingModels = false }

        guard let url = URL(string: ProviderConfiguration.localTagsURL) else {
            if localModels.isEmpty {
                localModels = [ProviderConfiguration.localDefaultModel]
            }
            return
        }

        do {
            var request = URLRequest(url: url)
            request.timeoutInterval = 3
            request.setValue("application/json", forHTTPHeaderField: "Accept")

            let (data, _) = try await URLSession.shared.data(for: request)
            let response = try JSONDecoder().decode(OllamaTagsResponse.self, from: data)
            let names = Array(Set(response.models.map(\.name))).sorted()
            if names.isEmpty {
                localModels = [ProviderConfiguration.localDefaultModel]
            } else {
                localModels = names
                if !names.contains(localModel) {
                    localModel = names.first ?? ProviderConfiguration.localDefaultModel
                }
            }
        } catch {
            if localModels.isEmpty {
                localModels = [localModel, ProviderConfiguration.localDefaultModel]
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
            }
        }
    }

    private struct OllamaTagsResponse: Decodable {
        let models: [Model]

        struct Model: Decodable {
            let name: String
        }
    }
}
