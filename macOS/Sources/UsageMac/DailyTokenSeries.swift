import Foundation

enum DailyTokenRange: String, CaseIterable, Identifiable {
    case week, month, all
    var id: String { rawValue }
    var days: Int? { self == .week ? 7 : self == .month ? 30 : nil }
    func title(_ language: Language) -> String {
        switch self {
        case .week: return language.text("7 days", "7 天")
        case .month: return language.text("30 days", "30 天")
        case .all: return language.text("All", "全部")
        }
    }
}

struct DailyTokenSeries {
    struct Bucket: Identifiable {
        var id: Date { start }
        let index: Int
        let start: Date
        let end: Date
        var values: [String: Double] = [:]
        var total: Double { values["total_tokens", default: 0] }
    }
    let buckets: [Bucket]
    let today: Double
    let total: Double
    let unknown: Double
    let daysPerBar: Int
    let anchor: Date

    init(history: JSONValue, range: DailyTokenRange, now: Date, calendar: Calendar = Self.localCalendar) {
        let anchor = calendar.startOfDay(for: now)
        self.anchor = anchor
        unknown = Self.amount(history["unknown_date_tokens"])
        let rows = history["days"].items.compactMap { row -> (Date, [String: Double])? in
            guard let date = Self.date(row["date"].text, calendar: calendar), date <= anchor else { return nil }
            let values = row.object.filter { $0.key.hasSuffix("tokens") }.mapValues(Self.amount)
            return (date, values)
        }
        let start = range.days.map { calendar.date(byAdding: .day, value: 1 - $0, to: anchor)! }
            ?? rows.map(\.0).min() ?? anchor
        let count = max(1, calendar.dateComponents([.day], from: start, to: anchor).day! + 1)
        let daysPerBar = max(1, Int(ceil(Double(count) / 60)))
        self.daysPerBar = daysPerBar
        var result = stride(from: 0, to: count, by: daysPerBar).enumerated().map { index, offset in
            Bucket(index: index, start: calendar.date(byAdding: .day, value: offset, to: start)!,
                   end: calendar.date(byAdding: .day, value: min(count - 1, offset + daysPerBar - 1), to: start)!)
        }
        var todayTotal = 0.0
        for (date, values) in rows {
            if date == anchor { todayTotal += values["total_tokens", default: 0] }
            guard date >= start else { continue }
            let offset = calendar.dateComponents([.day], from: start, to: date).day! / daysPerBar
            for (key, value) in values { result[offset].values[key, default: 0] += value }
        }
        buckets = result
        today = todayTotal
        total = result.reduce(0) { $0 + $1.total }
    }

    static var localCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        return calendar
    }

    private static func amount(_ value: JSONValue) -> Double {
        guard let number = value.number, number.isFinite, number >= 0 else { return 0 }
        return number
    }

    static func date(_ string: String, calendar: Calendar) -> Date? {
        let parts = string.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, (1970...9999).contains(parts[0]), (1...12).contains(parts[1]), (1...31).contains(parts[2]),
              let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])),
              calendar.component(.month, from: date) == parts[1], calendar.component(.day, from: date) == parts[2] else { return nil }
        return date
    }
}
