import Darwin
import XCTest
@testable import UsageMac

final class CollectorLifecycleTests: XCTestCase {
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
        for line in sys.stdin:
            request = json.loads(line)
            action = request['action']
            with log.open('a') as out:
                out.write(action + '\n')
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
            print(json.dumps({'id': request['id'], 'ok': True,
                              'result': {'protocol': 1, 'pid': os.getpid(),
                                         'integers': all(type(request.get(k)) is int for k in ('id', 'days', 'top'))}}), flush=True)
            if action == 'hello':
                with log.open('a') as out:
                    out.write('hello_replied\n')
            if action == 'exit_idle':
                threading.Timer(0.15, lambda: os._exit(0)).start()
        """#
        try script.write(to: root.appendingPathComponent("native_backend.py"), atomically: true, encoding: .utf8)
    }
    @MainActor func client(reportTimeout: Duration = .seconds(120), controlTimeout: Duration = .seconds(15)) -> CollectorClient {
        CollectorClient(environment: ["USAGE_PROJECT_DIR": root.path, "CODEX_HOME": root.path, "CLAUDE_CONFIG_DIR": root.path],
                        reportTimeout: reportTimeout, controlTimeout: controlTimeout)
    }
    func actions() -> String { (try? String(contentsOf: root.appendingPathComponent("actions.txt"), encoding: .utf8)) ?? "" }
    func remove() { try? FileManager.default.removeItem(at: root) }
}
