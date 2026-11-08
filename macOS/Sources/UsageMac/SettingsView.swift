import SwiftUI

struct SettingsView: View {
    @Bindable var model: DashboardModel
    private var language: Language { model.language }
    var body: some View {
        Form {
            Section(language.text("General", "通用")) {
                Picker(language.text("Language", "语言"), selection: $model.language) {
                    ForEach(Language.allCases) { Text($0.label).tag($0) }
                }
                Toggle(language.text("Refresh automatically", "自动刷新"), isOn: $model.automatic)
                Stepper(value: $model.interval, in: 3...300) {
                    LabeledContent(language.text("Refresh interval", "刷新间隔"), value: "\(model.interval) s")
                }
                Stepper(value: $model.days, in: 1...365) {
                    LabeledContent(language.text("Daily history rows", "每日历史行数"), value: "\(model.days)")
                }
            }
            Section(language.text("Sources", "数据来源")) {
                Toggle("Codex", isOn: $model.codexEnabled)
                Toggle("Claude Code", isOn: $model.claudeEnabled)
                Toggle("Isambard", isOn: $model.isambardEnabled)
                Toggle("Codex Radar", isOn: $model.radarEnabled)
                Text(language.text("Radar syncs every 4 hours. Refresh reads the cached snapshot. Source choices are saved on this Mac.", "Radar 每 4 小时同步，刷新读取缓存快照。来源选择会保存在此 Mac 上。"))
                    .font(.caption).foregroundStyle(DashboardTheme.muted)
            }
            Section(language.text("Diagnostics", "诊断")) {
                HStack {
                    Button(language.text("Check setup", "检查配置")) { Task { await model.checkSetup() } }
                    Button(language.text("Reconnect collectors", "重新连接采集器")) { Task { await model.reconnect() } }
                        .disabled(model.connecting)
                }
                if !model.diagnostics.isEmpty {
                    ScrollView { Text(model.diagnostics).font(.caption.monospaced()).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        .frame(height: 140)
                }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .background(DashboardTheme.background)
        .frame(width: 480, height: model.diagnostics.isEmpty ? 510 : 660)
    }
}
