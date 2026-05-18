import SwiftUI

/// Two-step first-run onboarding sheet shown when no provider config exists.
struct OnboardingView: View {
    @Environment(AppState.self) private var appState
    @State private var step: Step = .welcome
    @State private var selectedMode: ProviderMode = .local
    @State private var apiKey: String = ""
    @State private var ollamaState: OllamaState = .unknown
    @State private var isProbingOllama = false

    enum Step { case welcome, configure }
    enum ProviderMode: String, CaseIterable {
        case local = "Local (Ollama)"
        case cloud = "Ollama Cloud"
    }

    enum OllamaState: Equatable {
        case unknown
        case running(version: String)
        case notFound
    }

    var body: some View {
        Group {
            switch step {
            case .welcome:
                welcomeStep
            case .configure:
                configureStep
            }
        }
        .frame(width: 420, height: 340)
        .interactiveDismissDisabled(true)
    }

    // MARK: - Step 1: Welcome

    private var welcomeStep: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(nsImage: NSApplication.shared.applicationIconImage)
                .resizable()
                .interpolation(.high)
                .frame(width: 80, height: 80)
                .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
                .shadow(color: .black.opacity(0.15), radius: 8, y: 3)

            VStack(spacing: 8) {
                Text("Welcome to SysControl")
                    .font(.title2)
                    .fontWeight(.semibold)
                Text("Your AI-powered system monitor.\nLet's set up your AI provider to get started.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            Spacer()

            Button {
                withAnimation(.easeInOut(duration: 0.2)) { step = .configure }
            } label: {
                Text("Get Started →")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
            .padding(.horizontal, 40)
            .padding(.bottom, 28)
        }
        .padding(.horizontal, 32)
    }

    // MARK: - Step 2: Configure Provider

    private var configureStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Configure your AI provider")
                .font(.title3)
                .fontWeight(.semibold)
                .padding(.top, 28)

            Picker("Provider", selection: $selectedMode) {
                ForEach(ProviderMode.allCases, id: \.self) { mode in
                    Text(mode.rawValue).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            if selectedMode == .local {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Uses Ollama running locally — no API key needed.")
                        .font(.callout)
                        .foregroundStyle(.secondary)

                    ollamaStatusRow

                    if case .notFound = ollamaState {
                        HStack(spacing: 10) {
                            Link("Install Ollama",
                                 destination: URL(string: "https://ollama.com/download/mac")!)
                                .font(.caption)
                                .buttonStyle(.bordered)
                            Button("I'll start it") {
                                Task { await probeOllama() }
                            }
                            .font(.caption)
                            .buttonStyle(.bordered)
                        }
                    }
                }
                .onAppear { Task { await probeOllama() } }
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("API Key")
                        .font(.callout)
                        .fontWeight(.medium)
                    SecureField("Paste your API key here", text: $apiKey)
                        .textFieldStyle(.roundedBorder)
                    Text("Your key is stored securely in the macOS Keychain on this Mac.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer()

            HStack {
                Button("Back") {
                    withAnimation(.easeInOut(duration: 0.2)) { step = .welcome }
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)

                Spacer()

                Button("Done") {
                    finish()
                }
                .buttonStyle(.borderedProminent)
                .disabled(doneIsDisabled)
            }
            .padding(.bottom, 24)
        }
        .padding(.horizontal, 32)
    }

    private var doneIsDisabled: Bool {
        if selectedMode == .cloud && apiKey.trimmingCharacters(in: .whitespaces).isEmpty {
            return true
        }
        // Local: warn-only — we still let the user proceed if probing failed,
        // so an offline first-run still completes (configuration is editable).
        return false
    }

    @ViewBuilder
    private var ollamaStatusRow: some View {
        switch ollamaState {
        case .unknown:
            HStack(spacing: 6) {
                if isProbingOllama {
                    ProgressView().scaleEffect(0.55).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "circle.dashed")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text("Checking Ollama…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        case .running(let version):
            HStack(spacing: 6) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.caption)
                Text("Ollama detected (v\(version))")
                    .font(.caption)
                    .foregroundStyle(.green)
            }
        case .notFound:
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.caption)
                Text("Ollama not detected at localhost:11434")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
    }

    private func probeOllama() async {
        isProbingOllama = true
        defer { isProbingOllama = false }
        guard let url = URL(string: "http://localhost:11434/api/version") else {
            ollamaState = .notFound
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 2
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                ollamaState = .notFound
                return
            }
            let decoded = try? JSONDecoder().decode(OllamaVersion.self, from: data)
            ollamaState = .running(version: decoded?.version ?? "?")
        } catch {
            ollamaState = .notFound
        }
    }

    private struct OllamaVersion: Decodable {
        let version: String
    }

    // MARK: - Helpers

    private func finish() {
        let config: ProviderConfiguration
        if selectedMode == .local {
            config = .localDefault
        } else {
            config = ProviderConfiguration(
                apiKey: apiKey.trimmingCharacters(in: .whitespaces),
                baseURL: ProviderConfiguration.cloudBaseURL,
                model: ProviderConfiguration.cloudDefaultModel,
                label: "☁ Ollama Cloud"
            )
        }
        appState.completeOnboarding(config)
    }
}
