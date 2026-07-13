<p align="right">
  <strong>English</strong> | <a href="README.zh-CN.md">中文</a>
</p>

# Codex & Claude Code Usage

A fork of [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)
with an added local web dashboard for reading Codex and Claude Code usage from
one page.

It includes a dashboard plus focused Codex and Claude Code collectors:

- `codex_usage_web.py`: the added local dark-mode web dashboard with auto-refresh,
  English/Chinese language switching, rate-limit bars, daily heatmap, and model
  usage charts.
- `codex_usage.py`: the original upstream command-line tool and the core
  collector/reporting implementation used by both the CLI and the web dashboard.
- `claude_usage.py`: an independent, local-only Claude Code token collector. It
  does not add Claude-specific logic to `codex_usage.py`.
- `claude_usage_statusline.py`: an optional Claude Code statusLine bridge that
  captures the documented 5-hour and 7-day rate-limit snapshot.

No package install is required. The project uses Python standard-library modules
only.

> This is not an official OpenAI or Codex tool. It does not redeem credits, buy
> credits, change your account, change Codex settings, or upload local
> transcripts.

## Source And Attribution

This repository is based on
[MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage). The core
implementation is the upstream `codex_usage.py` CLI, which collects and renders
the Codex usage reports. For the original CLI-focused project description and
usage guide, see the preserved [old README](README_OLD.md).

The changes in this fork mainly add a local, auto-refreshing browser dashboard
in `codex_usage_web.py`, plus supporting documentation. The original CLI remains
available and is still the foundation for the dashboard data.

The upstream project is distributed under the MIT License. Keep the copyright
notice and license terms from `LICENCE` when copying, modifying, or
redistributing this project.

## Features

- Local browser dashboard at `http://127.0.0.1:8765`.
- Auto-refreshing usage view with a manual refresh button.
- English / 中文 Chinese interface switch.
- Online rate-limit view with fixed primary and weekly positions, showing the
  percentage left for each available window and `-` for a temporarily
  unavailable one.
- Reset countdowns shown as days, hours, and minutes.
- GitHub-contributions-style daily local usage heatmap.
- SQLite model counter chart with stacked token share and per-model table.
- Local token totals and top local sessions.
- Claude Code 5-hour and weekly remaining percentages and reset times.
- Deduplicated Claude Code input, output, cache-creation, and cache-read tokens,
  with daily, model, project, and session breakdowns.
- Overview-focused layout: detailed Codex and Claude Code usage panels open from
  their respective model cards instead of crowding the first page.
- Optional OpenAI Admin API usage and costs through `OPENAI_ADMIN_KEY`.
- Isambard service status in the overview or a dedicated view, with a compact
  planned-maintenance link to its own local detail page, a five-minute cache,
  and last-known-good fallback.
- Original CLI reports and exports remain available; see
  [README_OLD.md](README_OLD.md) for the full CLI guide.

## Requirements

- Python 3.10 or newer.
- Local Codex state in your Codex home directory, usually `~/.codex`.
- Local Claude Code transcripts in `~/.claude/projects` for Claude token usage.
- A Codex login in `auth.json` for reset credits and online usage/profile
  reports.
- `OPENAI_ADMIN_KEY` only if you want the optional OpenAI Admin API usage/cost
  report.

By default, the tool reads Codex data from:

```text
Path.home() / ".codex"
```

Set `CODEX_HOME` if your Codex data lives somewhere else.

## Quick Start: Web Dashboard

Run this from the repository directory:

```sh
python3 codex_usage_web.py
```

Open:

```text
http://127.0.0.1:8765
```

Stop the server with `Ctrl-C` in the terminal.

If port `8765` is already in use, choose another port:

```sh
python3 codex_usage_web.py --port 8766
```

Then open:

```text
http://127.0.0.1:8766
```

Useful dashboard options:

```sh
python3 codex_usage_web.py --refresh 30
python3 codex_usage_web.py --quiet
python3 codex_usage_web.py --host 127.0.0.1 --port 8765
```

The dashboard binds to `127.0.0.1` by default, so it is intended for local use
on your own machine.

## Claude Code Rate-Limit Setup

Claude token history works immediately when local Claude Code JSONL files are
present. To display the official 5-hour and 7-day subscription windows, install
the included statusLine bridge once:

```sh
python3 claude_usage_statusline.py --install
```

Then let Claude Code complete one response. The bridge writes only a sanitised
rate-limit snapshot to `~/.claude/usage-dashboard.json`; it does not copy prompt
or response content. If another statusLine is already configured, installation
stops instead of replacing it. Use `--force` only when replacement is intended.

Useful standalone commands:

```sh
python3 claude_usage.py
python3 claude_usage.py --json --days 30 --top 10
python3 claude_usage_statusline.py --status
python3 claude_usage_statusline.py --uninstall
```

Set `CLAUDE_CONFIG_DIR` when Claude Code uses a non-default data directory. Set
`CLAUDE_USAGE_SNAPSHOT` only when the snapshot should live at a custom path.

