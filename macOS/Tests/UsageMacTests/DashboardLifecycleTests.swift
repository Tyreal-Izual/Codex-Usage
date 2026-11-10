import XCTest
@testable import UsageMac

final class DashboardLifecycleTests: XCTestCase {
    @MainActor
    func testIsolatedTimeoutKeepsPollingAndRecoveryUntilNextReply() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.model.interval = 3
        fixture.model.automatic = true
        fixture.client.failNextReports = ["online-usage"]
        await fixture.model.start()
        let loaded = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(loaded)
        let local = fixture.model.reports[.local]
        XCTAssertTrue(fixture.model.connected)
        XCTAssertNil(fixture.model.connectionError)
        XCTAssertNotNil(fixture.model.errors[.online])
        XCTAssertTrue(fixture.model.offersReconnect)
        let recovered = await eventually { fixture.model.errors[.online] == nil && fixture.model.canRefresh }
        XCTAssertTrue(recovered, "Automatic polling must continue after an isolated timeout")
        XCTAssertFalse(fixture.model.offersReconnect)
        XCTAssertEqual(fixture.client.starts, 1)
        XCTAssertEqual(fixture.model.reports[.local], local)
    }

    @MainActor
    func testIntervalChangeReplacesTheCurrentLongSleep() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.model.interval = 300
        fixture.model.automatic = true
        await fixture.model.start()
        let loaded = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(loaded)
        let count = fixture.client.requests.count
        fixture.model.interval = 3
        let refreshed = await eventually { fixture.client.requests.count > count }
        XCTAssertTrue(refreshed, "The old 300-second sleep must be cancelled")
    }

    @MainActor
    func testAppOwnedStartupSurvivesCancelledWindowTask() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let delegate = AppDelegate(model: fixture.model)
        fixture.client.holdNextHello = true
        let windowTask = Task {
            delegate.applicationDidFinishLaunching(Notification(name: Notification.Name("testLaunch")))
            try? await Task.sleep(for: .seconds(30))
        }
        defer { windowTask.cancel() }
        let waiting = await eventually { fixture.client.held.count == 1 }
        XCTAssertTrue(waiting)
        XCTAssertTrue(fixture.model.connecting)
        XCTAssertFalse(fixture.model.needsReconnect)
        windowTask.cancel()
        await windowTask.value
        fixture.client.releaseFirst()
        let ready = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(ready)
        XCTAssertFalse(fixture.model.needsReconnect)
        XCTAssertFalse(fixture.model.reports.isEmpty)
    }

    @MainActor
    func testLaunchWithoutAWindowStartsAndTerminationStopsCollectors() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let delegate = AppDelegate(model: fixture.model)
        XCTAssertTrue(delegate.model === fixture.model)
        delegate.applicationDidFinishLaunching(Notification(name: Notification.Name("testLaunch")))
        let ready = await eventually { delegate.model.canRefresh }
        XCTAssertTrue(ready)
        XCTAssertEqual(fixture.client.starts, 1)
        delegate.applicationWillTerminate(Notification(name: Notification.Name("testTermination")))
        XCTAssertFalse(fixture.model.connected)
        XCTAssertTrue(fixture.model.pending.isEmpty)
    }

    @MainActor
    func testFastRefreshDoesNotShowDelayedReconnect() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        await fixture.model.start()
        XCTAssertFalse(fixture.model.offersReconnect)
        let ready = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(ready)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertFalse(fixture.model.offersReconnect)
        XCTAssertFalse(fixture.model.collectionIsSlow)
    }

    @MainActor
    func testOtherSourceRefreshesDoNotResetTheSlowRequestsDeadline() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.client.heldReports = ["local-usage"]
        await fixture.model.start()
        let poll = Task {
            while !Task.isCancelled {
                fixture.model.refresh(reports: [.online])
                do { try await Task.sleep(for: .milliseconds(20)) }
                catch { return }
            }
        }
        defer { poll.cancel() }
        let slow = await eventually { fixture.model.offersReconnect }
        XCTAssertTrue(slow)
        poll.cancel()
        fixture.client.releaseFirst()
        let ready = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(ready)
        XCTAssertFalse(fixture.model.offersReconnect)
    }

    @MainActor
    func testBusyCollectorCanBeReconnectedWithoutWaitingForTimeout() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.client.heldReports = ["local-usage"]
        await fixture.model.start()
        let pending = await eventually { fixture.client.held.count == 1 }
        XCTAssertTrue(pending)
        XCTAssertFalse(fixture.model.canRefresh)
        XCTAssertFalse(fixture.model.offersReconnect)
        let slow = await eventually { fixture.model.offersReconnect }
        XCTAssertTrue(slow)
        fixture.client.heldReports = []
        await fixture.model.reconnect()
        let ready = await eventually { fixture.model.canRefresh }
        XCTAssertTrue(ready)
        XCTAssertFalse(fixture.model.offersReconnect)
        XCTAssertEqual(fixture.client.starts, 2)
    }

    @MainActor
    func testSourceEditsDuringStartupAndReconnectAreAppliedBeforeRefreshing() async throws {
        for reconnecting in [false, true] {
            let fixture = ModelFixture()
            defer { fixture.close() }
            let model = fixture.model, client = fixture.client
            model.sources = ["codex"]
            if reconnecting {
                await model.start()
                let loaded = await eventually { model.canRefresh }
                XCTAssertTrue(loaded)
            }
            client.requests.removeAll()
            client.holdNextConfigure = true
            let connecting = Task {
                if reconnecting { await model.reconnect() }
                else { await model.start() }
            }
            let held = await eventually { client.held.count == 1 }
            XCTAssertTrue(held)
            XCTAssertTrue(model.connecting)
            model.sources = ["claude"]
            client.releaseFirst()
            await connecting.value
            let ready = await eventually { model.canRefresh }
            XCTAssertTrue(ready)
            let configurations = client.requests.filter { $0.action == "configure" }
            XCTAssertEqual(configurations.count, 2)
            XCTAssertEqual(configurations.last?.values["sources"], .array([.string("claude")]))
            XCTAssertEqual(Set(model.reports.keys), [.claude])
            XCTAssertEqual(client.requests.filter { $0.action == "report" }.map { $0.values["report"]?.text }, ["claude-usage"])
        }
    }

    @MainActor
    func testSupersededConfigurationReplyCannotUndoLatestSelection() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let model = fixture.model, client = fixture.client
        await model.start()
        let loaded = await eventually { model.canRefresh }
        XCTAssertTrue(loaded)
        client.holdNextConfigure = true
        model.sources.remove("radar")
        let held = await eventually { client.held.count == 1 }
        XCTAssertTrue(held)
        model.sources.remove("isambard")
        let applied = await eventually {
            client.requests.last(where: { $0.action == "configure" })?.values["sources"] == .array([.string("claude"), .string("codex")])
                && model.canRefresh
        }
        XCTAssertTrue(applied)
        client.releaseFirst()
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNil(model.reports[.radar])
        XCTAssertNil(model.reports[.isambard])
        XCTAssertNil(model.connectionError)
    }

    @MainActor
    func testDisconnectPreservesSnapshotDisablesRefreshAndReconnects() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let model = fixture.model, client = fixture.client
        await model.start()
        let loaded = await eventually { model.canRefresh }
        XCTAssertTrue(loaded)
        let snapshot = model.reports
        client.onDisconnect?("Helper exited")
        XCTAssertFalse(model.connected)
        XCTAssertFalse(model.connecting)
        XCTAssertFalse(model.canRefresh)
        XCTAssertTrue(model.needsReconnect)
        XCTAssertTrue(model.pending.isEmpty)
        XCTAssertEqual(model.connectionError, "Helper exited")
        XCTAssertEqual(model.reports, snapshot)
        let count = client.requests.count
        model.refresh(force: true)
        XCTAssertEqual(client.requests.count, count)
        await model.reconnect()
        let reloaded = await eventually { model.canRefresh }
        XCTAssertTrue(reloaded)
        XCTAssertFalse(model.needsReconnect)
        XCTAssertNil(model.connectionError)
        XCTAssertEqual(client.starts, 2)
    }

    @MainActor
    func testHistoryChangesCoalesceWithoutConfiguringOrRefreshingOtherSources() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let model = fixture.model, client = fixture.client
        await model.start()
        let loaded = await eventually { model.canRefresh }
        XCTAssertTrue(loaded)
        let count = client.requests.count
        model.days = 31
        model.days = 32
        model.days = 33
        XCTAssertEqual(client.requests.count, count)
        let refreshed = await eventually { client.requests.count >= count + 3 && model.pending.isEmpty }
        XCTAssertTrue(refreshed)
        let requests = Array(client.requests.dropFirst(count))
        XCTAssertEqual(requests.count, 3)
        XCTAssertTrue(requests.allSatisfy { $0.action == "report" && $0.values["days"]?.number == 33 })
        XCTAssertEqual(Set(requests.compactMap { $0.values["report"]?.text }), ["local-usage", "claude-usage", "api-usage"])
    }

    @MainActor
    func testOldHistoryReplyCannotOverwriteNewRequestOrClearItsPendingState() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let model = fixture.model, client = fixture.client
        client.heldReports = ["local-usage"]
        await model.start()
        let first = await eventually { client.held.count == 1 }
        XCTAssertTrue(first)
        model.days = 31
        let replacement = await eventually { client.held.count == 2 }
        XCTAssertTrue(replacement)
        client.releaseFirst()
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertTrue(model.pending.contains(.local))
        XCTAssertNil(model.reports[.local])
        client.releaseFirst()
        let done = await eventually { model.pending.isEmpty }
        XCTAssertTrue(done)
        XCTAssertEqual(model.reports[.local]?["days"].number, 31)
    }

    @MainActor
    func testInterruptedHandshakeCannotStopNewConnection() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        let model = fixture.model, client = fixture.client
        client.holdNextHello = true
        let oldStart = Task { await model.start() }
        let waiting = await eventually { client.held.count == 1 }
        XCTAssertTrue(waiting)
        model.stop()
        await model.start()
        await oldStart.value
        let ready = await eventually { model.canRefresh }
        XCTAssertTrue(ready)
        XCTAssertNil(model.connectionError)
        XCTAssertEqual(client.starts, 2)
    }

    @MainActor
    func testDisconnectDuringHandshakeEndsConnectingState() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.client.holdNextHello = true
        let start = Task { await fixture.model.start() }
        let waiting = await eventually { fixture.client.held.count == 1 }
        XCTAssertTrue(waiting)
        fixture.client.onDisconnect?("Handshake disconnected")
        await start.value
        XCTAssertFalse(fixture.model.connected)
        XCTAssertFalse(fixture.model.connecting)
        XCTAssertTrue(fixture.model.needsReconnect)
        XCTAssertEqual(fixture.model.connectionError, "Handshake disconnected")
    }

    @MainActor
    func testCancelledStartupCleansUpWithoutShowingConnectionFailure() async throws {
        let fixture = ModelFixture()
        defer { fixture.close() }
        fixture.client.holdNextHello = true
        let start = Task { await fixture.model.start() }
        let waiting = await eventually { fixture.client.held.count == 1 }
        XCTAssertTrue(waiting)
        start.cancel()
        fixture.client.releaseFirst()
        await start.value
        XCTAssertFalse(fixture.model.connected)
        XCTAssertFalse(fixture.model.connecting)
        XCTAssertFalse(fixture.model.canRefresh)
        XCTAssertNil(fixture.model.connectionError)
        XCTAssertTrue(fixture.model.offersReconnect)
    }
}

