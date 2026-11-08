import XCTest
@testable import UsageMac

final class LimitDetailsTests: XCTestCase {
    func testMenuShowsWeeklyOnlyAccountsForEitherPayloadShape() {
        let weekly: JSONValue = .object(["used_percent": .number(32)])
        for key in ["primary_window", "secondary_window"] {
            let windows = LimitWindows(.object([key: weekly]))
            XCTAssertEqual(LimitFormatting.menuSummary(provider: "Codex",
                primaryUsed: windows.primary["used_percent"].number,
                weeklyUsed: windows.weekly["used_percent"].number, language: .en), "Codex · Weekly · 68% left")
        }
    }

    func testMenuKeepsZeroUsageAndPrefersShortWindow() {
        XCTAssertEqual(LimitFormatting.menuSummary(provider: "Codex", primaryUsed: 0, weeklyUsed: 40, language: .en),
                       "Codex · 5-hour · 100% left")
        XCTAssertEqual(LimitFormatting.menuSummary(provider: "Claude", primaryUsed: 100, weeklyUsed: 40, language: .zh),
                       "Claude · 5 小时 · 0% 剩余")
    }

    func testMenuSkipsInvalidWindowsAndClampsPercentage() {
        XCTAssertNil(LimitFormatting.menuSummary(provider: "Codex", primaryUsed: nil, weeklyUsed: .nan, language: .en))
        XCTAssertEqual(LimitFormatting.menuSummary(provider: "Claude", primaryUsed: .infinity, weeklyUsed: 120, language: .en),
                       "Claude · Weekly · 0% left")
        XCTAssertEqual(LimitFormatting.menuSummary(provider: "Codex", primaryUsed: -10, weeklyUsed: nil, language: .en),
                       "Codex · 5-hour · 100% left")
    }

    func testMissingFlagsAreNotDisplayedAsFalseAndStringBalancesAreFormatted() {
        XCTAssertEqual(LimitFormatting.boolean(.null, language: .en), "—")
        XCTAssertEqual(LimitFormatting.boolean(.bool(false), language: .en), "false")
        XCTAssertEqual(LimitFormatting.boolean(.bool(true), language: .zh), "是")
        XCTAssertEqual(LimitFormatting.balance(.string("64150.0000000000"), language: .en), "64,150")
        XCTAssertEqual(LimitFormatting.balance(.number(0), language: .en), "0")
        XCTAssertEqual(LimitFormatting.balance(.null, language: .en), "—")
        XCTAssertEqual(LimitFormatting.balance(.string("NaN"), language: .en), "—")
        XCTAssertEqual(LimitFormatting.reachedTone(.null), .normal)
        XCTAssertEqual(LimitFormatting.reachedTone(.bool(false)), .good)
        XCTAssertEqual(LimitFormatting.reachedTone(.bool(true)), .bad)
    }

    func testRelativeResetUsesCollectionTimeAndKeepsCountingDown() {
        let collected = Date(timeIntervalSince1970: 1_000)
        let window: JSONValue = .object(["reset_after_seconds": .number(10_800)])
        let reset = LimitFormatting.resetAt(window, collectedAt: collected)
        XCTAssertEqual(reset, collected.addingTimeInterval(10_800))
        XCTAssertEqual(LimitFormatting.duration(reset!.timeIntervalSince(collected.addingTimeInterval(60)), language: .en), "2 hr 59 min")
        XCTAssertEqual(LimitFormatting.duration(reset!.timeIntervalSince(collected.addingTimeInterval(10_801)), language: .en), "now")
        XCTAssertNil(LimitFormatting.resetAt(window, collectedAt: nil))
        XCTAssertEqual(LimitFormatting.duration(nil, language: .en), "—")
    }

