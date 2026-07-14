<p align="right">
  <strong>English</strong> | <a href="README.zh-CN.md">中文</a>
</p>

# Codex & Claude Code Usage Dashboard

A local, dependency-free dashboard for viewing Codex, Claude Code, and
Isambard service information in one browser page.

The dashboard combines subscription rate-limit windows, local token history,
model and project breakdowns, daily heatmaps, session rankings, optional
OpenAI Admin API data, and Isambard service status. It runs with the Python
standard library and binds to `127.0.0.1` by default.

> This repository is maintained as an independent project, not as a
> synchronised mirror of its upstream. Its **Codex collection and reporting
> foundation is derived from
> [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)**. The
> combined web dashboard, Claude Code support, statusLine bridge, Isambard
> integration, bilingual interface, and related documentation are additions
> developed in this project.

This is not an official OpenAI, Anthropic, Codex, Claude Code, or Isambard
tool.

## Screenshots

<!-- markdownlint-disable MD033 -- HTML keeps the screenshot gallery compact on GitHub. -->
<p>
  <a href="img/dashboard/1.png"><img src="img/dashboard/1.png" alt="Codex and Claude Code rate-limit overview" width="220"></a>
  <a href="img/dashboard/2.png"><img src="img/dashboard/2.png" alt="Isambard status and model summaries" width="220"></a>
  <a href="img/dashboard/3.png"><img src="img/dashboard/3.png" alt="Codex usage details" width="220"></a>
  <a href="img/dashboard/4.png"><img src="img/dashboard/4.png" alt="Codex daily usage and reset credits" width="220"></a>
  <a href="img/dashboard/5.png"><img src="img/dashboard/5.png" alt="Claude Code usage details" width="220"></a>
  <a href="img/dashboard/6.png"><img src="img/dashboard/6.png" alt="Isambard service status in Chinese" width="220"></a>
</p>
<!-- markdownlint-enable MD033 -->

## Project Origin and Attribution

The codebase has two clearly separated origins:

| Area | Origin |
| --- | --- |
| `codex_usage.py` and the Codex collection/reporting foundation | Derived from [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage) and retained as the separate Codex core, with small integration-oriented changes such as a machine-readable retrieval timestamp |
| Codex results displayed in the browser | Powered by the upstream-derived `codex_usage.py` collector and integrated into this project's web interface |
| `codex_claude_usage_web.py` and the combined browser UI | Developed in this project |
| `claude_usage.py` and `claude_usage_statusline.py` | Developed in this project; independent of `codex_usage.py` |
| `isambard_status.py`, bilingual UI, dashboard layout, and integration logic | Developed in this project |

The upstream project is distributed under the MIT License. Its copyright and
license notice remain in [LICENCE](LICENCE), alongside Frederick Zou's
copyright notice for this project's additions. The upstream CLI documentation
is preserved in [README_OLD.md](README_OLD.md).

## Features

- Combined local overview for Codex rate limits, Claude Code rate limits,
  Isambard status, and Codex/Claude model summaries.
- Dedicated Codex and Claude Code detail views.
- English and Chinese interface with the language choice retained locally.
- Compact toolbar with report, language, local-day window, refresh interval,
  auto-refresh, and manual refresh controls.
- Compact panel headings for Codex reset summaries, online-data age, Claude
  snapshot state, model-data age, Isambard cache age, and planned-maintenance
  access. Ages are shown relatively (for example, `Updated <1 min`) when a
  source provides a timestamp.
- Primary/5-hour and weekly/7-day limit bars with reset countdowns.
- Local token totals, model shares, daily heatmaps, and top sessions.
- Claude Code input, output, cache-creation, and cache-read token accounting,
  deduplicated by request/message identity.
- Claude Code model, project, session, and daily breakdowns, including subagent
  JSONL files.
- Optional OpenAI organisation usage and cost data through
  `OPENAI_ADMIN_KEY`.
- Isambard service status and planned maintenance, with a five-minute cache
  and last-known-good fallback.
- Local JSON API for integrations and automation.
- Original Codex command-line reports and TXT/JSON/CSV exports.

## Requirements

- Python 3.10 or newer.
- Local Codex state, normally under `~/.codex`.
- Local Claude Code transcripts under `~/.claude/projects` for Claude token
  history.
- A Codex login in `~/.codex/auth.json` for Codex reset credits and read-only
  online usage/profile data.
- `OPENAI_ADMIN_KEY` only for the optional OpenAI Admin API section.

No package installation or third-party Python dependency is required.

## Quick Start

From the repository directory, run:

```sh
python3 codex_claude_usage_web.py
```

Then open:

```text
http://127.0.0.1:8765
```

Stop the server with `Ctrl-C`. Common options are:

```sh
python3 codex_claude_usage_web.py --port 8766
python3 codex_claude_usage_web.py --refresh 30
python3 codex_claude_usage_web.py --quiet
python3 codex_claude_usage_web.py --host 127.0.0.1 --port 8765
```

The default host is deliberately local-only. Changing it to `0.0.0.0` may
expose account and usage information to other devices on the network.

## Claude Code Setup

### Local token history

No installation step is required for token history. `claude_usage.py` reads
usage metadata from:

```text
~/.claude/projects/**/*.jsonl
```

Prompt text, response text, tool inputs, and file contents are ignored. Claude
Desktop Code sessions are included when the app writes them to this same
directory.

### Official 5-hour and 7-day windows

