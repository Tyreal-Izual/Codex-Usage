import SwiftUI

struct ModelDistribution {
    struct Row: Identifiable {
        let id: String
        let count: String
        let tokens: Double?
        let colorIndex: Int
    }
    let rows: [Row]
    let total: Double?

    init(items: [JSONValue], tokenKey: String, countKey: String) {
        rows = items.enumerated().map { index, item in
            let amount = item[tokenKey].number.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
            return Row(id: item["model"].display, count: item[countKey].display, tokens: amount, colorIndex: index)
        }
        let known = rows.compactMap(\.tokens)
        total = known.isEmpty ? nil : known.reduce(0, +)
    }

    func share(of row: Row) -> Double? {
        guard let total, total > 0, let tokens = row.tokens else { return nil }
        return tokens / total
    }
}

struct ModelUsage: View {
    let title: String
    let items: [JSONValue]
    let tokenKey: String
    let countKey: String
    let language: Language
    var subtitle = ""
    var updatedAt: Double?
    var fillHeight = false
    var unavailable = false
    var detailTitle = ""
    var showDetails: (() -> Void)?

    var body: some View {
        let distribution = ModelDistribution(items: items, tokenKey: tokenKey, countKey: countKey)
        TimelineView(.periodic(from: .now, by: 60)) { timeline in
            Panel(title: title, subtitle: subtitle, facts: updateFacts(now: timeline.date), fillHeight: fillHeight) {
                HStack {
                    HStack(spacing: 4) {
                        Text(distribution.total.map { JSONValue.number($0).display } ?? "—")
                            .highlightChanges(value: distribution.total.map { JSONValue.number($0).display })
                        Text(language.text("Tokens Used", "已用 token"))
                    }.accessibilityElement(children: .combine)
                    Spacer()
                    HStack(spacing: 4) {
                        Text(unavailable ? "—" : String(distribution.rows.count))
                            .highlightChanges(value: unavailable ? nil : String(distribution.rows.count))
                        Text(language.text("Models", "个模型"))
                    }.accessibilityElement(children: .combine)
                }.font(.subheadline.weight(.semibold)).foregroundStyle(DashboardTheme.muted).monospacedDigit()
                ModelShareBar(distribution: distribution)
                if distribution.rows.isEmpty {
                    Text(unavailable ? language.text("Model data unavailable", "模型数据暂不可用")
                         : language.text("No model records yet", "暂无模型记录"))
                        .foregroundStyle(DashboardTheme.muted).padding(.vertical, 12)
                } else {
                    ModelUsageTable(distribution: distribution, countKey: countKey, language: language)
                }
                if let showDetails {
                    Button(action: showDetails) {
                        HStack(spacing: 6) { Text(detailTitle); Image(systemName: "arrow.right") }
                            .font(.subheadline.weight(.semibold)).padding(.vertical, 5)
                    }
                    .buttonStyle(.plain).foregroundStyle(DashboardTheme.accent)
                }
            }
        }
    }

    private func updateFacts(now: Date) -> [PanelFact] {
        guard let updatedAt, updatedAt.isFinite, updatedAt > 0,
              let date = LimitFormatting.timestamp(.number(updatedAt / 1000)) else { return [] }
        return [PanelFact(id: "updated", label: language.text("Updated", "更新于"),
                          value: LimitFormatting.age(since: date, now: now, language: language),
                          help: dateText(date, language: language))]
    }
}

private struct ModelShareBar: View {
    let distribution: ModelDistribution
    var body: some View {
        GeometryReader { geometry in
            HStack(spacing: 0) {
                ForEach(distribution.rows) { row in
                    let share = distribution.share(of: row)
                    let color = DashboardTheme.modelColors[row.colorIndex % DashboardTheme.modelColors.count]
                    let tokens = row.tokens.map { JSONValue.number($0).display } ?? "—"
                    let percent = share.map { String(format: "%.1f%%", $0 * 100) } ?? "—"
                    let help = "\(row.id): \(tokens) (\(percent))"
                    Rectangle().fill(color)
                        .frame(width: geometry.size.width * CGFloat(share ?? 0))
                        .help(help)
                }
            }
        }
        .frame(height: 14)
        .background(DashboardTheme.track)
        .clipShape(Capsule())
        .accessibilityHidden(true) // Every value is also exposed in the labelled table below.
    }
}

private struct ModelUsageTable: View {
    let distribution: ModelDistribution
    let countKey: String
    let language: Language
    private var countTitle: String { countKey == "threads" ? language.text("Threads", "会话") : language.text("Requests", "请求") }
    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 0) {
            GridRow {
                Text(language.text("Model", "模型"))
                Text(countTitle).gridColumnAlignment(.trailing)
                Text(language.text("Tokens used", "已用 token")).gridColumnAlignment(.trailing)
                Text(language.text("Share", "占比")).gridColumnAlignment(.trailing)
            }.font(.caption.weight(.bold)).foregroundStyle(DashboardTheme.muted).padding(.vertical, 10)
            DashboardDivider().gridCellUnsizedAxes(.horizontal)
            ForEach(distribution.rows) { row in
                GridRow(alignment: .center) {
                    HStack(spacing: 8) {
                        Circle().fill(DashboardTheme.modelColors[row.colorIndex % DashboardTheme.modelColors.count]).frame(width: 9, height: 9).accessibilityHidden(true)
                        Text(row.id).fontWeight(.semibold).lineLimit(2).help(row.id)
                    }.frame(minWidth: 70, maxWidth: .infinity, alignment: .leading)
                    Text(row.count).fixedSize().highlightChanges(value: row.count)
                    Text(row.tokens.map { JSONValue.number($0).display } ?? "—").fontWeight(.medium).fixedSize()
                        .highlightChanges(value: row.tokens.map { JSONValue.number($0).display })
                    Text(distribution.share(of: row).map { String(format: "%.1f%%", $0 * 100) } ?? "—").fontWeight(.semibold).fixedSize()
                        .highlightChanges(value: distribution.share(of: row).map { String(format: "%.1f", $0 * 100) })
                }
                .font(.subheadline).monospacedDigit().padding(.vertical, 9)
                .accessibilityElement(children: .combine)
                DashboardDivider().gridCellUnsizedAxes(.horizontal)
            }
        }
        .textSelection(.enabled)
    }
}
