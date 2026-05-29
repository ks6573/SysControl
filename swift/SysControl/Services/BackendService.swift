import Foundation

/// Manages communication with the Python bridge process (`agent/bridge.py`).
/// Spawns the process, sends JSON commands via stdin, reads JSON events from stdout.
final class BackendService: @unchecked Sendable {
    // MARK: - Callbacks (set by AppState before start)
    var onReady: ((Int, String) -> Void)?          // (toolCount, model)
    var onConfigured: ((String) -> Void)?          // (model)
    var onToken: ((String) -> Void)?
    var onToolStarted: (([String]) -> Void)?
    var onToolFinished: ((String, String) -> Void)  // (name, result)
    var onChartImage: ((String) -> Void)?           // (filePath)
    var onTurnDone: ((String, Double) -> Void)?     // (finishReason, elapsed)
    var onError: ((String, String) -> Void)?         // (category, message)
    var onDisconnected: (() -> Void)?

    private var process: Process?
    private var stdinPipe: Pipe?
    private var stdoutPipe: Pipe?
    private var readTask: Task<Void, Never>?
    private var stderrReadTask: Task<Void, Never>?
    private let writeQueue = DispatchQueue(label: "com.syscontrol.backend.stdin")

    // Ring buffer of recent stderr lines for the "Show Logs" sheet.
    private let stderrLock = NSLock()
    private var stderrRing: [String] = []
    private static let stderrRingMax = 400

    /// Snapshot the most recent stderr lines (newest last).
    func recentStderr() -> String {
        stderrLock.lock()
        let copy = stderrRing
        stderrLock.unlock()
        return copy.joined(separator: "\n")
    }

    private func appendStderr(_ chunk: String) {
        let lines = chunk.split(omittingEmptySubsequences: false, whereSeparator: \.isNewline)
        stderrLock.lock()
        for line in lines {
            stderrRing.append(String(line))
            if stderrRing.count > Self.stderrRingMax {
                stderrRing.removeFirst(stderrRing.count - Self.stderrRingMax)
            }
        }
        stderrLock.unlock()
    }

    init() {
        onToolFinished = { _, _ in }
    }

    // MARK: - Lifecycle

