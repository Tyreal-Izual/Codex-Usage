import SwiftUI

/// The original dashboard palette, kept independent of macOS window activation.
enum DashboardTheme {
    static let background = color(0x0b1110)
    static let ink = color(0xeef7f3)
    static let muted = color(0x9badac)
    static let panel = color(0x121b1a)
    static let panelStrong = color(0x172321)
    static let field = color(0x0f1817)
    static let line = color(0x263534)
    static let accent = color(0x46d3b8)
    static let accentSoft = color(0x173a34)
    static let good = color(0x55d486)
    static let warning = color(0xe5b64a)
    static let bad = color(0xff786d)
    static let track = color(0x22302e)
    static let modelColors = [0x55d486, 0x46d3b8, 0x69a7ff, 0xc58cff, 0xf0b45c,
                              0xff7a90, 0x8bd36f, 0x55c7f0, 0xd4d46a, 0xf08be8].map(color)

    static func radarColor(_ model: String) -> Color {
        switch model {
        case "gpt-6-astra": return color(0xf97316)
        case "gpt-6.1-sol": return color(0xfde047)
        case "gpt-6.1-terra": return color(0x38bdf8)
        case "gpt-6-sol": return color(0xfacc15)
        case "gpt-6-luna": return color(0xa5b4fc)
        case "gpt-5.6-sol": return color(0xeab308)
        case "gpt-5.6-terra": return color(0x60a5fa)
        case "gpt-5.6-luna": return color(0xc7d2e0)
        default: return accent
        }
    }

    private static func color(_ hex: Int) -> Color {
        Color(.sRGB, red: Double((hex >> 16) & 255) / 255,
              green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255, opacity: 1)
    }
}

struct DashboardAppearance: ViewModifier {
    func body(content: Content) -> some View {
        let themed = content
            .preferredColorScheme(.dark)
            .foregroundStyle(DashboardTheme.ink)
            .tint(DashboardTheme.accent)
            .toolbarBackground(DashboardTheme.panelStrong, for: .windowToolbar)
            .toolbarColorScheme(.dark, for: .windowToolbar)
        if #available(macOS 15, *) {
            themed.toolbarBackgroundVisibility(.visible, for: .windowToolbar)
        } else {
            themed.toolbarBackground(.visible, for: .windowToolbar)
        }
    }
}

struct DashboardDivider: View {
    @Environment(\.displayScale) private var displayScale
    var body: some View {
        Rectangle().fill(DashboardTheme.line).frame(height: 1 / displayScale).accessibilityHidden(true)
    }
}

struct DashboardProgressStyle: ProgressViewStyle {
    var color = DashboardTheme.accent
    var height: CGFloat = 8
    var divisions = 1
    func makeBody(configuration: Configuration) -> some View {
        GeometryReader { geometry in
            Capsule().fill(DashboardTheme.track)
                .overlay(alignment: .leading) {
                    Capsule().fill(color)
                        .frame(width: geometry.size.width * min(1, max(0, configuration.fractionCompleted ?? 0)))
                }
                .overlay {
                    if divisions > 1 {
                        ForEach(1..<divisions, id: \.self) { index in
                            Rectangle().fill(DashboardTheme.field)
                                .frame(width: 1, height: height)
                                .position(x: geometry.size.width * CGFloat(index) / CGFloat(divisions), y: height / 2)
                        }
                    }
                }
        }.frame(height: height)
    }
}
