import SwiftUI

struct ResetCredits: View {
    let data: JSONValue
    let language: Language

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { timeline in
            let details = ResetCreditDetails(data: data, now: timeline.date)
            Panel(title: language.text("Codex Reset Credits", "Codex 重置额度"),
                  subtitle: language.text("Available first · by expiry", "可用额度优先 · 按到期排序"),
                  facts: facts(details, now: timeline.date)) {
                if !details.hasCreditList || data["ok"].flag == false {
                    Notice(text: language.text("Reset credit details are currently unavailable.", "暂时无法获取重置额度明细。"), warning: false)
                } else if details.credits.isEmpty {
                    Label(language.text("No reset credits returned", "暂无重置额度记录"), systemImage: "ticket")
                        .foregroundStyle(DashboardTheme.muted).padding(.vertical, 8)
                } else {
                    ViewThatFits(in: .horizontal) {
                        ResetCreditsTable(credits: details.credits, now: timeline.date, language: language)
                            .frame(minWidth: 840)
                        VStack(spacing: 8) {
                            ForEach(details.credits) { credit in
                                CompactResetCredit(credit: credit, now: timeline.date, language: language)
                            }
                        }
                    }
                }
            }
        }
    }

    private func facts(_ details: ResetCreditDetails, now: Date) -> [PanelFact] {
        let retrieved = LimitFormatting.retrievedAt(data)
        return [
            PanelFact(id: "available", label: language.text("Available", "可用"),
                      value: details.availableCount.map { JSONValue.number($0).display } ?? "—",
                      tone: (details.availableCount ?? 0) > 0 ? .good : .normal,
                      help: language.text("Count reported by Codex at the last update", "Codex 在上次更新时返回的可用数量"), tracksChanges: true),
            PanelFact(id: "soon", label: language.text("Expiring soon", "即将到期"),
                      value: details.hasCreditList ? String(details.expiringSoonCount) : "—",
                      tone: details.expiringSoonCount > 0 ? .warning : .normal,
                      help: language.text("Available credits expiring within 7 days", "七天内到期的可用额度"), tracksChanges: true),
            PanelFact(id: "updated", label: language.text("Updated", "更新于"),
                      value: LimitFormatting.age(since: retrieved, now: now, language: language)),
            PanelFact(id: "records", label: language.text("Records", "记录"),
                      value: details.hasCreditList ? String(details.credits.count) : "—", tracksChanges: true),
            PanelFact(id: "earned", label: language.text("Total earned", "累计获得"),
                      value: details.totalEarnedCount.map { JSONValue.number($0).display } ?? "—", tracksChanges: true)
        ]
    }
}

private extension ResetCreditDetails.State {
    var color: Color {
        switch self {
        case .available: return DashboardTheme.good
        case .expiringSoon, .inProgress: return DashboardTheme.warning
        case .expired: return DashboardTheme.bad
        case .redeemed, .unknown: return DashboardTheme.muted
        }
    }
    var symbol: String {
        switch self {
        case .available: return "checkmark.circle"
        case .expiringSoon: return "clock.badge.exclamationmark"
        case .inProgress: return "hourglass"
        case .redeemed: return "checkmark.seal"
        case .expired: return "xmark.circle"
        case .unknown: return "questionmark.circle"
        }
    }
}

private struct ResetCreditStatus: View {
    let credit: ResetCreditDetails.Credit
    let language: Language
    var body: some View {
        Label(credit.statusText(language), systemImage: credit.state.symbol)
            .font(.subheadline.weight(.semibold)).foregroundStyle(credit.state.color)
            .padding(.horizontal, 9).padding(.vertical, 5)
            .background(credit.state.color.opacity(0.1), in: Capsule())
            .overlay { Capsule().strokeBorder(credit.state.color.opacity(0.25)) }
            .help(language.text("Reported status: ", "服务端状态：") + credit.data["status"].display)
    }
}