    func testAbsoluteResetWinsOverRelativeFallbackAndDurationSupportsDays() {
        let window: JSONValue = .object(["reset_at": .number(9_000), "reset_after_seconds": .number(50)])
        XCTAssertEqual(LimitFormatting.resetAt(window, collectedAt: Date(timeIntervalSince1970: 1_000)), Date(timeIntervalSince1970: 9_000))
        XCTAssertEqual(LimitFormatting.duration(5 * 86400 + 22 * 3600 + 53 * 60, language: .en), "5 days 22 hr 53 min")
        XCTAssertEqual(LimitFormatting.duration(17 * 3600 + 29 * 60, language: .zh), "17 小时 29 分钟")
        XCTAssertNil(LimitFormatting.timestamp(.number(.infinity)))
    }

    func testSnapshotAgesPastFreshThresholdWithoutAnotherFetch() {
        let rate: JSONValue = .object(["available": .bool(true), "captured_at_epoch": .number(1_000),
                                      "stale": .bool(false), "stale_after_seconds": .number(900)])
        let fresh = ClaudeLimitDetails(rate: rate, now: Date(timeIntervalSince1970: 1_600))
        let old = ClaudeLimitDetails(rate: rate, now: Date(timeIntervalSince1970: 1_901))
        XCTAssertEqual(fresh.stale, false)
        XCTAssertEqual(old.stale, true)
        XCTAssertEqual(LimitFormatting.age(since: fresh.capturedAt, now: Date(timeIntervalSince1970: 1_600), language: .en), "10 min")
        XCTAssertEqual(old.facts(now: Date(timeIntervalSince1970: 1_901), language: .en).first { $0.id == "state" }?.value, "Stale")
        let unknown = ClaudeLimitDetails(rate: .object(["available": .bool(true), "stale": .bool(false)]), now: Date())
        XCTAssertNil(unknown.stale)
    }

    func testLoginRequiresAuthoritativeCheckAndRespectsRecentSnapshot() {
        let now = Date(timeIntervalSince1970: 2_000)
        func rate(checked: Bool, loggedIn: Bool, captured: Double) -> JSONValue {
            .object(["available": .bool(true), "captured_at_epoch": .number(captured),
                     "auth_status": .object(["checked": .bool(checked), "logged_in": .bool(loggedIn)])])
        }
        XCTAssertEqual(ClaudeLimitDetails(rate: rate(checked: false, loggedIn: true, captured: 1_900), now: now).login, .unknown)
        XCTAssertEqual(ClaudeLimitDetails(rate: rate(checked: true, loggedIn: true, captured: 1_900), now: now).login, .loggedIn)
        XCTAssertEqual(ClaudeLimitDetails(rate: rate(checked: true, loggedIn: false, captured: 1_900), now: now).login, .unknown)
        XCTAssertEqual(ClaudeLimitDetails(rate: rate(checked: true, loggedIn: false, captured: 1_000), now: now).login, .requiresLogin)
    }

    func testBackgroundCaptureFactsAndOptionalPlanArePreserved() {
        let rate: JSONValue = .object(["available": .bool(true), "captured_at": .string("2026-11-05T23:00:00Z"),
                                      "capture_ready": .bool(true), "capture_method": .string("usage_command"),
                                      "plan_type": .string("Max"), "limit_reached": .bool(false),
                                      "auth_status": .object(["checked": .bool(true), "logged_in": .bool(true)])])
        let now = LimitFormatting.timestamp(.string("2026-11-05T23:10:00Z"))!
        let facts = Dictionary(uniqueKeysWithValues: ClaudeLimitDetails(rate: rate, now: now).facts(now: now, language: .en).map { ($0.id, $0) })
        XCTAssertEqual(facts["capture"]?.value, "Background /usage")
        XCTAssertEqual(facts["login"]?.value, "Logged in")
        XCTAssertEqual(facts["state"]?.value, "Fresh")
        XCTAssertEqual(facts["plan"]?.value, "Max")
        XCTAssertEqual(facts["reached"]?.value, "false")
    }
}
