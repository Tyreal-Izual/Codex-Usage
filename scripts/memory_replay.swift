import AppKit
import Darwin
import SwiftUI

// Standalone diagnostic app, excluded from Usage.app; all responses are synthetic.
@MainActor
private final class ReplayCollector: CollectorConnection {
    var onDisconnect: ((String) -> Void)?
    var iteration = -1
    var changingValues = false
    var valueEvery = 1
    var requestsSent = 0
    private var reports = DemoData.reports
    func start() { }
    func stop() { }
    func request(_ action: String, values: [String: JSONValue]) async throws -> JSONValue {
        try Task.checkCancellation()
        await Task.yield()
        if action == "hello" { return .object(["protocol": .integer(1), "admin_enabled": .bool(false)]) }
        if action == "configure" { return .object(["ok": .bool(true)]) }
        guard let report = Report(rawValue: values["report"]?.text ?? ""), let previous = reports[report] else {
            throw BridgeError.message("Unknown replay report")
        }
        requestsSent += 1
        var value = previous.object
        if changingValues && iteration >= 0 && iteration % valueEvery == 0 && (report == .local || report == .claude) {
            let key = report == .local ? "sqlite_threads" : "local_usage"
            var section = value[key]!.object
            var metrics = report == .local ? section["selected"]!.object : section
            var rows = metrics["by_model"]!.items
            var first = rows[0].object
            let tokenKey = report == .local ? "tokens_used" : "total_tokens"
            first[tokenKey] = .number((first[tokenKey]?.number ?? 0) + 1000)
            rows[0] = .object(first)
            metrics["by_model"] = .array(rows)
            if report == .local { section["selected"] = .object(metrics) }
            else { section = metrics }
            value[key] = .object(section)
        }
        value["retrieved_at_local"] = .string("replay-\(iteration)")
        reports[report] = .object(value)
        return report == .radar ? .object(value) : .object(["ok": .bool(true), "data": .object(value)])
    }
}

@MainActor
private final class ReplaySession {
    let client = ReplayCollector()
    let model: DashboardModel
    private let suite = "UsageMemoryReplay." + UUID().uuidString
    private let defaults: UserDefaults
    private var closed = false
    init() {
        defaults = UserDefaults(suiteName: suite)!
        defaults.set(["codex", "claude", "radar", "isambard"], forKey: "sources")
        defaults.set(false, forKey: "automatic")
        defaults.set("en", forKey: "language")
        model = DashboardModel(defaults: defaults, demo: false, client: client)
    }
    func close() {
        guard !closed else { return }
        closed = true
        model.stop()
        defaults.removePersistentDomain(forName: suite)
    }
    func waitForReplies() async throws {
        while !model.canRefresh {
            try Task.checkCancellation()
            try await Task.sleep(for: .milliseconds(1))
        }
    }
}

@main
struct MemoryReplayApp: App {
    @State private var session = ReplaySession()
    @State private var started = false
    var body: some Scene {
        Window("Usage memory replay", id: "replay") {
            DashboardView(model: session.model)
                .modifier(DashboardAppearance())
                .environment(\.locale, Language.en.locale)
                .safeAreaInset(edge: .top) {
                    Text("Offline memory replay · synthetic data").font(.caption).padding(4)
                }
                .task {
                    guard !started else { return }
                    started = true
                    defer { session.close() }
                    do {
                        await session.model.start()
                        try await session.waitForReplies()
                        try await Task.sleep(for: .seconds(3))
                        let baseline = footprint()
                        var peak = baseline
                        let startedAt = Date()
                        var samples: [[String: Any]] = [["cycle": 0, "bytes": baseline]]
                        let env = ProcessInfo.processInfo.environment
                        let cycles = Int(env["USAGE_MEMORY_CYCLES"] ?? "600") ?? 600
                        let delay = Int(env["USAGE_MEMORY_DELAY_MS"] ?? "20") ?? 20
                        session.client.changingValues = env["USAGE_MEMORY_VALUES"] == "1"
                        session.client.valueEvery = max(1, Int(env["USAGE_MEMORY_VALUE_EVERY"] ?? "1") ?? 1)
                        for index in 0..<cycles {
                            try Task.checkCancellation()
                            session.client.iteration = index
                            session.model.refresh()
                            try await session.waitForReplies()
                            try await Task.sleep(for: .milliseconds(delay))
                            peak = max(peak, footprint())
                            if (index + 1) % 100 == 0 { samples.append(["cycle": index + 1, "bytes": footprint()]) }
                        }
                        try await Task.sleep(for: .seconds(5))
                        let result: [String: Any] = ["driver": "collector-protocol", "cycles": cycles,
                            "changing_values": session.client.changingValues, "value_every": session.client.valueEvery,
                            "requests_sent": session.client.requestsSent, "delay_ms": delay,
                            "start_bytes": baseline, "end_bytes": footprint(), "peak_bytes": peak,
                            "pid": ProcessInfo.processInfo.processIdentifier,
                            "elapsed_seconds": Date().timeIntervalSince(startedAt), "samples": samples]
                        if let output = env["USAGE_MEMORY_OUTPUT"] {
                            let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
                            try data.write(to: URL(fileURLWithPath: output), options: .atomic)
                        }
                        try await Task.sleep(for: .seconds(30))
                    } catch { }
                    session.close()
                    NSApplication.shared.terminate(nil)
                }
        }.defaultSize(width: 1120, height: 800)
    }

    private func footprint() -> UInt64 {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let status = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return status == KERN_SUCCESS ? info.phys_footprint : 0
    }
}
