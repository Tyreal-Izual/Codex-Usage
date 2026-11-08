import SwiftUI

struct PanelFactBadge: View {
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

    private func measure(width: CGFloat, subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        var frames: [CGRect] = []
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
        return (CGSize(width: width, height: y + rowHeight), frames)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let ideal = subviews.reduce(CGFloat(0)) { $0 + $1.sizeThatFits(.unspecified).width + spacing } - spacing
        let width = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? ideal
        return measure(width: width, subviews: subviews).size
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let frames = measure(width: bounds.width, subviews: subviews).frames
        for (index, view) in subviews.enumerated() {
            let frame = frames[index]
            view.place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                       anchor: .topLeading, proposal: ProposedViewSize(frame.size))
        }
    }
}
