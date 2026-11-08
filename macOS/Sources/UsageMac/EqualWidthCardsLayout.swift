import SwiftUI

/// Equal columns with a shared row height, wrapping as the available width changes.
/// Keeping the same Layout preserves view identity during window resizing.
struct EqualWidthCardsLayout: Layout {
    var minimumColumnWidth: CGFloat = 310
    var maximumColumns = 2
    var spacing: CGFloat = 18

    private func measure(width: CGFloat, subviews: Subviews) -> (columns: Int, columnWidth: CGFloat, heights: [CGFloat]) {
        let capacity = Int((width + spacing) / (minimumColumnWidth + spacing))
        let columns = max(1, min(maximumColumns, min(subviews.count, capacity)))
        let columnWidth = max(0, (width - CGFloat(columns - 1) * spacing) / CGFloat(columns))
        var heights: [CGFloat] = []
        for (index, view) in subviews.enumerated() {
            let height = view.sizeThatFits(ProposedViewSize(width: columnWidth, height: nil)).height
            if index % columns == 0 { heights.append(height) }
            else { heights[heights.count - 1] = max(heights[heights.count - 1], height) }
        }
        return (columns, columnWidth, heights)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let idealColumns = min(maximumColumns, subviews.count)
        let idealWidth = minimumColumnWidth * CGFloat(idealColumns) + CGFloat(idealColumns - 1) * spacing
        let width = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? idealWidth
        let measured = measure(width: width, subviews: subviews)
        return CGSize(width: width, height: measured.heights.reduce(0, +) + CGFloat(max(0, measured.heights.count - 1)) * spacing)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let measured = measure(width: bounds.width, subviews: subviews)
        var y = bounds.minY
        for (index, view) in subviews.enumerated() {
            let column = index % measured.columns
            let height = measured.heights[index / measured.columns]
            view.place(at: CGPoint(x: bounds.minX + CGFloat(column) * (measured.columnWidth + spacing), y: y),
                       anchor: .topLeading, proposal: ProposedViewSize(width: measured.columnWidth, height: height))
            if column == measured.columns - 1 { y += height + spacing }
        }
    }
}
