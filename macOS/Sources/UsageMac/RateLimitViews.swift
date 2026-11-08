import SwiftUI

struct CodexLimits: View {
    let data: JSONValue
    let language: Language
    var fillHeight = false
    private var rate: JSONValue { data["endpoints"]["rate_limit_status"]["data"] }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { timeline in
            let windows = LimitWindows(rate["rate_limit"])
            let collected = LimitFormatting.retrievedAt(data)
            Panel(title: language.text("Codex Online Rate Limits", "Codex 在线额度"),
                  subtitle: language.text("Read-only backend endpoints", "只读后端接口"),
                  facts: facts(now: timeline.date), fillHeight: fillHeight) {
                if data["endpoints"]["rate_limit_status"]["ok"].flag == false {
                    Notice(text: data["endpoints"]["rate_limit_status"]["error"].errorText)
                }
                EqualWidthCardsLayout(minimumColumnWidth: 300, spacing: 12) {
                    LimitMeter(title: language.text("Primary Window", "主额度窗口"),
                               used: windows.primary["used_percent"].number,
                               hint: language.text("Available before the primary limit is reached", "达到主额度上限前的剩余可用比例"),
                               resetAt: LimitFormatting.resetAt(windows.primary, collectedAt: collected),
                               now: timeline.date, language: language, stackFooter: fillHeight)
                    LimitMeter(title: language.text("Weekly Window", "每周窗口"),
                               used: windows.weekly["used_percent"].number,
                               hint: language.text("Available before the weekly limit is reached", "达到每周额度上限前的剩余可用比例"),
                               resetAt: LimitFormatting.resetAt(windows.weekly, collectedAt: collected),
                               now: timeline.date, language: language, stackFooter: fillHeight)
                }
                if rate["rate_limit"]["limit_reached"].flag == true {
                    Notice(text: language.text("Usage limit reached", "已达到用量上限"))
                }
            }
        }
    }

    private func facts(now: Date) -> [PanelFact] {
        let reached = rate["rate_limit"]["limit_reached"]
        let collected = LimitFormatting.retrievedAt(data)
        return [
            PanelFact(id: "plan", label: language.text("Plan", "套餐"), value: rate["plan_type"].display),
            PanelFact(id: "reached", label: language.text("Limit Reached", "达到上限"),
                      value: LimitFormatting.boolean(reached, language: language), tone: LimitFormatting.reachedTone(reached)),
            PanelFact(id: "updated", label: language.text("Updated", "更新于"),
                      value: LimitFormatting.age(since: collected, now: now, language: language),
                      help: collected.map { dateText($0, language: language) } ?? ""),
            PanelFact(id: "balance", label: language.text("Credits Balance", "积分余额"),
                      value: LimitFormatting.balance(rate["credits"]["balance"], language: language), tracksChanges: true),
            PanelFact(id: "credits", label: language.text("Has Credits", "有可用积分"),
                      value: LimitFormatting.boolean(rate["credits"]["has_credits"], language: language))
        ]
    }
}

struct ClaudeLimits: View {
    let data: JSONValue
    let language: Language
    var fillHeight = false
    private var rate: JSONValue { data["rate_limits"] }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { timeline in
            let details = ClaudeLimitDetails(rate: rate, now: timeline.date)
            Panel(title: language.text("Claude Code Rate Limits", "Claude Code 订阅额度"),
                  subtitle: language.text("Claude Code subscription usage snapshot", "Claude Code 订阅用量快照"),
                  facts: details.facts(now: timeline.date, language: language), fillHeight: fillHeight) {
                EqualWidthCardsLayout(minimumColumnWidth: 300, spacing: 12) {
                    LimitMeter(title: language.text("5-Hour Window", "5 小时窗口"),
                               used: rate["five_hour"]["used_percentage"].number,
                               hint: language.text("Available before the Claude 5-hour limit is reached", "达到 Claude 5 小时额度上限前的剩余可用比例"),
                               resetAt: LimitFormatting.resetAt(rate["five_hour"], collectedAt: nil),
                               now: timeline.date, language: language, stackFooter: fillHeight)
                    LimitMeter(title: language.text("7-Day Window", "7 天窗口"),
                               used: rate["seven_day"]["used_percentage"].number,
                               hint: language.text("Available before the Claude weekly limit is reached", "达到 Claude 每周额度上限前的剩余可用比例"),
                               resetAt: LimitFormatting.resetAt(rate["seven_day"], collectedAt: nil),
                               now: timeline.date, language: language, stackFooter: fillHeight)
                }
                if details.stale == true {
                    Notice(text: language.text("This snapshot is stale. Complete a Claude Code response or run the optional refresher.", "快照已过期。请完成一次 Claude Code 回复，或运行可选的后台刷新工具。"))
                }
                if details.login == .requiresLogin {
                    Notice(text: language.text("Sign in again with: claude auth login", "请重新登录：claude auth login"))
                }
                if !details.available || details.captureReady != true {
                    Notice(text: language.text("Enable limit capture once in Terminal:", "在终端执行一次以启用限额采集："), warning: false)
                    Text(rate["install_command"].text).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
        }
    }
}
