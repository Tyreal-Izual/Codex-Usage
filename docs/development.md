# Development and verification

[Quick start](../README.md) · [中文快速开始](../README.zh-CN.md)

## Repository layout

| Path | Responsibility |
| --- | --- |
| `codex_claude_usage_web.py` | Authenticated HTTP server, report composition and startup options |
| `codex_usage.py` | Upstream-derived Codex collector, terminal reports and exports |
| `claude_usage.py` | Claude usage metadata and local limit snapshots |
| `claude_usage_statusline.py` | Optional limit-capture bridge |
| `claude_usage_refresher.py` | Optional macOS/POSIX refresh automation |
| `codex_radar.py`, `isambard_status.py` | Public-source collection and caching |
| `usage_common.py` | Paths, atomic JSON writes, executable discovery and TLS configuration |
| `usage_sources.py` | Source selection, independent caches and read-only diagnostics |
| `dashboard_assets.py` | Load repository-owned templates and assets |
| `templates/` | Page markup |
| `static/` | Editable CSS/JavaScript, including progressive loading and Radar |
| `test_*.py` | Standard-library regression tests |

The source files are separated for editing, then assembled into authenticated
HTML responses at startup. There is no public filesystem route, build step,
third-party runtime dependency or need to install a package. Restart after edits.
Keep the checkout together; copying only an entry-point script is insufficient.

## Tests

```sh
python3 -B -m unittest discover -v
python3 -B -m unittest test_codex_usage test_usage_sources test_dashboard_refresh -v
```

Node.js on PATH enables the JavaScript regression tests. Python marks those tests
skipped when Node is missing. CI installs Node and fails if any test is skipped.
The suite uses temporary files, synthetic usage/benchmark records, mocked upstream
responses and ephemeral loopback HTTP servers; it requires no account or network service.

CI exercises Python 3.10 and 3.14 on Linux, macOS and Windows. Platform-specific
background installation is optional; the dashboard and collectors remain portable.
Cross-platform CI results only become available after pushing the workflow.

After UI changes also check a narrow browser window, language switching, keyboard
navigation, loading/failure states and reduced-motion behavior. Automated tests
cover script syntax, progressive loading, request bounds and selected rendering;
they do not establish visual correctness on every browser.

## Behavior to preserve

- CLI entry points, report keys, API authentication and source privacy boundaries.
- Cumulative Codex token totals use the final valid record, not the sum of snapshots.
- Claude duplicate identities are counted once, including across subagent files.
- File growth, truncation, replacement and deletion invalidate/reconcile caches.
- A source cache coalesces matching work without blocking unrelated sources.
- Disabled sources never start new collection work (already-running fetches may finish); `--check` never launches clients.
- Failed disk writes retain useful live results and clean up temporary files.
- Core collectors raise structured errors; only the CLI prints its error messages.
