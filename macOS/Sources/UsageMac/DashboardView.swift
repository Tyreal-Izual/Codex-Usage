import SwiftUI
import UniformTypeIdentifiers

struct DashboardView: View {
    @Bindable var model: DashboardModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selection: Destination? = .overview
    @State private var initialLimitsPositionPending = true
    @State private var exporting = false
    @State private var exportDocument = SnapshotDocument()
    @State private var exportError: String?
    private var language: Language { model.language }
    private let codexLimitsID = "codex-limits"
    private var hasCodexLimits: Bool {
        [.overview, .codex].contains(selection ?? .overview)
            && model.sources.contains("codex") && model.reports[.online] != nil
    }

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section(language.text("Usage", "用量")) {
                    ForEach([Destination.overview, .codex, .claude]) { destination in
                        Label(destination.title(language), systemImage: destination.symbol).tag(destination)
                    }
                }
                Section(language.text("Sources", "数据来源")) {
                    ForEach([Destination.radar, .isambard]) { destination in
                        Label(destination.title(language), systemImage: destination.symbol).tag(destination)
                    }
                    if model.adminEnabled {
                        Label(Destination.api.title(language), systemImage: Destination.api.symbol).tag(Destination.api)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(DashboardTheme.background)
            .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 260)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 8) {
                    Label(model.demo ? language.text("Demo data", "演示数据") : language.text("On this Mac", "此 Mac 上的数据"), systemImage: "desktopcomputer")
                        .font(.caption).foregroundStyle(DashboardTheme.muted)
                    SettingsLink { Label(language.text("Settings", "设置"), systemImage: "gearshape") }
                }.frame(maxWidth: .infinity, alignment: .leading).padding().background(DashboardTheme.background)
            }
        } detail: {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        heading
                        if let error = model.connectionError {
                            Panel(title: language.text("Connection needs attention", "采集连接需要处理")) {
                                Notice(text: error)
                                Button(language.text("Reconnect", "重新连接")) { Task { await model.reconnect() } }
                                    .disabled(model.connecting)
                            }
                        }
                        if model.connecting {
                            ProgressView(language.text("Starting collectors…", "正在启动采集器…")).padding()
                        }
                        content
                    }
                    .padding(.horizontal, 24).padding(.vertical, 20)
                    .padding(.bottom, hasCodexLimits ? 64 : 0)
                    .frame(maxWidth: 1300, alignment: .leading).frame(maxWidth: .infinity)
                }
                .id(selection ?? .overview)
                .overlay(alignment: .bottomTrailing) {
                    if hasCodexLimits {
                        Button {
                            initialLimitsPositionPending = false
                            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                                proxy.scrollTo(codexLimitsID, anchor: .top)
                            }
                        } label: {
                            Label(language.text("Back to limits", "回到额度"), systemImage: "arrow.up.to.line")
                        }
                        .buttonStyle(LimitsNavigationButtonStyle())
                        .help(language.text("Align Codex limits with the top of the page", "将 Codex 额度对齐到页面顶部"))
                        .padding(20)
                    }
                }
                .task(id: hasCodexLimits && !model.connecting) {
                    guard initialLimitsPositionPending, hasCodexLimits, !model.connecting else { return }
                    // Let the newly loaded panel enter the scroll layout before positioning it.
                    await Task.yield()
                    guard !Task.isCancelled, initialLimitsPositionPending else { return }
                    initialLimitsPositionPending = false
                    proxy.scrollTo(codexLimitsID, anchor: .top)
                }
                .onChange(of: selection) { initialLimitsPositionPending = false }
                .onChange(of: model.sources) {
                    if !model.sources.contains("codex") { initialLimitsPositionPending = false }
                }
            }
            .background(DashboardTheme.background)
            .navigationTitle((selection ?? .overview).title(language))
            .toolbar {
                ToolbarItemGroup {
                    if model.offersReconnect {
                        Button { Task { await model.reconnect() } } label: {
                            Label(language.text("Reconnect", "重新连接"), systemImage: "arrow.triangle.2.circlepath")
                        }.disabled(model.connecting)
                    }
                    if !model.pending.isEmpty { ProgressView().controlSize(.small).help(language.text("Refreshing sources", "正在刷新来源")) }
                    Button { model.refresh(force: true) } label: { Label(language.text("Refresh", "刷新"), systemImage: "arrow.clockwise") }
                        .keyboardShortcut("r").disabled(!model.canRefresh)
                    Button {
                        do { exportDocument = SnapshotDocument(data: try model.exportData()); exporting = true }
                        catch { exportError = error.localizedDescription }
                    } label: { Label(language.text("Export JSON", "导出 JSON"), systemImage: "square.and.arrow.up") }
                    .disabled(model.reports.isEmpty)
                }
            }
        }
        .frame(minWidth: 760, minHeight: 560)
        .background(DashboardTheme.background)
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: .json,
                      defaultFilename: "usage-\(Date().formatted(.iso8601.year().month().day().dateSeparator(.dash)))") { result in
            if case .failure(let error) = result { exportError = error.localizedDescription }
        }
        .alert(language.text("Export failed", "导出失败"), isPresented: Binding(get: { exportError != nil }, set: { if !$0 { exportError = nil } })) {
            Button(language.text("OK", "好")) { exportError = nil }
        } message: { Text(exportError ?? "") }
    }

    private var heading: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text((selection ?? .overview).title(language)).font(.largeTitle.weight(.semibold))
            HStack(spacing: 8) {
                if model.demo { Text(language.text("Preview with sample data", "使用样例数据预览")) }
                else if let updated = model.updated.values.max() {
                    Text(language.text("Updated", "更新于"))
                    Text(updated, style: .time)
                } else { Text(language.text("Your limits, tokens and sessions in one place.", "集中查看额度、token 与会话。")) }
                if !model.pending.isEmpty { Text("· \(model.pending.count) " + language.text("loading", "项加载中")) }
            }.font(.subheadline).foregroundStyle(DashboardTheme.muted)
        }
    }

    @ViewBuilder private var content: some View {
        let destination = selection ?? .overview
        if destination != .overview && !model.sources.contains(destination == .api ? "codex" : destination.rawValue) {
            ContentUnavailableView {
                Label(language.text("Source is disabled", "来源已关闭"), systemImage: "pause.circle")
            } description: { Text(language.text("Enable it in Settings to collect and display data.", "在设置中启用后即可采集和显示数据。")) }
            actions: { SettingsLink { Text(language.text("Open Settings", "打开设置")) } }
        } else {
            switch destination {
            case .overview:
                overview
            case .codex:
                SourceSection(report: .online, model: model) { CodexLimits(data: $0, language: language) }
                    .id(codexLimitsID)
                SourceSection(report: .local, model: model) { LocalDetails(data: $0, claude: false, language: language) }
                SourceSection(report: .resets, model: model) { ResetCredits(data: $0, language: language) }
                SourceSection(report: .online, model: model) { ProfileStatistics(data: $0, language: language) }
            case .claude:
                SourceSection(report: .claude, model: model) {
                    ClaudeLimits(data: $0, language: language)
                    LocalDetails(data: $0, claude: true, language: language)
                }
            case .radar:
                SourceSection(report: .radar, model: model) { RadarView(snapshot: $0, language: language) }
            case .isambard:
                SourceSection(report: .isambard, model: model) { IsambardView(data: $0, language: language) }
            case .api:
                SourceSection(report: .api, model: model) { AdminView(data: $0, language: language) }
            }
        }
    }

    private var overview: some View {
        VStack(spacing: 14) {
            if model.sources.isEmpty {
                ContentUnavailableView(language.text("Choose a source", "请选择数据来源"), systemImage: "slider.horizontal.3",
                                       description: Text(language.text("Enable Codex, Claude or public sources in Settings.", "在设置中启用 Codex、Claude 或公共数据来源。")))
            }
            SourceSection(report: .online, model: model) {
                CodexLimits(data: $0, language: language)
            }
            .id(codexLimitsID)
            SourceSection(report: .claude, model: model) {
                ClaudeLimits(data: $0, language: language)
            }
            SourceSection(report: .isambard, model: model) { IsambardView(data: $0, language: language, maintenance: false) }
            DailyTokensView(reports: model.reports, sources: model.sources, errors: model.errors, language: language)
            EqualWidthCardsLayout(minimumColumnWidth: 400) {
                if model.sources.contains("claude") {
                    SourceSection(report: .claude, model: model, fillHeight: true) { data in
                        ModelUsage(title: language.text("Claude Code Models", "Claude Code 模型"),
                                   items: data["local_usage"]["by_model"].items,
                                   tokenKey: "total_tokens", countKey: "requests", language: language,
                                   subtitle: language.text("Token totals grouped by model", "按模型汇总的 token"),
                                   updatedAt: data["local_usage"]["latest_record_at_unix_ms"].number,
                                   fillHeight: true,
                                   detailTitle: language.text("View full Claude Code details", "查看 Claude Code 完整详情"),
                                   showDetails: { selection = .claude })
                    }
                }
                if model.sources.contains("codex") {
                    SourceSection(report: .local, model: model, fillHeight: true) { data in
                        ModelUsage(title: language.text("Codex Models", "Codex 模型"),
                                   items: data["sqlite_threads"]["selected"]["by_model"].items,
                                   tokenKey: "tokens_used", countKey: "threads", language: language,
                                   subtitle: language.text("Local thread database", "本地会话数据库"),
                                   updatedAt: data["sqlite_threads"]["selected"]["updated_at_unix_ms"].number,
                                   fillHeight: true,
                                   unavailable: !data["sqlite_threads"]["selected"]["error"].errorText.isEmpty,
                                   detailTitle: language.text("View full Codex details", "查看 Codex 完整详情"),
                                   showDetails: { selection = .codex })
                    }
                }
            }
            SourceSection(report: .resets, model: model) { ResetCredits(data: $0, language: language) }
            SourceSection(report: .radar, model: model) { RadarView(snapshot: $0, language: language) }
        }
    }
}

private struct LimitsNavigationButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 12).padding(.vertical, 8)
            .foregroundStyle(DashboardTheme.background)
            .background(DashboardTheme.accent.opacity(configuration.isPressed ? 0.8 : 1), in: Capsule())
            .contentShape(Capsule())
            .shadow(color: .black.opacity(0.25), radius: 8, y: 3)
    }
}

struct SnapshotDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }
    var data = Data()
    init(data: Data = Data()) { self.data = data }
    init(configuration: ReadConfiguration) throws { data = configuration.file.regularFileContents ?? Data() }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}
