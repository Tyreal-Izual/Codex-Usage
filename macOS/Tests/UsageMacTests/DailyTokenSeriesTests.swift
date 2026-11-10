import XCTest
@testable import UsageMac

final class DailyTokenSeriesTests: XCTestCase {
    private func calendar(_ zone: String = "Europe/London") -> Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = TimeZone(identifier: zone)!
        return result
    }
    private func date(_ value: String, _ calendar: Calendar) -> Date {
        DailyTokenSeries.date(value, calendar: calendar)!
    }
    private func history(_ rows: [(String, Double)], unknown: Double = 0) -> JSONValue {
        .object(["days": .array(rows.map { .object(["date": .string($0.0), "total_tokens": .number($0.1)]) }),
                 "unknown_date_tokens": .number(unknown)])
    }

    func testWeekMeansSevenCalendarDaysIncludingZeroDaysAndToday() {
        let calendar = calendar()
        let series = DailyTokenSeries(history: history([("2026-11-01", 500), ("2026-11-05", 20),
                                                       ("2026-11-10", 30), ("2026-11-11", 100)]),
                                      range: .week, now: date("2026-11-10", calendar), calendar: calendar)
        XCTAssertEqual(series.buckets.count, 7)
        XCTAssertEqual(series.buckets.map(\.total), [0, 20, 0, 0, 0, 0, 30])
        XCTAssertEqual(series.total, 50)
        XCTAssertEqual(series.today, 30)
    }

    func testLongHistoryBucketsKeepEveryTokenAndUseAtMostSixtyBars() {
        let calendar = calendar()
        let start = date("2025-01-01", calendar)
        let rows = (0..<500).map { offset in
            let day = calendar.date(byAdding: .day, value: offset, to: start)!
            let c = calendar.dateComponents([.year, .month, .day], from: day)
            return (String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!), Double(offset + 1))
        }
        let series = DailyTokenSeries(history: history(rows, unknown: 123), range: .all,
                                      now: date(rows.last!.0, calendar), calendar: calendar)
        XCTAssertLessThanOrEqual(series.buckets.count, 60)
        XCTAssertEqual(Set(series.buckets.map(\.id)).count, series.buckets.count)
        XCTAssertEqual(series.today, 500)
        XCTAssertEqual(series.total, 125250)
        XCTAssertEqual(series.unknown, 123)
        XCTAssertEqual(series.buckets.last!.end, series.anchor)
    }

    func testDSTDoesNotChangeDayCountAndMidnightAdvancesToday() {
        let calendar = calendar()
        let data = history([("2026-10-24", 10), ("2026-10-25", 20)])
        let first = DailyTokenSeries(history: data, range: .week, now: date("2026-10-25", calendar), calendar: calendar)
        let next = DailyTokenSeries(history: data, range: .week, now: date("2026-10-26", calendar), calendar: calendar)
        XCTAssertEqual(first.buckets.count, 7)
        XCTAssertEqual(next.buckets.count, 7)
        XCTAssertEqual(first.today, 20)
        XCTAssertEqual(next.today, 0)
        XCTAssertEqual(first.total, next.total)
        XCTAssertEqual(first.buckets[1].id, next.buckets[0].id)
    }

    func testInvalidDatesAndNonfiniteAmountsDoNotBreakChartScale() {
        let calendar = calendar()
        let series = DailyTokenSeries(history: history([("2026-02-30", 100), ("unknown", 200),
                                                       ("2026-11-09", -.infinity), ("2026-11-10", .nan)]),
                                      range: .month, now: date("2026-11-10", calendar), calendar: calendar)
        XCTAssertEqual(series.buckets.count, 30)
        XCTAssertEqual(series.total, 0)
        XCTAssertEqual(series.today, 0)
    }

    func testEmptyHistoryAndUnknownOnlyHistoryHaveNoInventedUsage() {
        let calendar = calendar()
        let series = DailyTokenSeries(history: history([], unknown: 200), range: .all,
                                      now: date("2026-11-10", calendar), calendar: calendar)
        XCTAssertEqual(series.buckets.count, 1)
        XCTAssertEqual(series.total, 0)
        XCTAssertEqual(series.today, 0)
        XCTAssertEqual(series.unknown, 200)
    }
}
