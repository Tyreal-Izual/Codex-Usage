import Foundation

enum FactTone: Equatable {
    case normal, good, warning, bad
}

struct PanelFact: Identifiable {
    let id: String
    let label: String
    let value: String
    var tone: FactTone = .normal
    var help = ""
    var tracksChanges = false
}

enum LimitFormatting {
    static func timestamp(_ value: JSONValue) -> Date? {
        if let seconds = value.number ?? Double(value.text), seconds.isFinite {
            let date = Date(timeIntervalSince1970: seconds)
            return (Date.distantPast...Date.distantFuture).contains(date) ? date : nil
        }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return parser.date(from: value.text) ?? ISO8601DateFormatter().date(from: value.text)
    }

    static func retrievedAt(_ data: JSONValue) -> Date? {
        guard let milliseconds = data["retrieved_at_unix_ms"].number else { return nil }
        return timestamp(.number(milliseconds / 1000))
    }

    static func resetAt(_ window: JSONValue, collectedAt: Date?) -> Date? {
        for key in ["reset_at", "resets_at"] {
            if let date = timestamp(window[key]) { return date }
        }
        guard let collectedAt, let seconds = window["reset_after_seconds"].number,
              seconds.isFinite, seconds >= 0 else { return nil }
        return timestamp(.number(collectedAt.timeIntervalSince1970 + seconds))
    }

    static func boolean(_ value: JSONValue, language: Language) -> String {
        guard let flag = value.flag else { return "—" }
        return flag ? language.text("true", "是") : language.text("false", "否")
    }

    static func balance(_ value: JSONValue, language: Language) -> String {
        guard let number = value.number ?? Double(value.text), number.isFinite else { return "—" }
        return number.formatted(.number.precision(.fractionLength(0...2))
            .locale(Locale(identifier: language == .zh ? "zh_CN" : "en_GB")))
    }

    static func duration(_ seconds: Double?, language: Language) -> String {
        guard let seconds, seconds.isFinite, seconds < Double(Int.max) else { return "—" }
        if seconds <= 0 { return language.text("now", "现在") }
        if seconds < 60 { return language.text("<1 min", "<1 分钟") }
        let minutes = Int(seconds / 60)
        let values = [(minutes / 1440, language.text("day", "天")),
                      (minutes / 60 % 24, language.text("hr", "小时")),
                      (minutes % 60, language.text("min", "分钟"))]
        return values.filter { $0.0 > 0 }.map { count, unit in
            let label = language == .en && unit == "day" && count != 1 ? "days" : unit
            return "\(count) \(label)"
        }.joined(separator: " ")
    }

    static func age(since date: Date?, now: Date, language: Language) -> String {
        guard let date else { return "—" }
        let seconds = max(0, now.timeIntervalSince(date))
        return seconds < 60 ? language.text("<1 min", "<1 分钟") : duration(seconds, language: language)
    }

    static func reachedTone(_ value: JSONValue) -> FactTone {
        guard let reached = value.flag else { return .normal }
        return reached ? .bad : .good
    }

    static func menuSummary(provider: String, primaryUsed: Double?, weeklyUsed: Double?, language: Language) -> String? {
        let windows = [(primaryUsed, language.text("5-hour", "5 小时")),
                       (weeklyUsed, language.text("Weekly", "每周"))]
        guard let (used, window) = windows.first(where: { $0.0?.isFinite == true }), let used else { return nil }
        let remaining = min(100, max(0, 100 - used))
        return provider + " · " + window + " · " + String(format: "%.0f%%", remaining)
            + language.text(" left", " 剩余")
    }
}

struct ClaudeLimitDetails {
    enum Login: Equatable { case loggedIn, requiresLogin, unknown }
    let rate: JSONValue
    let capturedAt: Date?
    let stale: Bool?
    let login: Login
    var available: Bool { rate["available"].flag == true }
    var captureReady: Bool? { rate["capture_ready"].flag ?? rate["capture_installed"].flag }

    init(rate: JSONValue, now: Date) {
        self.rate = rate
        capturedAt = LimitFormatting.timestamp(rate["captured_at_epoch"])
            ?? LimitFormatting.timestamp(rate["captured_at"])
        if rate["available"].flag != true {
            stale = nil
        } else if rate["stale"].flag == true {
            stale = true
        } else if let capturedAt {
            let threshold = rate["stale_after_seconds"].number.flatMap { $0.isFinite && $0 > 0 ? $0 : nil } ?? 900
            stale = now.timeIntervalSince(capturedAt) > threshold
        } else {
            stale = nil
        }
        let auth = rate["auth_status"]
        if auth["checked"].flag != true {
            login = .unknown
        } else if auth["logged_in"].flag == true {
            login = .loggedIn
        } else if auth["logged_in"].flag == false && (stale == true || rate["available"].flag != true) {
            login = .requiresLogin
        } else {
            // A recent snapshot can coexist with a differently authenticated CLI.
            login = .unknown
        }
    }

    func facts(now: Date, language: Language) -> [PanelFact] {
        let snapshot = stale.map { $0 ? language.text("Stale", "已过期") : language.text("Fresh", "新鲜") }
            ?? language.text("Unknown", "未知")
        let loginText: String
        let loginTone: FactTone
        switch login {
        case .loggedIn: loginText = language.text("Logged in", "已登录"); loginTone = .good
        case .requiresLogin: loginText = language.text("Login required", "需登录"); loginTone = .bad
        case .unknown: loginText = language.text("Unknown", "未知"); loginTone = .normal
        }
        let capture: String
        if rate["capture_method"].text == "usage_command" { capture = language.text("Background /usage", "后台 /usage") }
        else if rate["capture_installed"].flag == true { capture = "StatusLine" }
        else if captureReady == false { capture = language.text("Not installed", "未安装") }
        else { capture = language.text("Unknown", "未知") }
        var facts = [
            PanelFact(id: "age", label: language.text("Snapshot Age", "快照年龄"),
                      value: LimitFormatting.age(since: capturedAt, now: now, language: language),
                      help: capturedAt.map { language.text("Captured: ", "采集于：") + dateText($0, language: language) } ?? ""),
            PanelFact(id: "login", label: language.text("CLI Login", "CLI 登录"), value: loginText, tone: loginTone),
            PanelFact(id: "state", label: language.text("Snapshot State", "快照状态"), value: snapshot,
                      tone: stale == false ? .good : stale == true ? .warning : .normal),
            PanelFact(id: "capture", label: language.text("Usage Capture", "用量采集"), value: capture,
                      tone: captureReady == true ? .good : captureReady == false ? .warning : .normal)
        ]
        let plan = rate["plan_type"].text.isEmpty ? rate["plan"].text : rate["plan_type"].text
        if !plan.isEmpty { facts.append(PanelFact(id: "plan", label: language.text("Plan", "套餐"), value: plan)) }
        if rate["limit_reached"].flag != nil {
            facts.append(PanelFact(id: "reached", label: language.text("Limit Reached", "达到上限"),
                                   value: LimitFormatting.boolean(rate["limit_reached"], language: language),
                                   tone: LimitFormatting.reachedTone(rate["limit_reached"])))
        }
        return facts
    }
}