## Isambard Status And Planned Maintenance

In the overview, `Online rate limits` is the first panel and `Isambard service
status` is the second. You can also choose **Isambard service status** from the
Report selector to focus on that data alone.

The Isambard panel shows the current service cards plus source metadata. Its
**Planned maintenance** item is a link to the full local schedule page:

```text
http://127.0.0.1:8765/isambard-maintenance
```

The normal dashboard refresh uses a local cache for up to five minutes, so it
does not repeatedly poll the public Isambard site. While viewing the overview
or Isambard report, use the dashboard's manual **Refresh** button or the
maintenance page's **Refresh source** button to fetch the two public source
pages immediately. If a fresh request fails, the dashboard
keeps displaying the last successful result and shows a warning.

## Original CLI

The original command-line interface remains available as `codex_usage.py` and
is still the core collector/reporting implementation used by the dashboard.
For CLI setup, commands, exports, authentication notes, and troubleshooting,
see the preserved [old README](README_OLD.md).

## Reports

The **Overview** shows the high-level Codex and Claude Code rate-limit and
model summaries. Use the link beneath **Codex models** or **Claude Code models**
to open the corresponding detail view. The Codex detail view includes reset
credits, profile statistics, local totals, daily usage, top sessions, and the
optional Admin API panels. The Claude Code detail view includes local totals,
daily usage, projects, and top sessions.

| Report | Dashboard/API value | Network |
| --- | --- | --- |
| Overview | `report=all` | Yes |
| Codex usage | `report=codex-usage` | Yes; includes reset credits, local/online usage, and optional Admin API usage/costs |
| Claude Code usage | `report=claude-usage` | No |
| Isambard service status | `report=isambard-status` | Yes, public pages; cached locally |

## Dashboard API

The web server also exposes local JSON endpoints:

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

Common query parameters:

| Parameter | Meaning | Default |
| --- | --- | --- |
| `report` | `all`, `codex-usage`, `claude-usage`, or `isambard-status` | `all` |
| `top` | Number of ranked rows to return | `10` |
| `days` | Recent local daily window | `30` |
| `warn_days` | Reset-expiry warning window | `7` |
| `bucket_width` | API usage bucket width: `1d`, `1h`, or `1m` | `1d` |
| `limit` | Optional API usage bucket limit | empty |
| `group_by` | Optional API usage grouping field, repeatable or comma-separated | empty |
| `no_costs` | Skip API costs query with `1`, `true`, or `yes` | `false` |
| `isambard_force_refresh` | Bypass the Isambard cache with `1`, `true`, or `yes` | `false` |

## Screenshots

<!-- markdownlint-disable MD033 -- HTML is used here so GitHub can render bounded thumbnails that link to the full-size screenshots. -->
<p>
  <a href="img/dashboard/1.png"><img src="img/dashboard/1.png" alt="Overview with Codex and Claude Code rate limits" width="220"></a>
  <a href="img/dashboard/2.png"><img src="img/dashboard/2.png" alt="Overview with service status and model detail links" width="220"></a>
  <a href="img/dashboard/3.png"><img src="img/dashboard/3.png" alt="Codex usage detail view" width="220"></a>
  <a href="img/dashboard/4.png"><img src="img/dashboard/4.png" alt="Codex local daily usage and reset credits" width="220"></a>
  <a href="img/dashboard/5.png"><img src="img/dashboard/5.png" alt="Claude Code usage detail view" width="220"></a>
  <a href="img/dashboard/6.png"><img src="img/dashboard/6.png" alt="Isambard service status in Chinese" width="220"></a>
</p>
<!-- markdownlint-enable MD033 -->

## Documentation

- [README.zh-CN.md](README.zh-CN.md): Chinese version of this README.
- [WEB_DASHBOARD.md](WEB_DASHBOARD.md): details for the local web dashboard.
- [README_OLD.md](README_OLD.md): the original long-form README for the
  CLI-focused version.

## Privacy And Safety

- The local dashboard serves from `127.0.0.1` by default.
- Local usage is read from Codex files on your machine.
- Claude Code tokens are read from `~/.claude/projects/**/*.jsonl`. Repeated
  streaming rows are deduplicated by request/message identity before summing.
- Claude rate limits come from the documented local statusLine payload; the
  dashboard never reads or reuses Claude OAuth credentials.
- Reset credits and online usage/profile reports use read-only Codex backend
  requests.
- The optional Admin API section within `codex-usage` uses documented OpenAI Admin API endpoints.
- The Isambard view reads two public status pages and stores only the parsed
  result in the ignored `isambard_status_snapshot.json` local cache.
- Do not commit `OPENAI_ADMIN_KEY`, Codex `auth.json`, exported private reports,
  or screenshots containing sensitive account data.

Codex backend endpoints used by the online reports are undocumented and may
change. Treat the output as useful operational information, not as a formal
billing statement.
