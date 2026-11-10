import Foundation

struct ResetCreditDetails {
    enum State: Equatable {
        case available, expiringSoon, inProgress, redeemed, expired, unknown

        var sortOrder: Int {
            switch self {
            case .available, .expiringSoon: return 0
            case .inProgress, .unknown: return 1
            case .redeemed, .expired: return 2
            }
        }
    }

    struct Credit: Identifiable {
        let id: OccurrenceID
        let data: JSONValue
        let expiresAt: Date?
        let grantedAt: Date?
        let state: State
        let sourceOrder: Int

        func title(_ language: Language) -> String {
            switch data["reset_type"].text {
            case "codex_rate_limits": return language.text("Codex reset", "Codex 重置")
            case "primary": return language.text("Primary window", "主窗口")
            case "weekly": return language.text("Weekly window", "每周窗口")
            case "": return language.text("Reset credit", "重置额度")
            default: return data["reset_type"].display
            }
        }

        func statusText(_ language: Language) -> String {
            switch state {
            case .available: return language.text("Available", "可用")
            case .expiringSoon: return language.text("Expires soon", "即将到期")
            case .inProgress: return language.text("In progress", "处理中")
            case .redeemed: return language.text("Used", "已使用")
            case .expired: return language.text("Expired", "已过期")
            case .unknown: return data["status"].text.isEmpty ? language.text("Unknown", "未知") : data["status"].text
            }
        }

        func timeRemaining(now: Date, language: Language) -> String {
            if state == .redeemed { return "—" }
            if state == .expired { return language.text("Expired", "已过期") }
            guard let expiresAt else { return "—" }
            if expiresAt <= now { return language.text("Expired", "已过期") }
            return LimitFormatting.duration(expiresAt.timeIntervalSince(now), language: language)
        }
    }

    static let soonInterval: TimeInterval = 7 * 24 * 60 * 60
    let credits: [Credit]
    let availableCount: Double?
    let totalEarnedCount: Double?
    let hasCreditList: Bool
    var expiringSoonCount: Int { credits.filter { $0.state == .expiringSoon }.count }

    init(data: JSONValue, now: Date) {
        availableCount = Self.count(data["available_count"])
        totalEarnedCount = Self.count(data["total_earned_count"])
        if case .array = data["credits"] { hasCreditList = true } else { hasCreditList = false }
        // Identity excludes status/countdown so time passing does not recreate a row.
        let identified = identifiedValues(data["credits"].items) { item in
            [item["reset_type"].display, item["granted_at"].display, item["expires_at"].display].joined(separator: "|")
        }
        credits = identified.enumerated().map { index, entry in
            let item = entry.value
            let expires = LimitFormatting.timestamp(item["expires_at"])
            let granted = LimitFormatting.timestamp(item["granted_at"])
            let state: State
            switch item["status"].text.lowercased() {
            case "available":
                if let expires, expires <= now { state = .expired }
                else if let expires, expires.timeIntervalSince(now) <= Self.soonInterval { state = .expiringSoon }
                else { state = .available }
            case "expired": state = .expired
            case "redeemed", "used", "consumed": state = .redeemed
            case "redeeming", "pending", "in_progress": state = .inProgress
            default: state = .unknown
            }
            return Credit(id: entry.id, data: item, expiresAt: expires, grantedAt: granted,
                          state: state, sourceOrder: index)
        }.sorted { first, second in
            if first.state.sortOrder != second.state.sortOrder { return first.state.sortOrder < second.state.sortOrder }
            let a = first.expiresAt ?? .distantFuture, b = second.expiresAt ?? .distantFuture
            return a == b ? first.sourceOrder < second.sourceOrder : a < b
        }
    }

    private static func count(_ value: JSONValue) -> Double? {
        guard let number = value.number ?? Double(value.text), number.isFinite,
              number >= 0, number.rounded(.towardZero) == number else { return nil }
        return number
    }
}