private struct ResetCreditDate: View {
    let date: Date?
    let fallback: JSONValue
    let language: Language
    var body: some View {
        Text(date.map { dateText($0, language: language) } ?? fallback.display)
            .monospacedDigit()
            .help(fallback.text.isEmpty ? date.map { $0.ISO8601Format() } ?? "—" : fallback.display)
    }
}

private struct ResetCreditsTable: View {
    let credits: [ResetCreditDetails.Credit]
    let now: Date
    let language: Language
    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 0) {
            GridRow {
                Text(language.text("Credit", "额度")).frame(minWidth: 110, maxWidth: .infinity, alignment: .leading)
                Text(language.text("Status", "状态")).frame(minWidth: 120, maxWidth: .infinity, alignment: .leading)
                Text(language.text("Time remaining", "剩余时间")).frame(minWidth: 140, maxWidth: .infinity, alignment: .leading)
                Text(language.text("Expires · local", "到期时间 · 本地")).frame(minWidth: 145, maxWidth: .infinity, alignment: .leading)
                Text(language.text("Granted · local", "获得时间 · 本地")).frame(minWidth: 145, maxWidth: .infinity, alignment: .leading)
            }.font(.caption.weight(.bold)).foregroundStyle(DashboardTheme.muted).padding(.bottom, 10)
            DashboardDivider().gridCellUnsizedAxes(.horizontal)
            ForEach(Array(credits.enumerated()), id: \.element.id) { index, credit in
                GridRow {
                    HStack(spacing: 8) {
                        Text(String(format: "%02d", index + 1)).foregroundStyle(DashboardTheme.muted).monospacedDigit()
                        Text(credit.title(language)).fontWeight(.bold)
                    }.frame(minWidth: 110, maxWidth: .infinity, alignment: .leading).help(credit.data["reset_type"].display)
                    ResetCreditStatus(credit: credit, language: language).fixedSize()
                        .frame(minWidth: 120, maxWidth: .infinity, alignment: .leading)
                    Text(credit.timeRemaining(now: now, language: language))
                        .fontWeight(.semibold).monospacedDigit().foregroundStyle(credit.state == .available ? DashboardTheme.ink : credit.state.color).fixedSize()
                        .frame(minWidth: 140, maxWidth: .infinity, alignment: .leading)
                    ResetCreditDate(date: credit.expiresAt, fallback: credit.data["expires_at_local"], language: language)
                        .fontWeight(.medium).fixedSize()
                        .frame(minWidth: 145, maxWidth: .infinity, alignment: .leading)
                    ResetCreditDate(date: credit.grantedAt, fallback: credit.data["granted_at_local"], language: language)
                        .foregroundStyle(DashboardTheme.muted).fixedSize()
                        .frame(minWidth: 145, maxWidth: .infinity, alignment: .leading)
                }
                .font(.subheadline).padding(.vertical, 9)
                .accessibilityElement(children: .combine)
                DashboardDivider().gridCellUnsizedAxes(.horizontal)
            }
        }.textSelection(.enabled)
    }
}

private struct CompactResetCredit: View {
    let credit: ResetCreditDetails.Credit
    let now: Date
    let language: Language
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(credit.title(language)).font(.headline.weight(.bold))
                Spacer()
                ResetCreditStatus(credit: credit, language: language)
            }
            Text(language.text("Time remaining: ", "剩余时间：") + credit.timeRemaining(now: now, language: language))
                .font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(credit.state.color)
            LabeledContent(language.text("Expires", "到期")) {
                ResetCreditDate(date: credit.expiresAt, fallback: credit.data["expires_at_local"], language: language)
            }.fontWeight(.medium)
            LabeledContent(language.text("Granted", "获得")) {
                ResetCreditDate(date: credit.grantedAt, fallback: credit.data["granted_at_local"], language: language)
            }.foregroundStyle(DashboardTheme.muted)
        }
        .font(.subheadline).textSelection(.enabled)
        .padding(.horizontal, 14).padding(.vertical, 12).frame(maxWidth: .infinity, alignment: .leading)
        .background(DashboardTheme.field, in: RoundedRectangle(cornerRadius: 10))
        .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(DashboardTheme.line) }
    }
}
