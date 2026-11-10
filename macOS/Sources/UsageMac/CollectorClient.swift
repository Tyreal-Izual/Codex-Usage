import Foundation
import Darwin

@MainActor
protocol CollectorConnection: AnyObject {
    var onDisconnect: ((String) -> Void)? { get set }
    func start() throws
    func request(_ action: String, values: [String: JSONValue]) async throws -> JSONValue
    func stop()
}

@MainActor
final class CollectorClient: CollectorConnection {
    var onDisconnect: ((String) -> Void)?
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffer = Data()
    private var nextID = 0
    private var generation = UUID()
    private var pending: [Int: CheckedContinuation<JSONValue, Error>] = [:]
    private var timeouts: [Int: Task<Void, Never>] = [:]
    private var healthProbe: Task<Void, Never>?
    private let environmentOverrides: [String: String]
    private let reportTimeout: Duration
    private let controlTimeout: Duration
    private static let ignoreBrokenPipe: Void = { _ = signal(SIGPIPE, SIG_IGN) }()

    init(environment: [String: String] = [:], reportTimeout: Duration = .seconds(120),
         controlTimeout: Duration = .seconds(15)) {
        environmentOverrides = environment
        self.reportTimeout = reportTimeout
        self.controlTimeout = controlTimeout
        _ = Self.ignoreBrokenPipe
    }

    func start() throws {
        guard process?.isRunning != true else { return }
        stop()
        let task = Process()
        let resources = Bundle.main.resourceURL
        let bundled = resources?.appendingPathComponent("helper/usage-helper")
        var environment = ProcessInfo.processInfo.environment
        environment.merge(environmentOverrides) { _, override in override }
        // Finder does not inherit the interactive shell PATH.
        environment["PATH"] = [environment["PATH"] ?? "", NSHomeDirectory() + "/.local/bin",
                               "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"].joined(separator: ":")
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUTF8"] = "1"
        if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) {
            task.executableURL = bundled
        } else {
            let root = environment["USAGE_PROJECT_DIR"].map { URL(fileURLWithPath: $0) }
                ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent()
                    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            let python = environment["USAGE_PYTHON"] ?? "/usr/bin/env"
            task.executableURL = URL(fileURLWithPath: python)
            task.arguments = (python == "/usr/bin/env" ? ["python3"] : []) + ["-B", root.appendingPathComponent("native_backend.py").path]
        }
        // Configuration is applied before any network collectors start.
        task.arguments = (task.arguments ?? []) + ["--sources", "codex,claude"]
        task.environment = environment
        let incoming = Pipe(), outgoing = Pipe()
        task.standardInput = incoming
        task.standardOutput = outgoing
        task.standardError = FileHandle.nullDevice
        let session = UUID()
        generation = session
        buffer.removeAll()
        outgoing.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            DispatchQueue.main.async {
                guard let self, self.generation == session else { return }
                if data.isEmpty { self.disconnected("Collector disconnected. Use Reconnect to try again.") }
                else { self.receive(data) }
            }
        }
        task.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.generation == session else { return }
                self.disconnected("Collector stopped. Use Reconnect to try again.")
            }
        }
        do { try task.run() }
        catch {
            outgoing.fileHandleForReading.readabilityHandler = nil
            throw BridgeError.message("Could not launch the Python collector: \(error.localizedDescription)")
        }
        process = task
        input = incoming.fileHandleForWriting
        output = outgoing.fileHandleForReading
    }

    func request(_ action: String, values: [String: JSONValue] = [:]) async throws -> JSONValue {
        try Task.checkCancellation()
        guard process?.isRunning == true, let input else {
            disconnected("Collector is not connected. Reconnect to try again.")
            throw BridgeError.message("Collector is not connected.")
        }
        nextID += 1
        let id = nextID
        var payload = values
        payload["action"] = .string(action)
        payload["id"] = .integer(id)
        var data = try JSONEncoder().encode(JSONValue.object(payload))
        data.append(0x0A)
        let timeout = action == "report" ? reportTimeout : controlTimeout
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                pending[id] = continuation
                timeouts[id] = Task { [weak self] in
                    do { try await Task.sleep(for: timeout) }
                    catch { return }
                    guard let self, self.pending[id] != nil else { return }
                    if action == "report" {
                        self.finish(id, result: .failure(BridgeError.reportTimeout))
                        self.checkHealth()
                    } else {
                        self.disconnected("Collector control request timed out. Reconnect to try again.")
                    }
                }
                do { try input.write(contentsOf: data) }
                catch { disconnected("Collector connection failed: \(error.localizedDescription)") }
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.finish(id, result: .failure(CancellationError())) }
        }
    }

    private func receive(_ data: Data) {
        buffer.append(data)
        // Reports contain metadata only. Bound a corrupt/misbehaving helper response.
        guard buffer.count <= 32 * 1024 * 1024 else {
            disconnected("Collector response exceeded the size limit. Reconnect to try again.")
            return
        }
        while let end = buffer.firstIndex(of: 0x0A) {
            let line = Data(buffer[..<end])
            buffer.removeSubrange(...end)
            do {
                let reply = try JSONDecoder().decode(BridgeReply.self, from: line)
                guard let id = reply.id else {
                    disconnected("Invalid collector response. Reconnect to try again.")
                    return
                }
                finish(id, result: reply.ok ? .success(reply.result ?? .null)
                       : .failure(BridgeError.message(reply.error ?? "Collection failed")))
            } catch {
                disconnected("Invalid collector response. Use Reconnect to try again.")
                return
            }
        }
    }

    private func finish(_ id: Int, result: Result<JSONValue, Error>) {
        timeouts.removeValue(forKey: id)?.cancel()
        pending.removeValue(forKey: id)?.resume(with: result)
    }

    private func checkHealth() {
        guard healthProbe == nil else { return }
        let session = generation
        healthProbe = Task { [weak self] in
            guard let self, self.generation == session, !Task.isCancelled else { return }
            defer { if self.generation == session { self.healthProbe = nil } }
            do {
                // hello runs on the helper's input thread, independently of report workers.
                let reply = try await self.request("hello")
                guard self.generation == session, !Task.isCancelled else { return }
                guard reply["protocol"].number == 1 else {
                    throw BridgeError.message("Invalid collector health response")
                }
            } catch {
                guard self.generation == session, !Task.isCancelled else { return }
                self.disconnected("Collector health check failed: \(error.localizedDescription)")
            }
        }
    }

    private func disconnected(_ message: String) {
        guard process != nil || input != nil || output != nil else { return }
        close(message)
        onDisconnect?(message)
    }

    private func close(_ message: String) {
        // Invalidate queued EOF/termination callbacks before releasing the session.
        generation = UUID()
        healthProbe?.cancel()
        healthProbe = nil
        let task = process
        process = nil
        task?.terminationHandler = nil
        output?.readabilityHandler = nil
        try? input?.close()
        input = nil
        try? output?.close()
        output = nil
        if let task, task.isRunning { task.terminate() }
        buffer.removeAll()
        for id in Array(pending.keys) { finish(id, result: .failure(BridgeError.message(message))) }
    }

    // Intentional shutdown must not surface a reconnect warning.
    func stop() { close("Collector stopped") }
}
