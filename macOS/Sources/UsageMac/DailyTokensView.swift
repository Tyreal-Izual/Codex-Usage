import SwiftUI
import Charts

struct DailyTokensView: View {
    let reports: [Report: JSONValue]
    let sources: Set<String>
    let errors: [Report: String]
    let language: Language
    @State private var range: DailyTokenRange = .week

    var body: some View {
        if sources.contains("codex") || sources.contains("claude") {
            Panel(title: language.text("Daily Tokens", "每日 Token")) {
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    EqualWidthCardsLayout(minimumColumnWidth: 360, spacing: 18) {
                        if sources.contains("claude") { column(.claude, title: "Claude Code", now: context.date) }
                        if sources.contains("codex") { column(.local, title: "Codex", now: context.date) }
                    }
                }
            }
            .overlay(alignment: .topTrailing) {
                Picker(language.text("Time range", "时间范围"), selection: $range) {
                    ForEach(DailyTokenRange.allCases) { item in Text(item.title(language)).tag(item) }
                }.pickerStyle(.segmented).labelsHidden().frame(width: 200)
                    .padding(.horizontal, 20).padding(.top, 9)
            }
        }
    }

    private func column(_ report: Report, title: String, now: Date) -> some View {
        let local = reports[report]?[report == .claude ? "local_usage" : "sessions"] ?? .null
        let history = local["daily_tokens"]
        return VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.subheadline.weight(.bold))
            if history == .null || local["available"].flag == false {
                Text(reports[report] == nil && errors[report] == nil
                     ? language.text("Loading…", "正在加载…") : language.text("Daily usage unavailable", "每日用量暂不可用"))
                    .foregroundStyle(DashboardTheme.muted).frame(height: 150)
            } else {
                DailyTokenCard(series: DailyTokenSeries(history: history, range: range, now: now),
                               range: range, language: language,
                               tint: report == .claude ? DashboardTheme.good : DashboardTheme.accent)
                if errors[report] != nil || (local["parse_or_read_errors"].number ?? 0) > 0 {
                    Text(language.text("Some records could not be refreshed or read.", "部分记录未能刷新或读取。"))
                        .font(.caption).foregroundStyle(DashboardTheme.warning)
                }
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct DailyTokenCard: View {
    let series: DailyTokenSeries
    let range: DailyTokenRange
    let language: Language
    let tint: Color
    @State private var selected: Int?
    private var selectedBucket: DailyTokenSeries.Bucket? {
        guard let selected, series.buckets.indices.contains(selected) else { return nil }
        return series.buckets[selected]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(language.text("Today", "今日")).font(.caption.weight(.semibold)).foregroundStyle(DashboardTheme.muted)
                Text(number(series.today)).font(.title2.weight(.bold)).monospacedDigit()
                    .highlightChanges(value: String(series.today)).id(series.anchor)
                Spacer(minLength: 8)
                Text(range.title(language) + " · " + number(series.total))
                    .font(.caption.weight(.semibold)).foregroundStyle(DashboardTheme.muted)
                    .help(language.text("Selected period total", "所选范围累计"))
            }
            plot
            HStack {
                if let bucket = selectedBucket {
                    Text(dateLabel(bucket) + " · " + number(bucket.total) + " tokens")
                        .foregroundStyle(DashboardTheme.ink)
                } else {
                    Text(dateLabel(series.buckets.first!, end: series.buckets.last!.end))
                    Spacer()
                    if series.daysPerBar > 1 {
                        Text("\(series.daysPerBar) " + language.text("days / bar", "天 / 柱"))
                    }
                }
            }.font(.caption).foregroundStyle(DashboardTheme.muted).monospacedDigit().frame(height: 16)
            if series.unknown > 0 {
                Text(language.text("Undated tokens excluded: ", "未计入图表的未知日期用量：") + number(series.unknown))
                    .font(.caption).foregroundStyle(DashboardTheme.muted)
            }
        }.onChange(of: range) { selected = nil }
            .onChange(of: series.anchor) { selected = nil }
    }

    private var plot: some View {
        Chart(series.buckets) { bucket in
            RectangleMark(xStart: .value(language.text("Day", "日期"), Double(bucket.index) - 0.36),
                          xEnd: .value(language.text("Day", "日期"), Double(bucket.index) + 0.36),
                          yStart: .value("Tokens", 0), yEnd: .value("Tokens", bucket.total))
                .foregroundStyle(tint.opacity(bucket.index == selected || bucket.end == series.anchor ? 1 : 0.62))
                .cornerRadius(2)
                .accessibilityLabel(dateLabel(bucket))
                .accessibilityValue(number(bucket.total) + " tokens")
        }
        .chartXScale(domain: -0.5...max(0.5, Double(series.buckets.count) - 0.5))
        .chartYScale(domain: 0...max(1, series.buckets.map(\.total).max() ?? 1))
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(DashboardTheme.line)
                AxisValueLabel {
                    if let amount = value.as(Double.self) {
                        Text(amount.formatted(.number.notation(.compactName).locale(language.locale)))
                            .foregroundStyle(DashboardTheme.muted)
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let point):
                            guard let frame = proxy.plotFrame else { return }
                            let plot = geometry[frame]
                            guard plot.contains(point), let value = proxy.value(atX: point.x - plot.minX, as: Double.self) else {
                                selected = nil; return
                            }
                            selected = min(series.buckets.count - 1, max(0, Int(value.rounded())))
                        case .ended: selected = nil
                        }
                    }
            }
        }
        .frame(height: 105)
        .help(selectedBucket.map(details) ?? language.text("Hover for details; use arrow keys when focused.", "悬停查看明细；聚焦后可用方向键选择。"))
        .focusable()
        .onKeyPress(.leftArrow) { move(-1); return .handled }
        .onKeyPress(.rightArrow) { move(1); return .handled }
    }

    private func move(_ delta: Int) {
        selected = min(series.buckets.count - 1, max(0, (selected ?? (delta > 0 ? -1 : series.buckets.count)) + delta))
    }
    private func number(_ value: Double) -> String { JSONValue.number(value).display(locale: language.locale) }
    private func dateLabel(_ bucket: DailyTokenSeries.Bucket, end: Date? = nil) -> String {
        let format = Date.FormatStyle(date: .abbreviated, time: .omitted).locale(language.locale)
        let finish = end ?? bucket.end
        return bucket.start.formatted(format) + (finish == bucket.start ? "" : " – " + finish.formatted(format))
    }
    private func details(_ bucket: DailyTokenSeries.Bucket) -> String {
        let rows = [("input_tokens", language.text("Input", "输入")), ("output_tokens", language.text("Output", "输出")),
                    ("cached_input_tokens", language.text("Cached input (included in input)", "缓存输入（已包含在输入中）")),
                    ("cache_read_input_tokens", language.text("Cache read", "缓存读取")),
                    ("cache_creation_input_tokens", language.text("Cache creation", "缓存写入")),
                    ("cache_write_input_tokens", language.text("Cache write (detail)", "缓存写入（细项）")),
                    ("reasoning_output_tokens", language.text("Reasoning (included in output)", "推理（已包含在输出中）"))]
        return ([dateLabel(bucket), "Tokens: " + number(bucket.total)] + rows.compactMap { key, label in
            bucket.values[key].map { label + ": " + number($0) }
        }).joined(separator: "\n")
    }
}
