import Foundation
import Observation

enum Language: String, CaseIterable, Identifiable {
    case en, zh
    var id: String { rawValue }
    var label: String { self == .zh ? "中文" : "English" }
    func text(_ english: String, _ chinese: String) -> String { self == .zh ? chinese : english }
}

enum Report: String, CaseIterable, Identifiable {
    case local = "local-usage", claude = "claude-usage", online = "online-usage"
    case resets, isambard = "isambard-status", api = "api-usage", radar
    var id: String { rawValue }
    var source: String {
        switch self {
        case .local, .online, .resets, .api: return "codex"
        case .claude: return "claude"
        case .isambard: return "isambard"
        case .radar: return "radar"
        }
    }
}

enum Destination: String, CaseIterable, Identifiable {
    case overview, codex, claude, radar, isambard, api
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .overview: return "square.grid.2x2"
        case .codex: return "terminal"
        case .claude: return "sparkle"
        case .radar: return "chart.bar.xaxis"
        case .isambard: return "server.rack"
        case .api: return "network"
        }
    }
    func title(_ language: Language) -> String {
        switch self {
        case .overview: return language.text("Overview", "总览")
        case .codex: return "Codex"
        case .claude: return "Claude Code"
        case .radar: return "Codex Radar"
        case .isambard: return "Isambard"
        case .api: return language.text("Admin API", "管理 API")
        }
    }
}

@MainActor @Observable
final class DashboardModel {
    var language: Language { didSet { save(language.rawValue, "language") } }
    var days: Int { didSet { if days != oldValue { save(days, "days"); historyChanged() } } }
    var interval: Int { didSet { save(interval, "interval") } }
    var automatic: Bool { didSet { save(automatic, "automatic") } }
    var sources: Set<String> { didSet { save(Array(sources).sorted(), "sources"); configurationChanged() } }
    var reports: [Report: JSONValue] = [:]
    var errors: [Report: String] = [:]
    var pending: Set<Report> = []
    var updated: [Report: Date] = [:]
    var connectionError: String?
    var connected = false
    var connecting = false
    var adminEnabled = false
    var diagnostics = ""
    let demo: Bool
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let client: any CollectorConnection
    @ObservationIgnored private var tasks: [Report: Task<Void, Never>] = [:]
    @ObservationIgnored private var requestIDs: [Report: UUID] = [:]
    @ObservationIgnored private var timer: Task<Void, Never>?
    @ObservationIgnored private var historyRefresh: Task<Void, Never>?
    @ObservationIgnored private var revision = UUID()
    @ObservationIgnored private var connectionID = UUID()
    private static let historyReports: Set<Report> = [.local, .claude, .api]

    init(defaults: UserDefaults = .standard, demo: Bool = ProcessInfo.processInfo.arguments.contains("--demo"),
         client: (any CollectorConnection)? = nil) {
        self.defaults = defaults
        self.demo = demo
        self.client = client ?? CollectorClient()
        language = Language(rawValue: defaults.string(forKey: "language") ?? "")
            ?? (Locale.preferredLanguages.first?.hasPrefix("zh") == true ? .zh : .en)
        days = min(365, max(1, defaults.object(forKey: "days") as? Int ?? 30))
        interval = min(300, max(3, defaults.object(forKey: "interval") as? Int ?? 15))
        automatic = defaults.object(forKey: "automatic") as? Bool ?? true
        sources = Set(defaults.stringArray(forKey: "sources") ?? ["codex", "claude", "radar", "isambard"])
        self.client.onDisconnect = { [weak self] message in
            self?.stop()
            self?.connectionError = message
        }
    }

    var canRefresh: Bool { connected && !connecting && pending.isEmpty && !demo }
    var needsReconnect: Bool { !connected && connectionError != nil && !demo }

    var isambardEnabled: Bool {
        get { sources.contains("isambard") }
        set { setSource("isambard", enabled: newValue) }
    }
    var radarEnabled: Bool {
        get { sources.contains("radar") }
        set { setSource("radar", enabled: newValue) }
    }
    var codexEnabled: Bool {
        get { sources.contains("codex") }
        set { setSource("codex", enabled: newValue) }
    }
    var claudeEnabled: Bool {
        get { sources.contains("claude") }
        set { setSource("claude", enabled: newValue) }
    }
    private func setSource(_ source: String, enabled: Bool) {
        if enabled { sources.insert(source) } else { sources.remove(source) }
    }
    private func save(_ value: Any, _ key: String) { if !demo { defaults.set(value, forKey: key) } }
    private func configurationChanged() {
        guard connected && !connecting && !demo else { return }
        Task { await configure() }
    }

    private func cancelReports(_ reports: Set<Report>) {
        for report in reports {
            requestIDs.removeValue(forKey: report)
            tasks.removeValue(forKey: report)?.cancel()
            pending.remove(report)
        }
    }

