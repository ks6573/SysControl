import SwiftUI

/// Two-step first-run onboarding sheet shown when no provider config exists.
struct OnboardingView: View {
    @Environment(AppState.self) private var appState
    @State private var step: Step = .welcome
    @State private var selectedMode: ProviderMode = .local
    @State private var apiKey: String = ""

    enum Step { case welcome, configure }
    enum ProviderMode: String, CaseIterable {
        case local = "Local (Ollama)"
        case cloud = "Cloud"
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
                VStack(alignment: .leading, spacing: 6) {
                    Text("Uses Ollama running locally — no API key needed.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Text("Make sure Ollama is installed and running before continuing.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
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
                .disabled(selectedMode == .cloud && apiKey.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.bottom, 24)
        }
        .padding(.horizontal, 32)
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
                label: "☁ Cloud"
            )
        }
        appState.completeOnboarding(config)
    }
}
