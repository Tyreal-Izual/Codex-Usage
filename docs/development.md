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

SwiftUI communicates with a persistent Python helper over stdin/stdout; there is no
HTTP listener or WebView. `AppDelegate` owns the model and starts collection even
without an open window. Preferences live in UserDefaults. Request IDs, `days` and
`top` are JSON integers.

- **Settings and replies:** source changes invalidate pending replies. The client keeps
  one active collection and only the latest waiting replacement per report. Cancellation
  or timeout does not free the helper's slot; its reply does, and reconnect clears both.
- **Deadlines:** reports have 120 seconds, control requests/probes 15 seconds. Reconnect
  appears after 12 seconds of waiting or immediately after disconnection. After a report
  timeout it remains until a later result or cancellation. Timers include client queue
  waits but exclude system sleep (`SuspendingClock`).
- **Recovery:** a report timeout fails that request and starts one shared `hello` probe.
  A healthy reply preserves the connection; failed probes, control timeouts, EOF, process exit or
  malformed replies close the session and fail pending requests. Intentional stop is silent.
- **Isolation:** the helper admits one collection per report and has capacity for all
  eight report types. Duplicates are rejected before submission; late results can fill
  the cache. Control/Radar reads bypass the pool; Radar has its own fetch worker.
- **Capture:** the optional Claude refresher drains stdout/stderr while the CLI runs,
  with bounded cleanup after timeout.

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

Changing the refresh preference reschedules polling immediately; upstream cache expiry
is independent. History rows
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
