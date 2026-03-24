import AppKit
import Foundation
import Observation

/// Checks GitHub Releases for new versions and manages the update flow.
///
/// Two update paths depending on install method:
/// - **DMG-installed**: Opens the browser to download the latest DMG.
/// - **Source-installed** (`~/.syscontrol/build/.git` exists): Runs the
///   `syscontrol-update` script to pull, rebuild, and reinstall automatically.
@Observable
final class UpdateService {

    // MARK: - Public State

    var status: UpdateStatus = .idle

    var currentVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
    }

    var isSourceInstall: Bool {
        let gitPath = NSString("~/.syscontrol/build/.git").expandingTildeInPath
        return FileManager.default.fileExists(atPath: gitPath)
    }

    // MARK: - Private

    private static let repoOwner = "ks6573"
    private static let repoName  = "SyscontrolMCP"
    private static let apiURL    = "https://api.github.com/repos/\(repoOwner)/\(repoName)/releases/latest"
    private static let cacheKey  = "lastUpdateCheck"
    private static let cacheInterval: TimeInterval = 4 * 60 * 60  // 4 hours

    // MARK: - Check for Updates

    /// Fetch the latest release from GitHub and compare against the running version.
    ///
    /// - Parameter force: When `true`, bypasses the 4-hour rate-limit cache.
    @MainActor
    func checkForUpdates(force: Bool = false) async {
        if !force, let last = UserDefaults.standard.object(forKey: Self.cacheKey) as? Date,
           Date().timeIntervalSince(last) < Self.cacheInterval {
            return  // within cache window — skip
        }

        status = .checking

        guard let url = URL(string: Self.apiURL) else {
            status = .failed("Invalid API URL")
            return
        }

        do {
            var request = URLRequest(url: url)
            request.timeoutInterval = 10
            request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")

            let (data, response) = try await URLSession.shared.data(for: request)

            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                status = .failed("GitHub returned status \(http.statusCode)")
                return
            }

            let release = try JSONDecoder().decode(GitHubRelease.self, from: data)
            UserDefaults.standard.set(Date(), forKey: Self.cacheKey)

            let remoteVersion = release.tag_name.hasPrefix("v")
                ? String(release.tag_name.dropFirst())
                : release.tag_name

            if isNewerVersion(remote: remoteVersion, local: currentVersion) {
                let dmgAsset = release.assets.first { $0.name.hasSuffix(".dmg") }
                let downloadURL = dmgAsset.flatMap { URL(string: $0.browser_download_url) }
                    ?? URL(string: release.html_url)!
                status = .available(version: remoteVersion, downloadURL: downloadURL)
            } else {
                status = .upToDate
            }
        } catch {
            status = .failed("Could not reach GitHub")
        }
    }

    // MARK: - Perform Update

    /// Execute the appropriate update action based on install method.
    @MainActor
    func performUpdate() {
        guard case .available(_, let downloadURL) = status else { return }

        if isSourceInstall {
            runSourceUpdate()
        } else {
            NSWorkspace.shared.open(downloadURL)
        }
    }

    // MARK: - Source Update

    /// Run `syscontrol-update` in the background and report progress.
    @MainActor
    private func runSourceUpdate() {
        let scriptPath = NSString("~/.local/bin/syscontrol-update").expandingTildeInPath

        guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
            status = .failed("syscontrol-update not found at ~/.local/bin/")
            return
        }

        status = .updating
        let path = scriptPath  // capture for Sendable closure

        Task.detached {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = [path]

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                try process.run()
                process.waitUntilExit()

                let code = process.terminationStatus
                await MainActor.run { [weak self] in
                    if code == 0 {
                        self?.status = .upToDate
                    } else {
                        self?.status = .failed("Update script exited with code \(code)")
                    }
                }
            } catch {
                await MainActor.run { [weak self] in
                    self?.status = .failed("Failed to run update script")
                }
            }
        }
    }

    // MARK: - Semver Comparison

    /// Returns `true` when `remote` is strictly newer than `local`.
    private func isNewerVersion(remote: String, local: String) -> Bool {
        let r = remote.split(separator: ".").compactMap { Int($0) }
        let l = local.split(separator: ".").compactMap { Int($0) }

        for i in 0 ..< max(r.count, l.count) {
            let rv = i < r.count ? r[i] : 0
            let lv = i < l.count ? l[i] : 0
            if rv > lv { return true }
            if rv < lv { return false }
        }
        return false
    }
}

// MARK: - Types

enum UpdateStatus: Equatable {
    case idle
    case checking
    case upToDate
    case available(version: String, downloadURL: URL)
    case updating
    case failed(String)
}

// MARK: - GitHub API Model

private struct GitHubRelease: Decodable {
    let tag_name: String
    let html_url: String
    let assets: [Asset]

    struct Asset: Decodable {
        let name: String
        let browser_download_url: String
    }
}
