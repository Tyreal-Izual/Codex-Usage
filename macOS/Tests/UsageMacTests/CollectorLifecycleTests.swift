import Darwin
import XCTest
@testable import UsageMac

final class CollectorLifecycleTests: XCTestCase {
    @MainActor
    func testHistoryAndSourceChangesWaitForHelperThenApplyLatestSettingsWithoutPolling() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(heldReport: "local-usage")
        let name = "UsageMacTests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: name)!
        defaults.set(["codex"], forKey: "sources")
        defaults.set(false, forKey: "automatic")
        let model = DashboardModel(defaults: defaults, demo: false, client: client)
        defer { model.stop(); defaults.removePersistentDomain(forName: name) }
        await model.start()
        let first = await eventually { fixture.actions().contains("held:30") }
        XCTAssertTrue(first)
        model.sources = []
        let disabled = await eventually { model.pending.isEmpty }
        XCTAssertTrue(disabled)
        model.sources = ["codex"]
        let enabled = await eventually { model.pending.contains(.local) }
        XCTAssertTrue(enabled)
        _ = try await client.request("hello")
        XCTAssertEqual(fixture.heldDays(), [30])
        XCTAssertNil(model.errors[.local])
        _ = try await client.request("release_report")
        let sameOptions = await eventually { fixture.heldDays() == [30, 30] }
        XCTAssertTrue(sameOptions)
        XCTAssertNil(model.reports[.local])

