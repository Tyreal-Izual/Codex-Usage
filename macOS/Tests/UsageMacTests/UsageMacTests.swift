import XCTest
@testable import UsageMac

final class UsageMacTests: XCTestCase {
    func testNullAndZeroRemainDistinctAcrossTheBridge() throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"zero":0,"missing":null,"enabled":false,"rows":[1,"你好"]}"#.utf8))
        XCTAssertEqual(value["zero"].number, 0)
        XCTAssertNil(value["missing"].number)
        XCTAssertEqual(value["enabled"].flag, false)
        XCTAssertEqual(value["rows"].items.count, 2)
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value)), value)
    }

    func testWeeklyOnlyLimitIsNotPresentedAsFiveHours() {
        let weekly: JSONValue = .object(["used_percent": .number(30)])
        let windows = LimitWindows(.object(["primary_window": weekly]))
        XCTAssertEqual(windows.primary, .null)
        XCTAssertEqual(windows.weekly, weekly)
        let both = LimitWindows(.object(["primary_window": .object(["used_percent": .number(0)]), "secondary_window": weekly]))
        XCTAssertEqual(both.primary["used_percent"].number, 0)
    }

    func testPartialUpstreamFailuresRemainVisible() {
        let data: JSONValue = .object(["endpoints": .object([
            "rate_limit_status": .object(["ok": .bool(true)]),
            "profile": .object(["ok": .bool(false), "error": .object(["error": .string("Timed out")])])
        ])])
        XCTAssertEqual(collectionError(data: data, envelope: .object(["ok": .bool(false)])), "profile: Timed out")
        XCTAssertEqual(collectionError(data: .null, envelope: .object(["ok": .bool(false)])), "Source unavailable")
    }

    func testSQLiteFailuresRemainVisibleAndDuplicateMessagesAreCollapsed() {
        let message = "SQLite: DatabaseError: file is not a database"
        let data: JSONValue = .object(["sqlite_threads": .object([
            "selected": .object(["error": .string("DatabaseError: file is not a database")])
        ])])
        XCTAssertEqual(collectionError(data: data, envelope: .object(["ok": .bool(true)])), message)
        let envelope: JSONValue = .object(["ok": .bool(false), "errors": .array([.object(["message": .string(message)])])])
        XCTAssertEqual(collectionError(data: data, envelope: envelope), message)
    }

    @MainActor
    func testDemoExportIncludesReportsAndFreshnessWithoutStartingCollectors() async throws {
        let model = DashboardModel(demo: true)
        await model.start()
        XCTAssertTrue(model.connected)
        XCTAssertTrue(model.pending.isEmpty)
        let value = try JSONDecoder().decode(JSONValue.self, from: model.exportData())
        XCTAssertEqual(value["reports"]["local-usage"]["sessions"]["final_token_totals_sum"]["total_tokens"].number, 3_580_000)
        XCTAssertFalse(value["updated_at"]["radar"].text.isEmpty)
        model.sources.remove("radar")
        let filtered = try JSONDecoder().decode(JSONValue.self, from: model.exportData())
        XCTAssertEqual(filtered["reports"]["radar"], .null)
        model.stop()
    }

    @MainActor
    func testRealPythonBridgeRoutesConcurrentRepliesAndSurvivesInvalidRequests() async throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: home) }
        let client = CollectorClient(environment: ["CODEX_HOME": home.path, "CLAUDE_CONFIG_DIR": home.path])
        try client.start()
        defer { client.stop() }
        let hello = try await client.request("hello")
        XCTAssertEqual(hello["protocol"].number, 1)
        _ = try await client.request("configure", values: ["sources": .array([])])
        async let first = client.request("report", values: ["report": .string("local-usage")])
        async let second = client.request("radar")
        let (local, radar) = try await (first, second)
        XCTAssertEqual(local["data"]["disabled"].flag, true)
        XCTAssertEqual(radar["disabled"].flag, true)
        do {
            _ = try await client.request("invalid")
            XCTFail("Invalid action should fail")
        } catch { XCTAssertTrue(error.localizedDescription.contains("Unknown")) }
        let again = try await client.request("hello")
        XCTAssertEqual(again["protocol"].number, 1)
        client.stop()
        do {
            _ = try await client.request("hello")
            XCTFail("A stopped helper should reject requests")
        } catch { XCTAssertTrue(error.localizedDescription.contains("connected")) }
        try client.start()
        let restarted = try await client.request("hello")
        XCTAssertEqual(restarted["protocol"].number, 1)
    }
}
