import SwiftUI

/// Keep each heading on one line when it fits, without hiding metadata when narrow.
struct PanelHeader: View {
    let title: String
    let subtitle: String
    let facts: [PanelFact]

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                titleLabel.fixedSize()
                ForEach(facts) { PanelFactBadge(fact: $0).fixedSize() }
                if !subtitle.isEmpty {
                    Spacer(minLength: 8)
                    subtitleLabel.fixedSize()
                }
            }
            PanelFactsLayout {
                titleLabel
                ForEach(facts) { PanelFactBadge(fact: $0) }
                if !subtitle.isEmpty { subtitleLabel }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var titleLabel: some View {
        Text(title).font(.headline.weight(.bold)).accessibilityAddTraits(.isHeader)
    }
    private var subtitleLabel: some View {
        Text(subtitle).font(.caption).foregroundStyle(DashboardTheme.muted)
    }
}
