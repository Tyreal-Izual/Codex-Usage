import XCTest
@testable import UsageMac

final class ResetCreditDetailsTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func credit(_ name: String, status: String = "available", expiresIn: Double?) -> JSONValue {
        .object(["reset_type": .string(name), "status": .string(status),
                 "granted_at": .number(now.timeIntervalSince1970 - 86_400),
                 "expires_at": expiresIn.map { .number(now.timeIntervalSince1970 + $0) } ?? .null])
    }

    func testActiveCreditsComeFirstWithSoonestExpiryAtTheTop() {
        let data: JSONValue = .object(["credits": .array([
            credit("used", status: "redeemed", expiresIn: -100),
            credit("later", expiresIn: 20 * 86_400), credit("soon", expiresIn: 3_600),
            credit("unknown-date", expiresIn: nil), credit("expired", expiresIn: -10)
        ])])
        let result = ResetCreditDetails(data: data, now: now)
        XCTAssertEqual(result.credits.map { $0.data["reset_type"].text }, ["soon", "later", "unknown-date", "used", "expired"])
        XCTAssertEqual(result.expiringSoonCount, 1)
        XCTAssertEqual(result.credits.first?.timeRemaining(now: now, language: .en), "1 hr")
    }

    func testExpirationUpdatesWithoutChangingReportedAvailableCount() {
        let data: JSONValue = .object(["available_count": .number(3), "total_earned_count": .number(0),
                                      "credits": .array([credit("one", expiresIn: 60)])])
        let before = ResetCreditDetails(data: data, now: now)
        let after = ResetCreditDetails(data: data, now: now.addingTimeInterval(60))
        XCTAssertEqual(before.credits[0].state, .expiringSoon)
        XCTAssertEqual(after.credits[0].state, .expired)
        XCTAssertEqual(after.credits[0].timeRemaining(now: now.addingTimeInterval(60), language: .en), "Expired")
        XCTAssertEqual(after.expiringSoonCount, 0)
        XCTAssertEqual(after.availableCount, 3)
        XCTAssertEqual(after.totalEarnedCount, 0)
        XCTAssertEqual(before.credits[0].id, after.credits[0].id)
    }

    func testMissingAndInvalidValuesStayUnknownRatherThanZero() {
        let missing = ResetCreditDetails(data: .null, now: now)
        XCTAssertNil(missing.availableCount)
        XCTAssertFalse(missing.hasCreditList)
        let zero = ResetCreditDetails(data: .object(["available_count": .number(0), "credits": .array([])]), now: now)
        XCTAssertEqual(zero.availableCount, 0)
        XCTAssertTrue(zero.hasCreditList)
        for value in [JSONValue.number(-1), .number(0.5), .bool(false), .string("NaN")] {
            XCTAssertNil(ResetCreditDetails(data: .object(["available_count": value]), now: now).availableCount)
        }
        let unknownDate = ResetCreditDetails(data: .object(["credits": .array([credit("one", expiresIn: nil)])]), now: now)
        XCTAssertEqual(unknownDate.credits[0].timeRemaining(now: now, language: .en), "—")
        XCTAssertEqual(unknownDate.expiringSoonCount, 0)
    }

    func testOnlyAvailableCreditsCanBeMarkedExpiringSoon() {
        let data: JSONValue = .object(["credits": .array([
            credit("used", status: "redeemed", expiresIn: 300),
            credit("held", status: "held", expiresIn: 300),
            credit("pending", status: "pending", expiresIn: 300),
            credit("edge", expiresIn: ResetCreditDetails.soonInterval),
            credit("outside", expiresIn: ResetCreditDetails.soonInterval + 1)
        ])])
        let result = ResetCreditDetails(data: data, now: now)
        XCTAssertEqual(result.expiringSoonCount, 1)
        XCTAssertEqual(result.credits.first { $0.data["reset_type"].text == "used" }?.timeRemaining(now: now, language: .en), "—")
        XCTAssertEqual(result.credits.first { $0.data["reset_type"].text == "held" }?.state, .unknown)
        XCTAssertEqual(result.credits.first { $0.data["reset_type"].text == "pending" }?.state, .inProgress)
    }

    func testIdenticalRecordsRemainSeparateAndKeepStableIDs() {
        let entry = credit("codex_rate_limits", expiresIn: 300)
        let data: JSONValue = .object(["credits": .array([entry, entry])])
        let a = ResetCreditDetails(data: data, now: now)
        let b = ResetCreditDetails(data: data, now: now.addingTimeInterval(60))
        XCTAssertEqual(Set(a.credits.map(\.id)).count, 2)
        XCTAssertEqual(a.credits.map(\.id), b.credits.map(\.id))
        XCTAssertEqual(a.credits[0].title(.zh), "Codex 重置")
        XCTAssertEqual(a.credits[0].statusText(.zh), "即将到期")
    }
}
