# Development and configuration

[Quick start](../README.md) · [中文快速开始](../README.zh-CN.md)

## Architecture

| Path | Responsibility |
| --- | --- |
| `macOS/Sources/UsageMac/` | SwiftUI scenes, layouts/theme, observable state, limit presentation and helper client |
| `native_backend.py` | Private JSON-lines dispatcher: request IDs and one active collection per report |
| `usage_reports.py`, `usage_sources.py`, `usage_common.py` | Report composition, source caches, paths, atomic writes and verified TLS |
| `codex_usage.py`, `claude_usage.py` | Local/online collectors and token aggregation |
| `codex_radar.py`, `isambard_status.py` | Public-source collection and disk caches |
| `claude_usage_statusline.py`, `claude_usage_refresher.py` | Optional Claude snapshot capture and scheduling |
| `scripts/` | App packaging, icon generation and bundle verification |
| `codex_claude_usage_web.py`, `static/`, `templates/` | Retained web interface; excluded from the native app's UI resources |

SwiftUI owns a persistent Python helper and communicates over stdin/stdout, with no
HTTP listener or WebView. Sources return independently; source changes invalidate old
replies. EOF, process exit and invalid responses close the helper session, fail pending
requests and expose Reconnect in the toolbar/menu. During collection it appears only
after a request has waited 12 seconds, so routine refreshes do not flash the button.
Timed-out reports keep it available until a later report result or explicit cancellation.
Reports time out after 120 seconds individually, then share a 15-second `hello` probe
outside the worker pool. A healthy reply preserves the session and polling; a failed
probe disconnects it. Control-request timeouts still close the session.
Request/probe timeouts and the 12-second Reconnect delay use `SuspendingClock`,
so time spent in system sleep does not count toward these deadlines.
The client retains helper occupancy after cancellation/timeout and keeps only the latest
waiting replacement per report. It sends that replacement when the old reply arrives;
waiting still counts toward the awake-time timeout, and reconnect clears both states.
Helper admission rejects duplicates that reach it while the same report is collecting,
even if `days`/`top` changed. Worker capacity covers every allowed report (currently
eight), so slow network reports cannot fill the local/Claude slots.
Late results can populate the cache. No duplicate polls wait in the helper worker queue.
Intentional shutdown is silent. Radar owns a separate worker. UI preferences persist
in UserDefaults; source edits during connection are applied before the initial refresh.
AppDelegate owns the model and starts it at application launch, even with no window.
Changing the polling interval reschedules it immediately.
Request IDs, `days` and `top` use explicit JSON integers on the private wire.

## Configuration

| Variable | Purpose / default |
| --- | --- |
| `CODEX_HOME` | Codex state: `~/.codex` |
| `CLAUDE_CONFIG_DIR`, `CLAUDE_BIN` | Claude state (`~/.claude`) and optional executable override |
| `CLAUDE_USAGE_SNAPSHOT` | Limit snapshot: `~/.claude/usage-dashboard.json` |
| `CLAUDE_USAGE_STALE_SECONDS` | Snapshot stale threshold: 900 seconds, minimum 60 |
| `CLAUDE_USAGE_PROJECT_DIR` | Trusted project for the optional refresher |
| `CODEX_USAGE_CACHE_DIR` | Public caches: `~/Library/Caches/codex-usage` |
| `CODEX_USAGE_EXPORT_DIR` | CLI exports: `~/Downloads/codex-usage`; App exports use the save dialog |
| `SSL_CERT_FILE` | Custom CA bundle; otherwise macOS `/etc/ssl/cert.pem` is used |
| `OPENAI_ADMIN_KEY` | Optional organization usage/cost API; not needed for subscriptions |

Finder does not inherit shell variables. To use a custom environment, launch
`dist/Usage.app/Contents/MacOS/UsageMac` from that configured shell. Without saved
preferences, local sources are auto-detected and Isambard/Radar are enabled.

| Source | Cache / refresh |
| --- | --- |
| Codex local | 5 seconds; unchanged transcripts reuse parsed metadata |
| Codex online, Reset Credits, Admin API | 60 seconds |
| Claude | 15 seconds; limits read the captured snapshot |
| Isambard | 30 seconds over a five-minute disk cache; manual bypass at most once per 30 seconds |
| Radar | Independent four-hour worker; [retry and validation rules](radar.md) |

The refresh preference controls polling, not upstream cache expiry. History rows
limit local daily tables; local totals remain historical. Admin API uses the same
value as its lookback in days. Limit countdowns and snapshot age update without a
fetch. Missing values, false and zero stay distinct.
History-size edits coalesce for 300 ms and refresh only local, Claude and enabled
Admin reports; they do not reconfigure sources or refresh online/public reports.
Reset credits prioritize active entries by expiry and highlight those due within
seven days. Counts remain server-reported; expiry cues follow the Mac's clock.
Changed limit percentages, model counts/tokens/shares, server credit counts/balance and
Radar scores highlight for four seconds. Initial data and clock ticks do not flash;
Reduce Motion disables the pulse.

## Build and checks

Quit Usage before rebuilding or starting demo mode. Open `macOS/Package.swift` in
Xcode; `./scripts/build_macos.sh --development` builds against the checkout's Python.
Run checks from the checkout root:

```sh
python3 -B -m unittest discover -v
source scripts/xcode_env.sh
xcrun swift test --package-path macOS --scratch-path .build/swift
./scripts/build_macos.sh
python3 -B scripts/check_bundle.py dist/Usage.app
codesign --verify --deep --strict dist/Usage.app
open dist/Usage.app --args --demo
```

Development builds require the checkout and selected Python; release builds bundle
Python. Switching build modes replaces the helper directory completely. Native builds
and tests require full Xcode; standalone Command Line Tools lack the SwiftUI macro
plugins. `scripts/xcode_env.sh` selects Xcode and exports `DEVELOPER_DIR`; set that
variable explicitly for another Xcode installation.

CI runs Python 3.10/3.14 on Linux, macOS and Windows for the shared
collectors and legacy web/CLI. Swift tests and app packaging run only on macOS. Python tests require
loopback access and Node; CI rejects skipped tests. TLS tests use a public, untrusted
fixture certificate without requiring an external OpenSSL executable. Swift tests cover
process failures, reconnect races, targeted history refresh, exports and presentation.
The bundle check uses temporary data and no external service by default. Add
`--https` to check public HTTPS without credentials. Certificate verification stays enabled.

For a built app, `Contents/Resources/helper/usage-helper --check` inspects setup,
`--check-tls` checks CA loading offline, and `--check-https` probes public endpoints.
Demo mode reads no account files, starts no helper and saves no preferences.
UI checks should cover both languages, resizing, keyboard access, source switches,
export and quit cleanup. Public signing/notarization and automatic updates remain release work.

## Data boundaries

Codex daily totals are grouped by session start date, not per-event consumption.
Session totals use JSONL logs; model totals use SQLite threads and can differ.
Native model lists show the top 20 entries; their totals and shares use those entries.

Claude counts each message/request identity once across files, retaining the snapshot
with the greatest total usage (latest timestamp breaks ties). Counters from duplicate
snapshots are not added together. Project grouping uses complete paths. File caches
track identity/change time as well as size/mtime; failed reads are retried, not cached.