@MainActor
private func eventually(_ condition: () -> Bool) async -> Bool {
    for _ in 0..<600 {
        if condition() { return true }
        try? await Task.sleep(for: .milliseconds(10))
    }
    return false
}

@MainActor
private final class ModelFixture {
    let name = "UsageMacTests." + UUID().uuidString
    let client = FakeCollectorConnection()
    let model: DashboardModel
    init() {
        let defaults = UserDefaults(suiteName: name)!
        defaults.set(["codex", "claude", "isambard", "radar"], forKey: "sources")
        defaults.set(false, forKey: "automatic")
        model = DashboardModel(defaults: defaults, demo: false, client: client, reconnectDelay: .milliseconds(80))
    }
    func close() {
        model.stop()
        UserDefaults.standard.removePersistentDomain(forName: name)
    }
}

@MainActor
private final class FakeCollectorConnection: CollectorConnection {
    struct Request {
        let action: String
        let values: [String: JSONValue]
        var result: JSONValue {
            if action == "hello" { return .object(["protocol": .number(1), "admin_enabled": .bool(true)]) }
            if action == "report" { return .object(["data": .object(["ok": .bool(true), "days": values["days"] ?? .null])]) }
            return .object(["ok": .bool(true)])
        }
    }
    var onDisconnect: ((String) -> Void)?
    var starts = 0
    var requests: [Request] = []
    var heldReports: Set<String> = []
    var failNextReports: Set<String> = []
    var holdNextHello = false
    var holdNextConfigure = false
    var held: [(Request, CheckedContinuation<JSONValue, Error>)] = []
    func start() { starts += 1 }
    func request(_ action: String, values: [String: JSONValue]) async throws -> JSONValue {
        let request = Request(action: action, values: values)
        requests.append(request)
        if action == "report", let report = values["report"]?.text,
           failNextReports.remove(report) != nil { throw BridgeError.reportTimeout }
        let holdHello = action == "hello" && holdNextHello
        let holdConfigure = action == "configure" && holdNextConfigure
        if holdHello || holdConfigure || heldReports.contains(values["report"]?.text ?? "") {
            if holdHello { holdNextHello = false }
            if holdConfigure { holdNextConfigure = false }
            return try await withCheckedThrowingContinuation { held.append((request, $0)) }
        }
        return request.result
    }
    func releaseFirst() {
        guard !held.isEmpty else { return }
        let (request, continuation) = held.removeFirst()
        continuation.resume(returning: request.result)
    }
    func stop() {
        let pending = held
        held.removeAll()
        pending.forEach { $0.1.resume(throwing: CancellationError()) }
    }
}
