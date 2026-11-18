import XCTest
@testable import UsageMac

final class PresentationContractTests: XCTestCase {
    @MainActor
    func testLimitsIgnoreUnrelatedMetadataButKeepVisibleChanges() {
        let original = DemoData.reports[.online]!
        var changed = original.object
        changed["retrieved_at_local"] = .string("not used by this view")
        XCTAssertEqual(CodexLimits(data: original, language: .en), CodexLimits(data: .object(changed), language: .en))
        changed["retrieved_at_unix_ms"] = .number(1)
        XCTAssertNotEqual(CodexLimits(data: original, language: .en), CodexLimits(data: .object(changed), language: .en))
        changed = original.object
        changed["endpoints"] = .object(["rate_limit_status": .object(["ok": .bool(false), "error": .string("offline")])])
        XCTAssertNotEqual(CodexLimits(data: original, language: .en), CodexLimits(data: .object(changed), language: .en))
        let claude = DemoData.reports[.claude]!
        var claudeChanged = claude.object
        claudeChanged["local_usage"] = .object(["new": .integer(1)])
        XCTAssertEqual(ClaudeLimits(data: claude, language: .en), ClaudeLimits(data: .object(claudeChanged), language: .en))
        claudeChanged["rate_limits"] = .object(["available": .bool(false)])
        XCTAssertNotEqual(ClaudeLimits(data: claude, language: .en), ClaudeLimits(data: .object(claudeChanged), language: .en))
    }

    @MainActor
    func testCreditAndStatusViewsRetainCountsWarningsAndLanguage() {
        let credits = DemoData.reports[.resets]!
        var changed = credits.object
        changed["unused_metadata"] = .integer(1)
        XCTAssertEqual(ResetCredits(data: credits, language: .en), ResetCredits(data: .object(changed), language: .en))
        for key in ["available_count", "total_earned_count", "retrieved_at_unix_ms", "credits", "ok"] {
            var changed = credits.object
            changed[key] = key == "ok" ? .bool(false) : .null
            XCTAssertNotEqual(ResetCredits(data: credits, language: .en), ResetCredits(data: .object(changed), language: .en), key)
        }
        XCTAssertNotEqual(ResetCredits(data: credits, language: .en), ResetCredits(data: credits, language: .zh))
        let status = DemoData.reports[.isambard]!
        var warned = status.object
        warned["warning"] = .string("Cached status")
        XCTAssertNotEqual(IsambardView(data: status, language: .en), IsambardView(data: .object(warned), language: .en))
        XCTAssertNotEqual(IsambardView(data: status, language: .en), IsambardView(data: status, language: .en, maintenance: false))
    }

    func testDuplicateModelsKeepNamesAndStableUniqueIDsAcrossValueChanges() {
        func model(_ tokens: Double) -> JSONValue {
            .object(["model": .string("same-model"), "threads": .integer(1), "tokens": .number(tokens)])
        }
        let before = ModelDistribution(items: [model(10), model(20)], tokenKey: "tokens", countKey: "threads")
        let after = ModelDistribution(items: [model(15), model(25)], tokenKey: "tokens", countKey: "threads")
        XCTAssertEqual(Set(before.rows.map(\.id)).count, 2)
        XCTAssertEqual(before.rows.map(\.id), after.rows.map(\.id))
        XCTAssertEqual(after.rows.map(\.name), ["same-model", "same-model"])
        XCTAssertEqual(after.total, 40)
    }

    func testDuplicateServiceAndMaintenanceRowsRemainSeparate() {
        let statuses: [JSONValue] = ["Cluster: No Known Issues", "Cluster: Planned Outage"].map {
            .object(["title": .string($0)])
        }
        let services = identifiedValues(statuses, key: { $0.statusIdentity })
        XCTAssertEqual(Set(services.map(\.id)).count, 2)
        let updated = identifiedValues(statuses.reversed(), key: { $0.statusIdentity })
        XCTAssertEqual(services.map(\.id), updated.map(\.id))
        let row: JSONValue = .array([.string("Storage"), .string("Scheduled maintenance")])
        let maintenance = arrayRows([row, row], language: .en)
        XCTAssertEqual(Set(maintenance.map(\.id)).count, 2)
        XCTAssertEqual(maintenance.map(\.cells), [["Storage", "Scheduled maintenance"], ["Storage", "Scheduled maintenance"]])
    }

    func testExplicitLocaleFormattingAndIdentityAreIndependent() {
        let value: JSONValue = .number(1234.5)
        XCTAssertEqual(value.display(locale: Language.en.locale), "1,234.5")
        XCTAssertEqual(value.display(locale: Language.zh.locale), "1,234.5")
        XCTAssertEqual(value.display(locale: Locale(identifier: "de_DE")), "1.234,5")
        let array: JSONValue = .array([.integer(1234), value])
        XCTAssertEqual(array.display(locale: Locale(identifier: "de_DE")), "1.234, 1.234,5")
        let item: JSONValue = .object(["id": .integer(1234), "amount": value])
        XCTAssertEqual(rows([item], identity: "id", keys: ["amount"], language: .en).map(\.id),
                       rows([item], identity: "id", keys: ["amount"], language: .zh).map(\.id))
    }

    func testLargeIntegerRoundTripsWithoutDoublePrecisionLoss() throws {
        let value = JSONValue.integer(9_007_199_254_740_993)
        let encoded = try JSONEncoder().encode(value)
        XCTAssertEqual(String(decoding: encoded, as: UTF8.self), "9007199254740993")
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: encoded), value)
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: Data("12.5".utf8)), .number(12.5))
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: Data("true".utf8)), .bool(true))
    }

    func testSingularAndPluralHealthyStatusesLocalizeConsistently() {
        for detail in ["No Known Issue", "No Known Issues", " NO KNOWN ISSUE "] {
            let state = ServiceState(.object(["title": .string("Cluster: " + detail)]))
            XCTAssertEqual(state, .operational)
            XCTAssertEqual(state.condition(detail, language: .zh), "运行正常")
        }
        XCTAssertEqual(ServiceState.outage.condition("Planned Outage", language: .zh), "Planned Outage")
    }
}
