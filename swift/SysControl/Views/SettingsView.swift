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
    @State private var cloudModels: [String] = []
    @State private var isRefreshingCloudModels = false
    @State private var cloudRefreshError: String?
    @State private var validationError: String?
    @State private var isRefreshingModels = false
    @State private var allowDeepResearch: Bool = false
    @State private var allowClipboard: Bool = false
    @State private var connectionTestResult: ConnectionTestResult?
    @State private var isTestingConnection = false
    @State private var lastTestedEndpoint: String = ""

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
                    Text("Ollama Cloud").tag(ProviderKind.cloud)
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
                        .onChange(of: cloudAPIKey) { _, _ in
                            cloudModels = []
                            cloudRefreshError = nil
                        }
                    TextField("Base URL", text: $cloudBaseURL)
                    HStack(alignment: .firstTextBaseline) {
                        if cloudModels.isEmpty {
                            TextField("Model", text: $cloudModel)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        } else {
                            Picker("Model", selection: $cloudModel) {
                                ForEach(cloudModels, id: \.self) { model in
                                    Text(model).tag(model)
                                }
                                if !cloudModels.contains(cloudModel) && !cloudModel.isEmpty {
                                    Text("\(cloudModel) (custom)").tag(cloudModel)
                                }
                            }
                            .labelsHidden()
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        Button {
                            Task { await refreshCloudModels() }
                        } label: {
                            if isRefreshingCloudModels {
                                ProgressView().scaleEffect(0.55).frame(width: 12, height: 12)
                            } else {
                                Text("Fetch Models")
                            }
                        }
                        .disabled(isRefreshingCloudModels || cloudAPIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    if let err = cloudRefreshError {
                        Text(err)
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
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

                Toggle(isOn: $allowClipboard) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Clipboard Access")
                        Text("Read and write the system clipboard. Off by default — clipboards often hold passwords or 2FA codes.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: allowClipboard) { _, newValue in
                    permissionStore.set("allow_clipboard", newValue)
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
                VStack(alignment: .leading, spacing: 8) {
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
                    if !lastTestedEndpoint.isEmpty {
                        Text("Tested endpoint: \(lastTestedEndpoint)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .lineLimit(2)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(minWidth: 580, idealWidth: 620, minHeight: 640, idealHeight: 740)
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
        let permissions = permissionStore.load()
        allowDeepResearch = permissions["allow_deep_research"] ?? false
        allowClipboard = permissions["allow_clipboard"] ?? false
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
                label: "☁ Ollama Cloud"
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
            lastTestedEndpoint = testURL
            return
        }
        lastTestedEndpoint = testURL

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

    private func refreshCloudModels() async {
        guard !isRefreshingCloudModels else { return }
        let key = cloudAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else {
            cloudRefreshError = "Enter your API key first."
            return
        }
        isRefreshingCloudModels = true
        cloudRefreshError = nil
        defer { isRefreshingCloudModels = false }

        let base = cloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let urlString = ProviderConfiguration.openAIModelsURL(
            fromBaseURL: base.isEmpty ? ProviderConfiguration.cloudBaseURL : base
        )
        guard let url = URL(string: urlString) else {
            cloudRefreshError = "Invalid base URL"
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 5
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                cloudRefreshError = "HTTP \(http.statusCode) from \(urlString)"
                return
            }
            let decoded = try JSONDecoder().decode(OpenAIModelsResponse.self, from: data)
            let names = decoded.data.map(\.id).sorted()
            if names.isEmpty {
                cloudRefreshError = "No models returned"
                return
            }
            cloudModels = names
            if !names.contains(cloudModel) {
                cloudModel = names.first ?? cloudModel
            }
        } catch {
            cloudRefreshError = error.localizedDescription
        }
    }

    private struct OpenAIModelsResponse: Decodable {
        let data: [Model]
        struct Model: Decodable {
            let id: String
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
