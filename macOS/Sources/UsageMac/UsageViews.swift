import SwiftUI

struct TokenSummary: View {
    let title: String
    let totals: JSONValue
    let language: Language
    var body: some View {
        Panel(title: title) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), alignment: .leading)], spacing: 14) {
                Metric(title: language.text("Total tokens", "总 token"), value: totals["total_tokens"].display(locale: language.locale))
                Metric(title: language.text("Input", "输入"), value: totals["input_tokens"].display(locale: language.locale))
                Metric(title: language.text("Output", "输出"), value: totals["output_tokens"].display(locale: language.locale))
                Metric(title: language.text("Cache read", "缓存读取"), value: (totals["cached_input_tokens"] != .null ? totals["cached_input_tokens"] : totals["cache_read_input_tokens"]).display(locale: language.locale))
                if totals["cache_creation_input_tokens"] != .null {
                    Metric(title: language.text("Cache creation", "缓存写入"), value: totals["cache_creation_input_tokens"].display(locale: language.locale))
                }
                if totals["reasoning_output_tokens"] != .null {
                    Metric(title: language.text("Reasoning output", "推理输出"), value: totals["reasoning_output_tokens"].display(locale: language.locale))
                }
            }
        }
    }
}

struct LocalDetails: View {
    let data: JSONValue
    let claude: Bool
    let language: Language
    private var local: JSONValue { claude ? data["local_usage"] : data["sessions"] }
    var body: some View {
        VStack(spacing: 14) {
            TokenSummary(title: language.text("Local token history", "本地 token 历史"),
                         totals: claude ? local["token_totals"] : local["final_token_totals_sum"], language: language)
            if let errors = local["parse_or_read_errors"].number, errors > 0 {
                Notice(text: language.text("Some transcript records could not be read: ", "部分记录未能读取：") + local["parse_or_read_errors"].display(locale: language.locale))
            }
            ModelUsage(title: language.text("Usage by model", "按模型统计"),
                       items: claude ? local["by_model"].items : data["sqlite_threads"]["selected"]["by_model"].items,
                       tokenKey: claude ? "total_tokens" : "tokens_used", countKey: claude ? "requests" : "threads", language: language,
                       updatedAt: claude ? local["latest_record_at_unix_ms"].number : data["sqlite_threads"]["selected"]["updated_at_unix_ms"].number,
                       unavailable: !claude && !data["sqlite_threads"]["selected"]["error"].errorText.isEmpty)
            Panel(title: language.text("Daily history", "每日记录"),
                  subtitle: language.text("Usage events grouped by local calendar day", "按用量发生的本地自然日汇总")) {
                RecordTable(headers: [language.text("Date", "日期"), language.text("Sessions", "会话"), "Tokens", language.text("Input", "输入"), language.text("Output", "输出")],
                            rows: rows(local["daily_usage"].items.reversed(), identity: "date", keys: ["date", "sessions", "total_tokens", "input_tokens", "output_tokens"], language: language), language: language)
            }
            if claude {
                Panel(title: language.text("Projects", "项目")) {
                    RecordTable(headers: [language.text("Project", "项目"), language.text("Requests", "请求"), "Tokens"],
                                rows: rows(local["by_project"].items, identity: "project", keys: ["project", "requests", "total_tokens"], language: language), language: language)
                }
            }
            Panel(title: language.text("Top sessions", "用量最多的会话")) {
                RecordTable(headers: [language.text("Project", "项目"), language.text("Model", "模型"), "Tokens", language.text("Date", "日期"), language.text("Session file", "会话文件")],
                            rows: rows(local[claude ? "top_sessions" : "top_sessions_by_total_tokens"].items, identity: "session_file", keys: ["project", claude ? "models" : "model", "usage.total_tokens", "date", "session_file"], language: language), language: language)
            }
        }
    }
}

struct ProfileStatistics: View {
    let data: JSONValue
    let language: Language
    var body: some View {
        let endpoint = data["endpoints"]["profile"]
        let stats = endpoint["data"]["stats"]
        Panel(title: language.text("Account statistics", "账户统计")) {
            if endpoint["ok"].flag == false { Notice(text: endpoint["error"].errorText) }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))], alignment: .leading, spacing: 16) {
                Metric(title: language.text("Lifetime tokens", "累计 token"), value: stats["lifetime_tokens"].display(locale: language.locale))
                Metric(title: language.text("Peak daily tokens", "单日峰值"), value: stats["peak_daily_tokens"].display(locale: language.locale))
                Metric(title: language.text("Most used effort", "常用推理档位"), value: stats["most_used_reasoning_effort"].display(locale: language.locale))
            }
        }
    }
}
