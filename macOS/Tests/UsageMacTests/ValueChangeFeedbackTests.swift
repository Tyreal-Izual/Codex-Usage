import XCTest
@testable import UsageMac

final class ValueChangeFeedbackTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)

    func testInitialLoadAndMissingValuesDoNotFlashButZeroCanChange() {
        var feedback = ValueChangeFeedback()
        feedback.observe(nil, at: start)
        feedback.observe("0", at: start)
        XCTAssertNil(feedback.changedAt)
        XCTAssertEqual(feedback.remaining(at: start), 0)
        feedback.observe("1", at: start.addingTimeInterval(1))
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(1)), 4)
        feedback.observe(nil, at: start.addingTimeInterval(2))
        XCTAssertNil(feedback.changedAt)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(2)), 0)
        feedback.observe("0", at: start.addingTimeInterval(3))
        XCTAssertNil(feedback.changedAt)
    }

    func testIdenticalRefreshDoesNotRestartHighlight() {
        var feedback = ValueChangeFeedback()
        feedback.observe("100", at: start.addingTimeInterval(-1))
        feedback.observe("101", at: start)
        let revision = feedback.revision
        feedback.observe("101", at: start.addingTimeInterval(3))
        XCTAssertEqual(feedback.revision, revision)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(3)), 1)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(4)), 0)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(20)), 0)
    }

    func testRapidChangesStartNewWindowAndStayBoundedWhenClockMovesBack() {
        var feedback = ValueChangeFeedback()
        feedback.observe("10.0", at: start.addingTimeInterval(-1))
        feedback.observe("9.9", at: start)
        let revision = feedback.revision
        feedback.observe("9.8", at: start.addingTimeInterval(2))
        XCTAssertGreaterThan(feedback.revision, revision)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(4)), 2)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(6)), 0)
        XCTAssertEqual(feedback.remaining(at: start.addingTimeInterval(-100)), 4)
    }
}
