import SwiftUI

struct RadarView: View {
    let snapshot: JSONValue
    let language: Language
    private var points: [JSONValue] { snapshot["data"]["points"].items }
    private var models: [String] { points.reduce(into: []) { if !$0.contains($1["model"].text) { $0.append($1["model"].text) } } }
    private let efforts = ["ultra", "max", "xhigh", "high", "medium", "low"]
    private let columns = Array(repeating: GridItem(.flexible(minimum: 105), spacing: 10), count: 6)
    var body: some View {
        Panel(title: language.text("Degradation radar", "降智雷达"), subtitle: language.text("Published total scores · out of 150 · sync every 4 hours", "官网总分 · 满分 150 · 每 4 小时同步")) {
            if snapshot["stale"].flag == true {
                Notice(text: language.text("Showing the last successful snapshot. A retry is scheduled.", "正在显示上次成功的快照，稍后会自动重试。"))
            }
            if snapshot["cache_warning"] != .null { Notice(text: snapshot["cache_warning"].display) }
            if points.isEmpty {
                Text(snapshot["last_error"] == .null
                     ? language.text("Waiting for the first benchmark snapshot…", "正在等待首次评测快照…")
                     : language.text("Benchmark data is temporarily unavailable.", "评测数据暂时不可用。"))
                    .foregroundStyle(DashboardTheme.muted)
            }
            if !points.isEmpty {
                // One shared scroller keeps all model rows aligned on narrow windows.
                ScrollView(.horizontal) {
                    VStack(alignment: .leading, spacing: 16) {
                        ForEach(models, id: \.self) { model in
                            let family = points.filter { $0["model"].text == model }
                            VStack(alignment: .leading, spacing: 8) {
                                Text(model).font(.subheadline.weight(.bold))
                                LazyVGrid(columns: columns, spacing: 10) {
                                    ForEach(efforts, id: \.self) { effort in
                                        if let point = family.first(where: { $0["effort"].text == effort }) {
                                            RadarScoreCard(point: point, language: language)
                                        } else {
                                            Color.clear.accessibilityHidden(true)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .containerRelativeFrame(.horizontal) { width, _ in max(width, 680) }
                    .padding(.bottom, 4)
                }
            }
            DashboardDivider()
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(language.text("Synced: ", "同步于：") + localDate(snapshot["fetched_at"], language: language))
                    Text(language.text("Test period: ", "测试时段：") + localDate(snapshot["data"]["source_started_at"], language: language) + " – " + localDate(snapshot["data"]["source_updated_at"], language: language))
                    Text(language.text("Next check: ", "下次检查：") + localDate(snapshot["next_attempt_at"], language: language))
                }.font(.caption).foregroundStyle(DashboardTheme.muted)
                Spacer()
                Link(language.text("Source ↗", "来源 ↗"), destination: URL(string: "https://codexradar.com/#stationmaster-round")!)
            }
        }
    }
}

private struct RadarScoreCard: View {
    let point: JSONValue
    let language: Language
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    private var model: String { point["model"].text }
    private var color: Color { DashboardTheme.radarColor(model) }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(point["effort"].display).font(.caption.weight(.semibold)).foregroundStyle(DashboardTheme.muted)
            Text(point["score"].number.map { String(format: "%.2f", $0) } ?? "—")
                .font(.system(.title3, design: .rounded, weight: .semibold)).monospacedDigit()
                .foregroundStyle(color)
                .highlightChanges(value: point["score"].number.map { String(format: "%.2f", $0) })
            ProgressView(value: point["score"].number ?? 0, total: 150)
                .progressViewStyle(DashboardProgressStyle(color: color, height: 6, divisions: 3))
        }
        .padding(.horizontal, 12).padding(.vertical, 10).frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 9)
                .fill(LinearGradient(colors: [.white.opacity(0.035), .clear], startPoint: .topLeading, endPoint: .bottomTrailing))
        }
        .background(DashboardTheme.field, in: RoundedRectangle(cornerRadius: 9))
        .overlay { RoundedRectangle(cornerRadius: 9).strokeBorder(DashboardTheme.line) }
        .overlay {
            RoundedRectangle(cornerRadius: 9).strokeBorder(color, lineWidth: 2)
                .mask(alignment: .top) { Rectangle().frame(height: 10) }
                .allowsHitTesting(false)
        }
        .overlay {
            RoundedRectangle(cornerRadius: 9).strokeBorder(color, lineWidth: 1)
                .opacity(hovered ? 1 : 0)
                .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: hovered)
                .allowsHitTesting(false)
        }
        .contentShape(RoundedRectangle(cornerRadius: 9))
        .onHover { hovered = $0 }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(model) \(point["effort"].display)")
        .accessibilityValue(point["score"].number.map { String(format: "%.2f / 150", $0) } ?? language.text("Not tested", "未测"))
    }
}

struct IsambardView: View {
    let data: JSONValue
    let language: Language
    var maintenance = true
    var body: some View {
        Panel(title: language.text("Isambard Status", "Isambard 服务状态"), subtitle: localDate(data["status"]["fetched_at"], language: language)) {
            if data["warning"] != .null { Notice(text: data["warning"].display) }
            EqualWidthCardsLayout(minimumColumnWidth: 250, maximumColumns: 3, spacing: 12) {
                ForEach(data["status"]["statuses"].items, id: \.statusIdentity) { status in
                    ServiceStatusCard(status: status, language: language)
                }
            }
            if maintenance {
                DashboardDivider()
                Text(language.text("Planned maintenance", "计划维护")).font(.headline)
                RecordTable(headers: data["status"]["maintenance_headers"].items.map(\.display),
                            rows: data["status"]["maintenance_rows"].items.map {
                    TabularRow(id: $0.items.map(\.display).joined(separator: "|"), cells: $0.items.map(\.display))
                }, language: language)
            }
        }
    }
}

private extension JSONValue {
    // Status text can change independently of the service's identity.
    var statusIdentity: String { self["title"].text.components(separatedBy: ":").first ?? self["title"].text }
}

struct AdminView: View {
    let data: JSONValue
    let language: Language
    var body: some View {
        VStack(spacing: 14) {
            Panel(title: language.text("Organization usage", "组织用量")) {
                if data["usage"]["error"] != .null { Notice(text: data["usage"]["error"].errorText) }
                if data["usage"]["has_more"].flag == true { Notice(text: language.text("More records exist beyond the collection limit.", "仍有记录超出本次采集上限。")) }
                RecordTable(headers: [language.text("Date", "日期"), language.text("Model", "模型"), language.text("Requests", "请求"), "Tokens"],
                            rows: rows(data["usage"]["rows"].items, identity: "start_time", keys: ["start_time_local", "model", "num_model_requests", "total_tokens"]), language: language)
            }
            Panel(title: language.text("Organization costs", "组织费用")) {
                if data["costs"]["error"] != .null { Notice(text: data["costs"]["error"].errorText) }
                RecordTable(headers: [language.text("Date", "日期"), language.text("Item", "项目"), language.text("Amount", "金额"), language.text("Currency", "币种")],
                            rows: rows(data["costs"]["rows"].items, identity: "start_time", keys: ["start_time_local", "line_item", "amount", "currency"]), language: language)
            }
        }
    }
}
