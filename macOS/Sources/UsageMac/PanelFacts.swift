import SwiftUI

struct PanelFactBadge: View, Equatable {
    let fact: PanelFact
    private var valueColor: Color {
        switch fact.tone {
        case .normal: return DashboardTheme.ink
        case .good: return DashboardTheme.good
        case .warning: return DashboardTheme.warning
        case .bad: return DashboardTheme.bad
        }
    }
    var body: some View {
        HStack(spacing: 5) {
            Text(fact.label).fontWeight(.semibold).foregroundStyle(DashboardTheme.muted)
            Text(fact.value).fontWeight(.semibold).foregroundStyle(valueColor).monospacedDigit()
                .highlightChanges(value: fact.tracksChanges ? fact.value : nil)
        }
        .font(.subheadline)
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(DashboardTheme.field, in: Capsule())
        .overlay { Capsule().strokeBorder(DashboardTheme.line) }
        .accessibilityElement(children: .combine)
        .help(fact.help.isEmpty ? fact.label + ": " + fact.value : fact.help)
    }
}

/// Wrap panel heading elements without truncating values on smaller cards.
struct PanelFactsLayout: Layout {
    var spacing: CGFloat = 8
    struct Cache {
        var width: CGFloat?
        var measurement: (size: CGSize, frames: [CGRect])?
    }
    func makeCache(subviews: Subviews) -> Cache { Cache() }
    func updateCache(_ cache: inout Cache, subviews: Subviews) { cache = Cache() }

    private func measure(width: CGFloat, subviews: Subviews, cache: inout Cache) -> (size: CGSize, frames: [CGRect]) {
        if cache.width == width, let measurement = cache.measurement { return measurement }
        var frames: [CGRect] = []
        frames.reserveCapacity(subviews.count)
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0
        var rowStart = 0
        func centerRow() {
            for index in rowStart..<frames.count {
                let offset = (rowHeight - frames[index].height) / 2
                frames[index].origin.y += offset
            }
        }
        for view in subviews {
            let size = view.sizeThatFits(ProposedViewSize(width: width, height: nil))
            if x > 0 && x + size.width > width {
                centerRow()
                rowStart = frames.count
                x = 0; y += rowHeight + spacing; rowHeight = 0
            }
            frames.append(CGRect(x: x, y: y, width: size.width, height: size.height))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        centerRow()
        let measurement = (CGSize(width: width, height: y + rowHeight), frames)
        cache.width = width
        cache.measurement = measurement
        return measurement
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let width = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil }
            ?? (subviews.reduce(CGFloat(0)) { $0 + $1.sizeThatFits(.unspecified).width + spacing } - spacing)
        return measure(width: width, subviews: subviews, cache: &cache).size
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        let frames = measure(width: bounds.width, subviews: subviews, cache: &cache).frames
        for (index, view) in subviews.enumerated() {
            let frame = frames[index]
            view.place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                       anchor: .topLeading, proposal: ProposedViewSize(frame.size))
        }
    }
}
