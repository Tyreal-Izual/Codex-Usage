import SwiftUI

struct ServiceStatusCard: View {
    let status: JSONValue
    let language: Language
    @State private var expanded = false
    private var state: ServiceState { ServiceState(status) }
    private var titleParts: [String] {
        status["title"].display(locale: language.locale).split(separator: ":", maxSplits: 1)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    }
    private var condition: String {
        guard titleParts.count == 2, !titleParts[1].isEmpty else { return state.title(language) }
        let detail = titleParts[1]
        return state.condition(detail, language: language)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { expanded.toggle() } label: {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) {
                        serviceName.fixedSize()
                        Spacer(minLength: 0)
                        statusBadge.fixedSize()
                        disclosureIndicator
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .top, spacing: 8) {
                            serviceName.fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            disclosureIndicator
                        }
                        statusBadge.fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 14).padding(.vertical, 10).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(status["title"].display(locale: language.locale) + ", " + state.title(language))
            .accessibilityValue(expanded ? language.text("Expanded", "已展开") : language.text("Collapsed", "已收起"))
            .accessibilityHint(language.text("Show or hide service details", "展开或收起服务说明"))
            .help(status["title"].display(locale: language.locale))
            if expanded {
                Text(status["body"].display(locale: language.locale))
                    .font(.body).foregroundStyle(DashboardTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14).padding(.bottom, 10)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(DashboardTheme.field)
        .overlay(alignment: .leading) { Rectangle().fill(state.color).frame(width: 4) }
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(DashboardTheme.line) }
    }

    private var serviceName: some View {
        Text(titleParts.first ?? status["title"].display(locale: language.locale)).font(.title3.weight(.bold))
    }
    private var statusBadge: some View {
        Label(condition, systemImage: state.symbol)
            .font(.subheadline.weight(.semibold)).foregroundStyle(state.color)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(state.color.opacity(0.12), in: Capsule())
            .overlay { Capsule().strokeBorder(state.color.opacity(0.3)) }
    }
    private var disclosureIndicator: some View {
        Image(systemName: expanded ? "chevron.up" : "chevron.down")
            .font(.caption.weight(.semibold)).foregroundStyle(DashboardTheme.muted)
            .accessibilityHidden(true)
    }
}

enum ServiceState: Equatable {
    case operational, degraded, outage, unknown

    init(_ status: JSONValue) {
        let css = status["class"].text.lowercased(), title = status["title"].text.lowercased()
        let detail = title.split(separator: ":", maxSplits: 1).last.map(String.init) ?? title
        if css.contains("success") || Self.isHealthy(detail) { self = .operational }
        else if css.contains("warning") || title.contains("degraded") || title.contains("at risk") { self = .degraded }
        else if css.contains("failure") || title.contains("outage") { self = .outage }
        else { self = .unknown }
    }

    private static func isHealthy(_ detail: String) -> Bool {
        ["no known issue", "no known issues"].contains(detail.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    }

    func condition(_ detail: String, language: Language) -> String {
        Self.isHealthy(detail) ? title(language) : detail
    }

    var color: Color {
        switch self {
        case .operational: return DashboardTheme.good
        case .degraded: return DashboardTheme.warning
        case .outage: return DashboardTheme.bad
        case .unknown: return DashboardTheme.muted
        }
    }
    var symbol: String {
        switch self {
        case .operational: return "checkmark.circle"
        case .degraded: return "exclamationmark.triangle"
        case .outage: return "xmark.circle"
        case .unknown: return "questionmark.circle"
        }
    }
    func title(_ language: Language) -> String {
        switch self {
        case .operational: return language.text("Operational", "运行正常")
        case .degraded: return language.text("Degraded", "服务降级")
        case .outage: return language.text("Outage", "服务中断")
        case .unknown: return language.text("Unknown", "状态未知")
        }
    }
}