        model.days = 31
        model.days = 32
        model.days = 33
        let replacement = await eventually { model.pending.contains(.local) }
        XCTAssertTrue(replacement)
        _ = try await client.request("hello") // Drain requests already written to the helper.
        XCTAssertEqual(fixture.heldDays(), [30, 30])
        XCTAssertNil(model.errors[.local])
        _ = try await client.request("release_report")
        let sent = await eventually { fixture.heldDays() == [30, 30, 33] }
        XCTAssertTrue(sent)
        XCTAssertNil(model.reports[.local], "Cancelled history must not be displayed")
        _ = try await client.request("release_report")
        let applied = await eventually { model.canRefresh && model.reports[.local]?["days"].number == 33 }
        XCTAssertTrue(applied)
        XCTAssertNil(model.errors[.local])
        XCTAssertFalse(model.automatic)
    }

    @MainActor
    func testTimedOutReportRetainsItsSlotUntilLateReply() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(reportTimeout: .seconds(1))
        defer { client.stop() }
        client.onDisconnect = { message in XCTFail("Responsive helper disconnected: \(message)") }
        try client.start()
        _ = try await client.request("hello")
        do {
            _ = try await client.request("report", values: ["report": .string("queued"), "days": .integer(30)])
            XCTFail("Held report must time out")
        }
        catch { XCTAssertTrue(error.localizedDescription.contains("timed out")) }
        var started = false
        let next = Task {
            started = true
            return try await client.request("report", values: ["report": .string("queued"), "days": .integer(60)])
        }
        defer { next.cancel() }
        let waiting = await eventually { started }
        XCTAssertTrue(waiting)
        _ = try await client.request("hello")
        XCTAssertEqual(fixture.heldDays(), [30])
        _ = try await client.request("release_report")
        let sent = await eventually { fixture.heldDays() == [30, 60] }
        XCTAssertTrue(sent)
        _ = try await client.request("release_report")
        let result = try await next.value
        XCTAssertEqual(result["data"]["days"].number, 60)
    }

    @MainActor
    func testStopClearsActiveAndQueuedReportsBeforeRestart() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(reportTimeout: .seconds(3))
        defer { client.stop() }
        try client.start()
        _ = try await client.request("hello")
        let first = Task { try await client.request("report", values: ["report": .string("queued"), "days": .integer(30)]) }
        let active = await eventually { fixture.heldDays() == [30] }
        XCTAssertTrue(active)
        var started = false
        let queued = Task {
            started = true
            return try await client.request("report", values: ["report": .string("queued"), "days": .integer(60)])
        }
        let waiting = await eventually { started }
        XCTAssertTrue(waiting)
        client.stop()
        for task in [first, queued] {
            do { _ = try await task.value; XCTFail("Stopped request must fail") }
            catch { }
        }
        try client.start()
        _ = try await client.request("hello")
        let restarted = Task { try await client.request("report", values: ["report": .string("queued"), "days": .integer(90)]) }
        defer { restarted.cancel() }
        let sent = await eventually { fixture.heldDays() == [30, 90] }
        XCTAssertTrue(sent)
        _ = try await client.request("release_report")
        let result = try await restarted.value
        XCTAssertEqual(result["data"]["days"].number, 90)
    }

    @MainActor
    func testReportTimeoutsShareProbeAndKeepResponsiveHelperAlive() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(reportTimeout: .milliseconds(150))
        defer { client.stop() }
        client.onDisconnect = { message in XCTFail("Responsive helper disconnected: \(message)") }
        try client.start()
        let hello = try await client.request("hello")
        let first = Task { try await client.request("report", values: ["report": .string("hold_delayed_probe")]) }
        let second = Task { try await client.request("report", values: ["report": .string("hold_delayed_probe")]) }
        for request in [first, second] {
            do { _ = try await request.value; XCTFail("Report must time out") }
            catch { XCTAssertTrue(error.localizedDescription.contains("timed out")) }
        }
        let probed = await eventually { fixture.actions().components(separatedBy: "\n").filter { $0 == "hello_replied" }.count == 2 }
        XCTAssertTrue(probed)
        XCTAssertEqual(fixture.actions().components(separatedBy: "\n").filter { $0 == "hello" }.count, 2)
        let local = try await client.request("report", values: ["report": .string("local-usage")])
        XCTAssertEqual(local["pid"].number, hello["pid"].number)
    }

    @MainActor
    func testUnresponsiveProbeDisconnectsAndAllowsRestart() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(reportTimeout: .milliseconds(150), controlTimeout: .seconds(1))
        defer { client.stop() }
        let disconnected = expectation(description: "Unresponsive helper disconnected")
        disconnected.assertForOverFulfill = true
        client.onDisconnect = { _ in disconnected.fulfill() }
        try client.start()
        let hello = try await client.request("hello")
        let pid = Int32(hello["pid"].number!)
        do {
            _ = try await client.request("report", values: ["report": .string("hold_unresponsive")])
            XCTFail("Stalled report must time out")
        } catch { XCTAssertTrue(error.localizedDescription.contains("timed out")) }
        await fulfillment(of: [disconnected], timeout: 3)
        let exited = await eventually { kill(pid, 0) == -1 && errno == ESRCH }
        XCTAssertTrue(exited)
        try client.start()
        let restarted = try await client.request("hello")
        XCTAssertNotEqual(restarted["pid"].number, hello["pid"].number)
    }

    @MainActor
    func testOldProbeCannotDisconnectOrClearTheNewSession() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client(reportTimeout: .milliseconds(150))
        defer { client.stop() }
        client.onDisconnect = { message in XCTFail("Old probe affected new session: \(message)") }
        try client.start()
        let before = try await client.request("hello")
        do { _ = try await client.request("report", values: ["report": .string("hold_unresponsive")]) }
        catch { XCTAssertTrue(error.localizedDescription.contains("timed out")) }
        let probing = await eventually { fixture.actions().components(separatedBy: "\n").filter { $0 == "hello" }.count == 2 }
        XCTAssertTrue(probing)
        client.stop()
        try client.start()
        let after = try await client.request("hello")
        XCTAssertNotEqual(before["pid"].number, after["pid"].number)
        let reply = try await client.request("report", values: ["report": .string("local-usage")])
        XCTAssertEqual(reply["pid"].number, after["pid"].number)
    }

    @MainActor
    func testClientProtectsBrokenPipeWritesWithoutAppInitialization() throws {
        _ = CollectorClient()
        let pipe = Pipe()
        try pipe.fileHandleForReading.close()
        defer { try? pipe.fileHandleForWriting.close() }
        XCTAssertThrowsError(try pipe.fileHandleForWriting.write(contentsOf: Data([1])))
    }

    @MainActor
    func testIntegerArgumentsReachPythonAsIntegers() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client()
        defer { client.stop() }
        try client.start()
        let result = try await client.request("hello", values: ["days": .integer(30), "top": .integer(20)])
        XCTAssertEqual(result["integers"].flag, true)
    }

    @MainActor
    func testBrokenResponsesAndCrashesFailAllRequestsAndAllowRestart() async throws {
        for action in ["malformed", "missing_id", "crash"] {
            let fixture = try HelperFixture()
            defer { fixture.remove() }
            let client = fixture.client()
            defer { client.stop() }
            let disconnected = expectation(description: "Disconnected after \(action)")
            disconnected.assertForOverFulfill = true
            client.onDisconnect = { _ in disconnected.fulfill() }
            try client.start()
            let hello = try await client.request("hello")
            let pid = Int32(hello["pid"].number!)
            let waiting = Task { try await client.request("hold") }
            let held = await eventually { fixture.actions().contains("hold") }
            XCTAssertTrue(held)
            do {
                _ = try await client.request(action)
                XCTFail("Broken transport must fail")
            } catch { }
            do {
                _ = try await waiting.value
                XCTFail("All pending requests must fail")
            } catch { }
            await fulfillment(of: [disconnected], timeout: 3)
            let exited = await eventually { kill(pid, 0) == -1 && errno == ESRCH }
            XCTAssertTrue(exited, "Invalid output must not leave the helper alive")
            let started = Date()
            do {
                _ = try await client.request("hello")
                XCTFail("Disconnected requests must fail immediately")
            } catch { XCTAssertLessThan(Date().timeIntervalSince(started), 1) }
            try client.start()
            let restarted = try await client.request("hello")
            XCTAssertNotEqual(restarted["pid"].number, hello["pid"].number)
            XCTAssertEqual(restarted["protocol"].number, 1)
        }
    }

    @MainActor
    func testIdleExitNotifiesAndIntentionalStopDoesNotNotify() async throws {
        let fixture = try HelperFixture()
        defer { fixture.remove() }
        let client = fixture.client()
        defer { client.stop() }
        let disconnected = expectation(description: "Idle exit")
        disconnected.assertForOverFulfill = true
        client.onDisconnect = { _ in disconnected.fulfill() }
        try client.start()
        _ = try await client.request("exit_idle")
        await fulfillment(of: [disconnected], timeout: 3)
        client.onDisconnect = { message in XCTFail("Intentional stop notified: \(message)") }
        try client.start()
        _ = try await client.request("hello")
        client.stop()
        try client.start()
        let restarted = try await client.request("hello")
        XCTAssertEqual(restarted["protocol"].number, 1)
    }
}