    func start() {
        let proc = Process()
        let stdin = Pipe()
        let stdout = Pipe()
        let stderr = Pipe()

        // Find the Python venv relative to the project root.
        // The Swift app sits in swift/, so project root is ../
        let bundlePath = Bundle.main.resourcePath ?? ""
        let projectRoot: String
        if bundlePath.contains(".app/") {
            // Running from .app bundle — resources are inside the bundle
            projectRoot = bundlePath
        } else {
            // Running from Xcode or command line
            projectRoot = URL(fileURLWithPath: #file)
                .deletingLastPathComponent()  // Services/
                .deletingLastPathComponent()  // SysControl/
                .deletingLastPathComponent()  // swift/
                .deletingLastPathComponent()  // project root
                .path
        }

        let pythonPath = "\(projectRoot)/.venv/bin/python3"
        let bridgePath = "\(projectRoot)/agent/bridge.py"

        guard FileManager.default.fileExists(atPath: bridgePath) else {
            onError?("Startup", "Agent bridge not found at \(bridgePath). Please reinstall.")
            return
        }

        // Prefer the bundled venv python, but only if it actually RUNS. A
        // bundled interpreter can be present and executable yet still abort in
        // dyld at launch (e.g. a non-relocatable build whose libpython path is
        // missing, or a wrong-arch binary). isExecutableFile only checks the
        // permission bit, so we probe by launching it. Fall back to system
        // python otherwise.
        let actualPython: String
        if FileManager.default.isExecutableFile(atPath: pythonPath),
           BackendService.interpreterRuns(pythonPath) {
            actualPython = pythonPath
        } else {
            actualPython = "/usr/bin/python3"
        }

        proc.executableURL = URL(fileURLWithPath: actualPython)
        proc.arguments = ["-u", bridgePath]  // -u = unbuffered stdout
        proc.currentDirectoryURL = URL(fileURLWithPath: projectRoot)

        // Ensure bundled packages are importable even with fallback python
        var env = ProcessInfo.processInfo.environment
        let extraPaths = [projectRoot]
        if let existing = env["PYTHONPATH"] {
            env["PYTHONPATH"] = extraPaths.joined(separator: ":") + ":" + existing
        } else {
            env["PYTHONPATH"] = extraPaths.joined(separator: ":")
        }
        proc.environment = env
        proc.standardInput = stdin
        proc.standardOutput = stdout
        proc.standardError = stderr

        proc.terminationHandler = { [weak self] proc in
            guard let self else { return }
            // The continuous stderr drain (stderrReadTask) owns the pipe, so
            // read captured output from the ring buffer rather than racing it on
            // the FileHandle. Fall back to a direct read only if the ring is
            // still empty (drain task hadn't run yet).
            var stderrText = self.recentStderr()
            if stderrText.isEmpty {
                let data = stderr.fileHandleForReading.availableData
                stderrText = String(data: data, encoding: .utf8) ?? ""
            }
            if let message = BackendService.startupFailureMessage(
                exitCode: proc.terminationStatus, stderr: stderrText) {
                DispatchQueue.main.async { self.onError?("Startup", message) }
            }
            DispatchQueue.main.async {
                self.onDisconnected?()
            }
        }

        do {
            try proc.run()
        } catch {
            onError?("Startup", "Failed to start bridge: \(error.localizedDescription)")
            return
        }

        self.process = proc
        self.stdinPipe = stdin
        self.stdoutPipe = stdout

        // Read stdout in a background task
        readTask = Task.detached { [weak self] in
            self?.readLoop(stdout)
        }

        // Continuously drain stderr into the ring buffer so the UI can show
        // it on demand without holding the entire stream in memory.
        let stderrHandle = stderr.fileHandleForReading
        stderrReadTask = Task.detached { [weak self] in
            while !Task.isCancelled {
                let data = stderrHandle.availableData
                if data.isEmpty {
                    // EOF or stream closed.
                    return
                }
                if let text = String(data: data, encoding: .utf8) {
                    self?.appendStderr(text)
                }
            }
        }
    }

    func shutdown() {
        // Send shutdown synchronously so the bytes flush before SIGTERM —
        // the async writeQueue used by sendCommand could otherwise be drained
        // *after* terminate(), in which case the bridge never sees the message.
        if let pipe = stdinPipe,
           let data = try? JSONSerialization.data(withJSONObject: ["type": "shutdown"]),
           var json = String(data: data, encoding: .utf8) {
            json += "\n"
            if let payload = json.data(using: .utf8) {
                let writeHandle = pipe.fileHandleForWriting
                writeQueue.sync { writeHandle.write(payload) }
            }
        }
        readTask?.cancel()
        stderrReadTask?.cancel()
        process?.terminate()
        process = nil
    }

    // MARK: - Commands

    func sendMessage(_ text: String, sessionID: String? = nil, history: [[String: String]]? = nil) {
        var command: [String: Any] = [
            "type": "user_message",
            "text": text,
        ]
        if let sessionID, !sessionID.isEmpty {
            command["session_id"] = sessionID
        }
        if let history, !history.isEmpty {
            command["history"] = history
        }
        sendCommand(command)
    }

    func cancelRequest() {
        sendCommand(["type": "cancel"])
    }

    func clearSession(sessionID: String? = nil) {
        var command: [String: Any] = ["type": "clear_session"]
        if let sessionID, !sessionID.isEmpty {
            command["session_id"] = sessionID
        }
        sendCommand(command)
    }

    func configure(apiKey: String, baseURL: String, model: String) {
        sendCommand([
            "type": "configure",
            "api_key": apiKey,
            "base_url": baseURL,
            "model": model,
        ])
    }

    // MARK: - Private

    private func sendCommand(_ dict: [String: Any]) {
        guard let pipe = stdinPipe,
              let data = try? JSONSerialization.data(withJSONObject: dict),
              var json = String(data: data, encoding: .utf8) else { return }
        json += "\n"
        guard let payload = json.data(using: .utf8) else { return }
        // FileHandle.write is not thread-safe — concurrent calls from the
        // main actor and any background task can interleave bytes and produce
        // malformed JSON lines that the bridge cannot parse.  Serialise.
        let writeHandle = pipe.fileHandleForWriting
        writeQueue.async {
            writeHandle.write(payload)
        }
    }

    private static let newlineByte: UInt8 = 0x0A

    private func readLoop(_ pipe: Pipe) {
        let handle = pipe.fileHandleForReading
        var buffer = Data()

        while !Task.isCancelled {
            let chunk = handle.availableData
            if chunk.isEmpty {
                // EOF — process exited
                break
            }
            buffer.append(chunk)

            // Split on newlines.  Walk the buffer once per chunk; each event
            // is decoded directly from the slice so we don't allocate a new
            // String for the line and a separate Data for json parsing.
            while let newlineIdx = buffer.firstIndex(of: BackendService.newlineByte) {
                let lineData = buffer[buffer.startIndex..<newlineIdx]
                defer { buffer.removeSubrange(buffer.startIndex...newlineIdx) }
                guard !lineData.isEmpty,
                      let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                      let type = json["type"] as? String else { continue }

                dispatchEvent(type: type, json: json)
            }
        }
    }

    private func dispatchEvent(type: String, json: [String: Any]) {
        // Callers (AppState) re-enter MainActor on every callback, so this
        // function stays on the read-loop background thread.
        switch type {
        case "ready":
            let toolCount = json["tool_count"] as? Int ?? 0
            let model = json["model"] as? String ?? "unknown"
            onReady?(toolCount, model)

        case "configured":
            if let model = json["model"] as? String {
                onConfigured?(model)
            }

        case "token":
            if let text = json["text"] as? String {
                onToken?(text)
            }

        case "tool_started":
            if let names = json["names"] as? [String] {
                onToolStarted?(names)
            }

        case "tool_finished":
            let name = json["name"] as? String ?? ""
            let result = json["result"] as? String ?? ""
            onToolFinished(name, result)

        case "chart_image":
            if let path = json["path"] as? String,
               BackendService.isAllowedChartPath(path) {
                onChartImage?(path)
            }

        case "turn_done":
            let reason = json["finish_reason"] as? String ?? "stop"
            let elapsed = json["elapsed"] as? Double ?? 0
            onTurnDone?(reason, elapsed)

        case "error":
            let category = json["category"] as? String ?? "Unknown"
            let message = json["message"] as? String ?? "An error occurred"
            onError?(category, message)

        default:
            break
        }
    }

    /// Whether a Python interpreter can actually execute. A file may be present
    /// with the execute bit set yet still abort in dyld at launch (missing
    /// libpython, wrong architecture); `isExecutableFile` only checks the bit,
    /// so we probe by running a trivial isolated program with a watchdog.
    private static func interpreterRuns(_ path: String) -> Bool {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: path)
        proc.arguments = ["-I", "-c", ""]  // -I: ignore env/site — fastest probe
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
        } catch {
            return false
        }
        // A trivial probe returns in milliseconds; guard against a hang anyway.
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 5) {
            if proc.isRunning { proc.terminate() }
        }
        proc.waitUntilExit()
        return proc.terminationStatus == 0
    }

    /// Map a bridge process that died to an actionable startup message, or nil
    /// if the exit doesn't look like a known fatal cause (e.g. a clean exit or a
    /// normal SIGTERM shutdown). Distinguishes dyld/library failures — the
    /// hallmark of a broken or non-relocatable bundled runtime — from missing
    /// Python dependencies.
    static func startupFailureMessage(exitCode: Int32, stderr: String) -> String? {
        guard exitCode != 0 else { return nil }
        let snippet = String(stderr.suffix(400))
        if stderr.contains("dyld")
            || stderr.contains("Library not loaded")
            || stderr.contains("Symbol not found")
            || stderr.contains("image not found") {
            return "The bundled Python runtime failed to load (dynamic library "
                + "error). This usually means a broken install — please reinstall "
                + "the latest SysControl DMG.\n\n" + snippet
        }
        if stderr.contains("ModuleNotFoundError") || stderr.contains("ImportError") {
            return "Missing Python dependency. Please reinstall from the latest "
                + "DMG or use the source installer.\n\n" + snippet
        }
        return nil
    }

    /// Reject inline-image paths that don't live in the temp dir under one of
    /// the expected SysControl prefixes — the bridge already enforces this
    /// server-side, but a hostile MCP tool could emit arbitrary paths.
    static func isAllowedChartPath(_ path: String) -> Bool {
        let resolved = (path as NSString).resolvingSymlinksInPath
        let lastComponent = (resolved as NSString).lastPathComponent
        let allowedPrefix = lastComponent.hasPrefix("syscontrol_chart_")
            || lastComponent.hasPrefix("syscontrol_artifact_")
        guard allowedPrefix,
              lastComponent.hasSuffix(".png") else {
            return false
        }
        let tmpDir = (NSTemporaryDirectory() as NSString).resolvingSymlinksInPath
        return ["/tmp", "/private/tmp", tmpDir].contains { resolved.hasPrefix($0 + "/") }
    }
}
