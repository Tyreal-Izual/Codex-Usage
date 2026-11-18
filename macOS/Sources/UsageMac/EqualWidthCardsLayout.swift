import SwiftUI

/// Equal columns with a shared row height, wrapping as the available width changes.
/// Keeping the same Layout preserves view identity during window resizing.
struct EqualWidthCardsLayout: Layout {
    var minimumColumnWidth: CGFloat = 310
    var maximumColumns = 2
    var spacing: CGFloat = 18
    struct Cache {
        var width: CGFloat?
        var measurement: (columns: Int, columnWidth: CGFloat, heights: [CGFloat])?
    }
    func makeCache(subviews: Subviews) -> Cache { Cache() }
    func updateCache(_ cache: inout Cache, subviews: Subviews) { cache = Cache() }

    private func measure(width: CGFloat, subviews: Subviews, cache: inout Cache) -> (columns: Int, columnWidth: CGFloat, heights: [CGFloat]) {
        if cache.width == width, let measurement = cache.measurement { return measurement }
        let capacity = Int((width + spacing) / (minimumColumnWidth + spacing))
        let columns = max(1, min(maximumColumns, min(subviews.count, capacity)))
        let columnWidth = max(0, (width - CGFloat(columns - 1) * spacing) / CGFloat(columns))
        var heights: [CGFloat] = []
        heights.reserveCapacity((subviews.count + columns - 1) / columns)
        for (index, view) in subviews.enumerated() {
            let height = view.sizeThatFits(ProposedViewSize(width: columnWidth, height: nil)).height
            if index % columns == 0 { heights.append(height) }
            else { heights[heights.count - 1] = max(heights[heights.count - 1], height) }
        }
        cache.width = width
        cache.measurement = (columns, columnWidth, heights)
        return (columns, columnWidth, heights)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let idealColumns = min(maximumColumns, subviews.count)
        let idealWidth = minimumColumnWidth * CGFloat(idealColumns) + CGFloat(idealColumns - 1) * spacing
        let width = proposal.width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? idealWidth
        let measured = measure(width: width, subviews: subviews, cache: &cache)
        return CGSize(width: width, height: measured.heights.reduce(0, +) + CGFloat(max(0, measured.heights.count - 1)) * spacing)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        let measured = measure(width: bounds.width, subviews: subviews, cache: &cache)
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
