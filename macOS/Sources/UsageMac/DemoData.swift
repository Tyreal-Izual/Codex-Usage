import Foundation

/// Synthetic preview data. --demo never starts Python or reads account files.
enum DemoData {
    static let reports: [Report: JSONValue] = {
        let raw = #"""
        {
          "online-usage": {"endpoints": {
            "rate_limit_status": {"ok": true, "data": {"plan_type": "Pro", "credits": {"balance": "120.0000000000", "has_credits": true}, "rate_limit": {"limit_reached": false,
              "primary_window": {"used_percent": 28, "reset_after_seconds": 7200},
              "secondary_window": {"used_percent": 46, "reset_after_seconds": 259200}}}},
            "profile": {"ok": true, "data": {"stats": {"lifetime_tokens": 12458000, "peak_daily_tokens": 850000, "most_used_reasoning_effort": "high"}}}
          }},
          "local-usage": {
            "sqlite_threads": {"selected": {"by_model": [{"model":"gpt-6.1-sol", "threads":42, "tokens_used":2350000}, {"model":"gpt-6.1-terra", "threads":18, "tokens_used":1230000}]}},
            "sessions": {"final_token_totals_sum":{"total_tokens":3580000,"input_tokens":2920000,"output_tokens":660000,"cached_input_tokens":2100000},
              "daily_usage":[{"date":"2026-11-04","sessions":8,"total_tokens":420000,"input_tokens":360000,"output_tokens":60000},{"date":"2026-11-05","sessions":5,"total_tokens":310000,"input_tokens":260000,"output_tokens":50000}],
              "top_sessions_by_total_tokens":[{"session_file":"sessions/example.jsonl","project":"~/Projects/Example","model":"gpt-6.1-sol","date":"2026-11-05","usage":{"total_tokens":180000}}]}
          },
          "claude-usage": {
            "rate_limits":{"available":true,"capture_ready":true,"stale":false,"captured_at":"2026-11-05T12:00:00Z","plan_type":"Max","five_hour":{"used_percentage":18,"resets_at":1793887200},"seven_day":{"used_percentage":37,"resets_at":1794096000}},
            "local_usage":{"token_totals":{"total_tokens":1920000,"input_tokens":120000,"output_tokens":160000,"cache_read_input_tokens":1500000,"cache_creation_input_tokens":140000},
              "by_model":[{"model":"Claude Sonnet","requests":56,"total_tokens":1200000},{"model":"Claude Opus","requests":24,"total_tokens":720000}],
              "daily_usage":[{"date":"2026-11-05","sessions":4,"total_tokens":230000,"input_tokens":18000,"output_tokens":22000}],
              "by_project":[{"project":"~/Projects/Example","requests":80,"total_tokens":1920000}],"top_sessions":[]}
          },
          "resets":{"available_count":2,"total_earned_count":5,"credits":[{"granted_at":"2026-11-01","reset_type":"primary","status":"available","expires_at_local":"2026-11-30"}]},
          "isambard-status":{"status":{"fetched_at":"2026-11-05T12:00:00Z","statuses":[{"title":"Isambard AI","class":"success","body":"All systems operational."},{"title":"Storage","class":"success","body":"All systems operational."}],"maintenance_headers":["Service","Start","End"],"maintenance_rows":[["Storage","2026-11-10 09:00","2026-11-10 10:00"]]}}
        }
        """#
        let value = try! JSONDecoder().decode(JSONValue.self, from: Data(raw.utf8))
        var reports = Dictionary(uniqueKeysWithValues: value.object.compactMap { key, value in Report(rawValue: key).map { ($0, value) } })
        let now = Date().timeIntervalSince1970
        var online = reports[.online]!.object
        online["retrieved_at_unix_ms"] = .number(now * 1000)
        reports[.online] = .object(online)
        var claude = reports[.claude]!.object
        var limits = claude["rate_limits"]!.object
        limits["captured_at_epoch"] = .number(now - 600)
        limits["captured_at"] = .string(ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: now - 600)))
        limits["stale_after_seconds"] = .number(900)
        limits["capture_method"] = .string("usage_command")
        limits["auth_status"] = .object(["checked": .bool(true), "logged_in": .bool(true)])
        limits["five_hour"] = .object(["used_percentage": .number(18), "resets_at": .number(now + 10_740)])
        limits["seven_day"] = .object(["used_percentage": .number(37), "resets_at": .number(now + 62_940)])
        claude["rate_limits"] = .object(limits)
        reports[.claude] = .object(claude)
        reports[.resets] = .object([
            "ok": .bool(true), "retrieved_at_unix_ms": .number(now * 1000),
            "available_count": .number(2), "total_earned_count": .number(5), "credits_returned": .number(3),
            "credits": .array([
                .object(["reset_type": .string("codex_rate_limits"), "status": .string("available"),
                         "granted_at": .number(now - 7 * 86_400), "expires_at": .number(now + 18 * 3_600)]),
                .object(["reset_type": .string("codex_rate_limits"), "status": .string("available"),
                         "granted_at": .number(now - 2 * 86_400), "expires_at": .number(now + 24 * 86_400)]),
                .object(["reset_type": .string("codex_rate_limits"), "status": .string("redeemed"),
                         "granted_at": .number(now - 30 * 86_400), "expires_at": .number(now - 86_400)])
            ])
        ])
        let points = ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra"].flatMap { model in
            ["low", "medium", "high", "xhigh", "max", "ultra"].enumerated().map { index, effort in
                JSONValue.object(["model": .string(model), "effort": .string(effort), "score": .number(90 + Double(index) * 6.4)])
            }
        }
        reports[.radar] = .object(["available": .bool(true), "fetched_at": .string("2026-11-05T12:00:00Z"),
                                  "next_attempt_at": .string("2026-11-05T16:00:00Z"),
                                  "data": .object(["points": .array(points), "source_started_at": .string("2026-11-05T10:00:00Z"), "source_updated_at": .string("2026-11-05T11:00:00Z")])])
        return reports
    }()
}
