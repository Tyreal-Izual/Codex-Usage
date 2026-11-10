import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model: DashboardModel
    private var startup: Task<Void, Never>?

    override init() {
        model = DashboardModel()
        super.init()
    }
    init(model: DashboardModel) {
        self.model = model
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard startup == nil else { return }
        startup = Task { [model] in await model.start() }
    }
    func applicationWillTerminate(_ notification: Notification) {
        startup?.cancel()
        model.stop()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main
struct UsageMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    private var model: DashboardModel { delegate.model }
    var body: some Scene {
        Window("Usage", id: "dashboard") {
            DashboardView(model: model)
                .modifier(DashboardAppearance())
                .environment(\.locale, model.language.locale)
        }
        .defaultSize(width: 1120, height: 800)
        .commands {
            CommandGroup(after: .newItem) {
                Button(model.language.text("Refresh usage", "刷新用量")) { model.refresh(force: true) }
                    .keyboardShortcut("r").disabled(!model.canRefresh)
            }
        }
        Settings { SettingsView(model: model).modifier(DashboardAppearance()) }
        MenuBarExtra("Usage", systemImage: "chart.bar.fill") {
            UsageMenu(model: model)
        }
    }
}

struct UsageMenu: View {
    let model: DashboardModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        let language = model.language
        Button(language.text("Open Usage", "打开用量")) {
            openWindow(id: "dashboard")
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
        Divider()
        let codexWindows = LimitWindows(model.reports[.online]?["endpoints"]["rate_limit_status"]["data"]["rate_limit"] ?? .null)
        if model.sources.contains("codex"), let summary = LimitFormatting.menuSummary(provider: "Codex",
            primaryUsed: codexWindows.primary["used_percent"].number,
            weeklyUsed: codexWindows.weekly["used_percent"].number, language: language) {
            Text(summary)
        }
        if model.sources.contains("claude"), let summary = LimitFormatting.menuSummary(provider: "Claude",
            primaryUsed: model.reports[.claude]?["rate_limits"]["five_hour"]["used_percentage"].number,
            weeklyUsed: model.reports[.claude]?["rate_limits"]["seven_day"]["used_percentage"].number, language: language) {
            Text(summary)
        }
        if model.connecting {
            Text(language.text("Connecting…", "正在连接…"))
        } else if model.needsReconnect {
            Text(language.text("Collector disconnected", "采集器已断开"))
        }
        if model.offersReconnect {
            Button(language.text("Reconnect", "重新连接")) { Task { await model.reconnect() } }
                .disabled(model.connecting)
        }
        Button(language.text("Refresh", "刷新")) { model.refresh(force: true) }.disabled(!model.canRefresh)
        SettingsLink { Text(language.text("Settings…", "设置…")) }
        Divider()
        Button(language.text("Quit Usage", "退出 Usage")) { NSApplication.shared.terminate(nil) }.keyboardShortcut("q")
    }
}
