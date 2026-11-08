import SwiftUI

/// Track displayed values so refreshes and off-screen reappearances don't replay a change.
struct ValueChangeFeedback {
    static let lifetime: TimeInterval = 4
    private(set) var value: String?
    private(set) var changedAt: Date?
    private(set) var revision = 0

    mutating func observe(_ next: String?, at date: Date) {
        guard next != value else { return }
        changedAt = value != nil && next != nil ? date : nil
        value = next
        revision &+= 1
    }

    func remaining(at date: Date) -> TimeInterval {
        guard let changedAt else { return 0 }
        return min(Self.lifetime, max(0, Self.lifetime - date.timeIntervalSince(changedAt)))
    }
}

extension View {
    func highlightChanges(value: String?) -> some View {
        modifier(ValueChangeHighlight(value: value == "—" || value == "" ? nil : value))
    }
}

private struct ValueChangeHighlight: ViewModifier {
    let value: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var feedback = ValueChangeFeedback()
    @State private var highlighted = false
    @State private var pulsing = false

    func body(content: Content) -> some View {
        content
            .background {
                RoundedRectangle(cornerRadius: 3)
                    .fill(DashboardTheme.accent.opacity(0.18))
                    .padding(-3).opacity(highlighted ? 1 : 0)
                    .allowsHitTesting(false)
            }
            .scaleEffect(pulsing && !reduceMotion ? 1.035 : 1)
            .onChange(of: value, initial: true) { feedback.observe(value, at: .now) }
            .task(id: feedback.revision) {
                // A new change cancels the old fade; unchanged refreshes leave it alone.
                var transaction = Transaction(animation: nil)
                transaction.disablesAnimations = true
                withTransaction(transaction) {
                    highlighted = feedback.remaining(at: .now) > 0
                    pulsing = false
                }
                guard let started = feedback.changedAt, highlighted else { return }
                do {
                    if !reduceMotion && Date.now.timeIntervalSince(started) < 0.6 {
                        withAnimation(.easeOut(duration: 0.15)) { pulsing = true }
                        try await Task.sleep(for: .seconds(0.15))
                        withAnimation(.easeOut(duration: 0.45)) { pulsing = false }
                    }
                    let hold = reduceMotion ? ValueChangeFeedback.lifetime : 2.6
                    try await Task.sleep(for: .seconds(max(0, hold - Date.now.timeIntervalSince(started))))
                    withAnimation(reduceMotion ? nil : .easeOut(duration: feedback.remaining(at: .now))) {
                        highlighted = false
                    }
                } catch { /* The next task owns the highlight after cancellation. */ }
            }
    }
}