    private func historyChanged() {
        historyRefresh?.cancel()
        historyRefresh = nil
        guard connected && !demo else { return }
        cancelReports(Self.historyReports)
        historyRefresh = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(300)) }
            catch { return }
            guard let self, !Task.isCancelled else { return }
            self.historyRefresh = nil
            self.refresh(reports: Self.historyReports)
        }
    }

    func start() async {
        guard !connected && !connecting else { return }
        if demo {
            reports = DemoData.reports
            sources = ["codex", "claude", "radar", "isambard"]
            updated = Dictionary(uniqueKeysWithValues: reports.keys.map { ($0, Date()) })
            connected = true
            return
        }
        let session = UUID()
        connectionID = session
        connecting = true
        defer { if connectionID == session { connecting = false } }
        do {
            try client.start()
            let hello = try await client.request("hello", values: [:])
            guard connectionID == session else { return }
            try Task.checkCancellation()
            guard hello["protocol"].number == 1 else { throw BridgeError.message("Unsupported collector protocol") }
            adminEnabled = hello["admin_enabled"].flag == true
            if defaults.object(forKey: "sources") == nil {
                sources = Set(hello["detected_sources"].items.map(\.text))
            }
            connected = true
            connectionError = nil
            await configure()
            guard connectionID == session, connected else { return }
            try Task.checkCancellation()
            timer = Task { [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(self?.interval ?? 15)) }
                    catch { return }
                    guard let self else { return }
                    if self.automatic { self.refresh() }
                }
            }
        } catch {
            guard connectionID == session else { return }
            stop()
            connectionError = error is CancellationError ? nil : error.localizedDescription
        }
    }

    func configure() async {
        guard connected, !demo else { return }
        let current = UUID()
        revision = current
        do {
            while true {
                let selection = sources
                historyRefresh?.cancel()
                historyRefresh = nil
                cancelReports(Set(Report.allCases))
                for report in Report.allCases where !selection.contains(report.source) {
                    reports.removeValue(forKey: report)
                    errors.removeValue(forKey: report)
                    updated.removeValue(forKey: report)
                }
                _ = try await client.request("configure", values: ["sources": .array(selection.sorted().map(JSONValue.string))])
                guard revision == current else { return }
                // Startup suppresses configurationChanged(); reconcile edits made while awaiting the reply.
                guard selection == sources else { continue }
                connectionError = nil
                refresh()
                return
            }
        } catch {
            if revision == current { connectionError = error.localizedDescription }
        }
    }

    func refresh(force: Bool = false, reports requested: Set<Report> = Set(Report.allCases)) {
        guard connected, !demo else { return }
        if requested.isSuperset(of: Self.historyReports) {
            historyRefresh?.cancel()
            historyRefresh = nil
        }
        let current = revision
        let requestedDays = days
        for report in Report.allCases where requested.contains(report) && sources.contains(report.source) && !pending.contains(report) {
            if report == .api && !adminEnabled { continue }
            let requestID = UUID()
            requestIDs[report] = requestID
            pending.insert(report)
            tasks[report] = Task { [weak self] in
                guard let self else { return }
                defer {
                    if self.revision == current && self.requestIDs[report] == requestID {
                        self.pending.remove(report)
                        self.tasks.removeValue(forKey: report)
                        self.requestIDs.removeValue(forKey: report)
                    }
                }
                do {
                    let value = try await self.client.request(report == .radar ? "radar" : "report", values: [
                        "report": .string(report.rawValue), "days": .number(Double(requestedDays)),
                        "top": .number(20), "force": .bool(force)
                    ])
                    guard self.revision == current, self.requestIDs[report] == requestID, !Task.isCancelled else { return }
                    let data = report == .radar ? value : value["data"]
                    let message = collectionError(data: data, envelope: value)
                    if data["ok"].flag != false || self.reports[report] == nil { self.reports[report] = data }
                    self.errors[report] = message.isEmpty ? nil : message
                    if data["ok"].flag != false { self.updated[report] = Date() }
                } catch is CancellationError { }
                catch {
                    guard self.revision == current, self.requestIDs[report] == requestID else { return }
                    self.errors[report] = error.localizedDescription
                }
            }
        }
    }

    func checkSetup() async {
        guard !demo else { diagnostics = "Demo data — no local account files are read."; return }
        do { diagnostics = try prettyJSON(await client.request("check", values: [:])) }
        catch { diagnostics = error.localizedDescription }
    }

    func exportData() throws -> Data {
        let snapshot = JSONValue.object([
            "exported_at": .string(ISO8601DateFormatter().string(from: Date())),
            "sources": .array(sources.sorted().map(JSONValue.string)),
            "reports": .object(Dictionary(uniqueKeysWithValues: reports.filter { sources.contains($0.key.source) }.map { ($0.key.rawValue, $0.value) })),
            "errors": .object(Dictionary(uniqueKeysWithValues: errors.filter { sources.contains($0.key.source) }.map { ($0.key.rawValue, .string($0.value)) })),
            "updated_at": .object(Dictionary(uniqueKeysWithValues: updated.filter { sources.contains($0.key.source) }.map {
                ($0.key.rawValue, .string(ISO8601DateFormatter().string(from: $0.value)))
            }))
        ])
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(snapshot)
    }

    func stop() {
        connectionID = UUID()
        revision = UUID()
        timer?.cancel()
        timer = nil
        historyRefresh?.cancel()
        historyRefresh = nil
        cancelReports(Set(Report.allCases))
        client.stop()
        connected = false
        connecting = false
    }
    func reconnect() async {
        guard !connecting else { return }
        stop()
        await start()
    }
}

func collectionError(data: JSONValue, envelope: JSONValue) -> String {
    var messages = envelope["errors"].items.map { $0["message"].errorText }
    messages.append(data["error"].errorText)
    let sqliteError = data["sqlite_threads"]["selected"]["error"].errorText
    if !sqliteError.isEmpty { messages.append("SQLite: " + sqliteError) }
    for (name, endpoint) in data["endpoints"].object.sorted(by: { $0.key < $1.key }) where endpoint["ok"].flag == false {
        messages.append(name + ": " + endpoint["error"].errorText)
    }
    for key in ["usage", "costs"] where data[key]["ok"].flag == false {
        messages.append(key + ": " + data[key]["error"].errorText)
    }
    let unique = messages.filter { !$0.isEmpty }.reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
    return unique.isEmpty && envelope["ok"].flag == false ? "Source unavailable" : unique.joined(separator: "\n")
}

func prettyJSON(_ value: JSONValue) throws -> String {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    return String(decoding: try encoder.encode(value), as: UTF8.self)
}