@MainActor
private func eventually(_ condition: () -> Bool) async -> Bool {
    for _ in 0..<300 {
        if condition() { return true }
        try? await Task.sleep(for: .milliseconds(10))
    }
    return false
}

private struct HelperFixture {
    let root: URL
    init() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let script = #"""
        import json, os, sys, threading, time
        from pathlib import Path
        log = Path(__file__).with_name('actions.txt')
        hello_count = 0
        probe_mode = 'reply'
        waiting = []
        held_report = os.environ.get('USAGE_TEST_HOLD_REPORT', 'queued')
        def respond(request):
            print(json.dumps({'id': request['id'], 'ok': True,
                              'result': {'protocol': 1, 'pid': os.getpid(),
                                         'data': {'ok': True, 'days': request.get('days')},
                                         'integers': all(type(request.get(k)) is int for k in ('id', 'days', 'top'))}}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            action = request['action']
            with log.open('a') as out:
                out.write(action + '\n')
            if action == 'report' and request.get('report') == held_report:
                with log.open('a') as out:
                    out.write('held:' + str(request.get('days')) + '\n')
                if waiting:
                    print(json.dumps({'id': request['id'], 'ok': False, 'error': 'report is still collecting'}), flush=True)
                else:
                    waiting.append(request)
                continue
            if action == 'release_report' and waiting:
                respond(waiting.pop(0))
            if action == 'hold' or (action == 'report' and request.get('report') == 'hold'):
                continue
            if action == 'report' and request.get('report') in ('hold_delayed_probe', 'hold_unresponsive'):
                probe_mode = request['report']
                continue
            if action == 'hello':
                hello_count += 1
                if hello_count > 1:
                    if probe_mode == 'hold_unresponsive':
                        continue
                    if probe_mode == 'hold_delayed_probe':
                        time.sleep(0.25)
            if action == 'crash':
                os._exit(7)
            if action == 'malformed':
                print('{broken-json', flush=True)
                continue
            if action == 'missing_id':
                print('{"ok":true,"result":{}}', flush=True)
                continue
            respond(request)
            if action == 'hello':
                with log.open('a') as out:
                    out.write('hello_replied\n')
            if action == 'exit_idle':
                threading.Timer(0.15, lambda: os._exit(0)).start()
        """#
        try script.write(to: root.appendingPathComponent("native_backend.py"), atomically: true, encoding: .utf8)
    }
    @MainActor func client(reportTimeout: Duration = .seconds(120), controlTimeout: Duration = .seconds(15), heldReport: String = "queued") -> CollectorClient {
        CollectorClient(environment: ["USAGE_PROJECT_DIR": root.path, "CODEX_HOME": root.path, "CLAUDE_CONFIG_DIR": root.path,
                                      "USAGE_TEST_HOLD_REPORT": heldReport],
                        reportTimeout: reportTimeout, controlTimeout: controlTimeout)
    }
    func actions() -> String { (try? String(contentsOf: root.appendingPathComponent("actions.txt"), encoding: .utf8)) ?? "" }
    func heldDays() -> [Int] {
        actions().split(separator: "\n").compactMap { $0.hasPrefix("held:") ? Int($0.dropFirst(5)) : nil }
    }
    func remove() { try? FileManager.default.removeItem(at: root) }
}
