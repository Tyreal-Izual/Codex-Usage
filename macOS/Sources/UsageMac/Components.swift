import SwiftUI

struct Panel<Content: View>: View {
    let title: String
    var subtitle: String = ""
    var facts: [PanelFact] = []
    var fillHeight = false
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PanelHeader(title: title, subtitle: subtitle, facts: facts)
                .padding(.horizontal, 20).padding(.vertical, 12)
                .background(DashboardTheme.panelStrong)
            DashboardDivider()
            VStack(alignment: .leading, spacing: 12) { content }
                .padding(.horizontal, 20).padding(.vertical, 16)
                .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        .foregroundStyle(DashboardTheme.ink)
        .background(DashboardTheme.panel)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(DashboardTheme.line) }
        .shadow(color: .black.opacity(0.18), radius: 12, y: 6)
    }
}

struct Metric: View {
    let title: String
    let value: String
    var detail: String = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption.weight(.semibold)).foregroundStyle(DashboardTheme.muted)
            Text(value).font(.system(.title2, design: .rounded, weight: .semibold)).monospacedDigit()
            if !detail.isEmpty { Text(detail).font(.caption).foregroundStyle(DashboardTheme.muted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

struct Notice: View {
    let text: String
    var warning = true
    var body: some View {
        Label(text, systemImage: warning ? "exclamationmark.triangle" : "info.circle")
            .font(.callout).foregroundStyle(warning ? DashboardTheme.warning : DashboardTheme.muted)
            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct LimitMeter: View {
    let title: String
    let used: Double?
    let hint: String
    let resetAt: Date?
    let now: Date
    let language: Language
    var stackFooter = false
    var tint: Color = DashboardTheme.accent
    var body: some View {
        let remaining = used.flatMap { $0.isFinite ? min(100, max(0, 100 - $0)) : nil }
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title).font(.subheadline.weight(.bold))
                Spacer()
                Text(remaining.map { String(format: "%.1f%%", $0) } ?? "—")
                    .font(.title3.weight(.bold)).monospacedDigit()
                    .highlightChanges(value: remaining.map { String(format: "%.1f", $0) })
                if remaining != nil {
                    Text(language.text("left", "剩余")).font(.caption).foregroundStyle(DashboardTheme.muted)
                }
            }
            ProgressView(value: remaining ?? 0, total: 100)
                .progressViewStyle(DashboardProgressStyle(color: (used ?? 0) >= 90 ? DashboardTheme.bad
                    : (used ?? 0) >= 75 ? DashboardTheme.warning : tint))
                .accessibilityLabel(title)
                .accessibilityValue(remaining.map { String(format: "%.1f%%", $0) } ?? language.text("Unavailable", "暂无数据"))
            if stackFooter {
                stackedFooter
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        hintLabel.fixedSize()
                        Spacer(minLength: 0)
                        resetLabel.fixedSize()
                    }
                    stackedFooter
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(DashboardTheme.field, in: RoundedRectangle(cornerRadius: 10))
        .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(DashboardTheme.line) }
    }

    private var hintLabel: some View {
        Text(hint).font(.caption).foregroundStyle(DashboardTheme.muted)
    }
    private var stackedFooter: some View {
        VStack(alignment: .leading, spacing: 6) {
            hintLabel.fixedSize(horizontal: false, vertical: true)
            resetLabel
        }
    }
    private var resetLabel: some View {
        Text(language.text("Resets In ", "距重置 ") + LimitFormatting.duration(resetAt.map { $0.timeIntervalSince(now) }, language: language))
            .font(.subheadline.weight(.semibold)).monospacedDigit()
            .help(resetAt.map { dateText($0, language: language) } ?? language.text("Reset time unavailable", "重置时间未知"))
    }
}

struct TabularRow: Identifiable {
    let id: OccurrenceID
    let cells: [String]
}

struct TableHeading: Identifiable {
    let id: Int
    let title: String
}

struct RecordTable: View {
    let headers: [String]
    let rows: [TabularRow]
    let language: Language
    var body: some View {
        if rows.isEmpty {
            Text(language.text("No records yet", "暂无记录")).foregroundStyle(DashboardTheme.muted).padding(.vertical, 8)
        } else {
            Table(rows) {
                TableColumnForEach(headers.enumerated().map { TableHeading(id: $0.offset, title: $0.element) }) { heading in
                    TableColumn(heading.title) { (row: TabularRow) in
                        Text(row.cells.indices.contains(heading.id) ? row.cells[heading.id] : "—")
                            .monospacedDigit().textSelection(.enabled)
                            .help(row.cells.indices.contains(heading.id) ? row.cells[heading.id] : "")
                    }.width(min: 90, ideal: heading.id == 0 ? 180 : 120)
                }
            }
            .tableStyle(.inset)
            .scrollContentBackground(.hidden)
            .background(DashboardTheme.field)
            .frame(height: min(360, CGFloat(rows.count) * 28 + 36))
        }
    }
}

func rows(_ items: [JSONValue], identity: String, keys: [String], language: Language) -> [TabularRow] {
    identifiedValues(items, key: { $0[identity].display }).map { entry in
        TabularRow(id: entry.id, cells: keys.map { path in
            path.split(separator: ".").reduce(entry.value) { $0[String($1)] }.display(locale: language.locale)
        })
    }
}

func arrayRows(_ items: [JSONValue], language: Language) -> [TabularRow] {
    identifiedValues(items, key: { $0.items.map(\.display).joined(separator: "|") }).map { entry in
        TabularRow(id: entry.id, cells: entry.value.items.map { $0.display(locale: language.locale) })
    }
}

func dateText(_ date: Date, language: Language) -> String {
    date.formatted(Date.FormatStyle(date: .abbreviated, time: .shortened)
        .locale(language.locale))
}

func localDate(_ value: JSONValue, language: Language) -> String {
    if let epoch = value.number { return dateText(Date(timeIntervalSince1970: epoch), language: language) }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let date = formatter.date(from: value.text) ?? ISO8601DateFormatter().date(from: value.text)
    return date.map { dateText($0, language: language) } ?? value.display(locale: language.locale)
}

struct SourceSection<Content: View>: View {
    let report: Report
    let model: DashboardModel
    var fillHeight = false
    @ViewBuilder let content: (JSONValue) -> Content
    var body: some View {
        if model.sources.contains(report.source) {
            VStack(alignment: .leading, spacing: 12) {
                if let error = model.errors[report] { Notice(text: error) }
                if let data = model.reports[report] {
                    content(data)
                } else if model.pending.contains(report) {
                    HStack { ProgressView().controlSize(.small); Text(model.language.text("Loading…", "正在加载…")) }
                        .padding(20).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        }
    }
}