To capture the official subscription windows exposed to Claude Code
statusLine scripts, register the included bridge once:

```sh
python3 claude_usage_statusline.py --install
```

After a compatible Claude Code client completes a response, the bridge writes
a sanitised snapshot to:

```text
~/.claude/usage-dashboard.json
```

It stores only rate-limit percentages, reset timestamps, model metadata, and
capture metadata. It does not store prompts or responses. Installation refuses
to replace a different statusLine unless `--force` is explicitly supplied.

Useful commands:

```sh
python3 claude_usage.py
python3 claude_usage.py --json --days 30 --top 10
python3 claude_usage_statusline.py --status
python3 claude_usage_statusline.py --uninstall
```

> Browser auto-refresh only rereads the latest snapshot; it cannot make
> Anthropic refresh that snapshot. Claude Desktop may update local JSONL token
> history without invoking a custom statusLine. In that case, token charts
> continue to change while the 5-hour/7-day snapshot becomes stale. The
> dashboard displays snapshot age and stale state so an old value is not
> mistaken for live account usage.

## Dashboard Views and Data Sources

| View | Main contents | Network |
| --- | --- | --- |
| Overview (`all`) | Codex rate limits, Claude Code rate limits, Isambard status, and model summaries | Codex read-only endpoints and public Isambard pages; local data otherwise |
| Codex Usage (`codex-usage`) | Reset credits, local tokens/models/days/sessions, online profile data, and optional Admin API data | Yes |
| Claude Code Usage (`claude-usage`) | Local token totals, models, projects, days, sessions, and the saved statusLine snapshot | No |
| Isambard Service Status (`isambard-status`) | Current service cards and planned maintenance | Public pages, cached locally |

The full planned-maintenance view is available at:

```text
http://127.0.0.1:8765/isambard-maintenance
```

Automatic dashboard refreshes reuse Isambard data for up to five minutes.
Manual refresh bypasses that cache. If a live request fails, the most recent
successful result remains visible with a warning.

The main Isambard card keeps source metadata compact: its heading shows cache
age when cached and a maintenance-window count linking to the full schedule.
The overview toolbar requests the top 10 ranked rows; API callers can still use
the `top` query parameter to choose a different limit.

## Local JSON API

The web server exposes:

```text
GET /
GET /isambard-maintenance
GET /healthz
GET /api/usage
```

Example:

```text
http://127.0.0.1:8765/api/usage?report=codex-usage&top=10&days=30
```

| Parameter | Meaning | Default |
| --- | --- | --- |
| `report` | `all`, `codex-usage`, `claude-usage`, or `isambard-status` | `all` |
| `top` | Maximum ranked rows | `10` |
| `days` | Recent local daily window | `30` |
| `warn_days` | Reset-credit expiry warning window | `7` |
| `bucket_width` | Admin API bucket width: `1d`, `1h`, or `1m` | `1d` |
| `limit` | Optional Admin API bucket limit | empty |
| `group_by` | Optional Admin API grouping field; repeat or comma-separate | empty |
| `no_costs` | Skip the Admin API costs request with `1`, `true`, or `yes` | `false` |
| `isambard_force_refresh` | Bypass the Isambard cache with `1`, `true`, or `yes` | `false` |

## Standalone Collectors and Original CLI

The collectors can also be used without the web dashboard:

```sh
python3 claude_usage.py
python3 codex_usage.py
python3 codex_usage.py local-usage --top 20 --days 60
python3 codex_usage.py export --report all --format json
```

Running `codex_usage.py` interactively opens its menu. See
[README_OLD.md](README_OLD.md) for its complete command, export, and
troubleshooting guide.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `CODEX_HOME` | Use a Codex data directory other than `~/.codex` |
| `CLAUDE_CONFIG_DIR` | Use a Claude Code data directory other than `~/.claude` |
| `CLAUDE_USAGE_SNAPSHOT` | Store/read the Claude rate-limit snapshot at another path |
| `CLAUDE_USAGE_STALE_SECONDS` | Override the default 15-minute Claude snapshot stale threshold |
| `OPENAI_ADMIN_KEY` | Enable optional OpenAI organisation usage and cost queries |

## Privacy and Limitations

- The server listens on `127.0.0.1` by default.
- Local Codex and Claude files are read but not modified.
- Claude streaming rows are deduplicated before token totals are calculated.
- The Claude statusLine bridge never reads or reuses Claude OAuth credentials.
- Codex reset-credit and online-profile requests are read-only.
- OpenAI Admin API access is optional and uses documented endpoints.
- Isambard data comes from public status pages; only parsed cache data is kept.
- Individual collectors fail independently so one unavailable source does not
  take down the whole dashboard.

Some Codex subscription endpoints used by the upstream-derived collector are
undocumented and may change. Treat all displayed values as operational
information rather than a contractual billing statement. Do not commit API
keys, `auth.json`, private exports, cached account data, or sensitive
screenshots.

## Documentation

- [README.zh-CN.md](README.zh-CN.md): Chinese version.
- [WEB_DASHBOARD.md](WEB_DASHBOARD.md): detailed dashboard behaviour and data
  sources.
- [README_OLD.md](README_OLD.md): preserved documentation for the
  upstream-derived Codex CLI.

## License

This project is distributed under the MIT License. See [LICENCE](LICENCE).
The upstream-derived Codex implementation retains MacSteini's copyright
notice; the dashboard, Claude Code, Isambard, and integration additions are
copyright (c) 2026 Frederick Zou.
