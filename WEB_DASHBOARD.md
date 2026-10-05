# Dashboard configuration and API / 仪表盘配置与 API

[English quick start](README.md) · [中文快速开始](README.zh-CN.md)

## Startup options / 启动参数

```sh
python3 codex_claude_usage_web.py --help
python3 codex_claude_usage_web.py --sources all --refresh 30 --quiet
python3 codex_claude_usage_web.py --sources claude --default-report claude-usage
python3 codex_claude_usage_web.py --cache-dir /tmp/codex-usage-cache --check
```

| Option | Meaning / 作用 |
| --- | --- |
| `--sources auto` | Default: detect local Codex/Claude and enable Isambard/Radar; 默认检测本地来源并勾选两项公共来源 |
| `--sources all` | Enable Codex, Claude, Isambard and Radar; 恢复完整总览 |
| `--sources codex,radar` | Enable only the listed sources; 只启用列出的来源 |
| `--default-report` | `all`, `codex-usage`, `claude-usage`, `isambard-status` |
| `--check` | Read-only JSON setup diagnostics, then exit; 只读配置检查 |
| `--cache-dir` | Public-source disk cache directory; 公共来源缓存目录 |
| `--port 8766` | Change the default port 8765; 修改端口 |
| `--refresh 30` | Browser interval (default 15 seconds), local configuration only; 仅本地配置 |
| `--days 60` | Local daily rows (default 30, maximum 365), local configuration only; 仅本地配置 |
| `--quiet` | Disable per-request access logs; 关闭访问日志 |
| `--max-workers` | Simultaneous HTTP requests, default 4 |
| `--max-collectors` | Simultaneous report collections, default 2 |
| `--cache-seconds` | Whole-report reuse window, default 5 seconds; per-source caches remain independent |

The page URL can override the default view with `?report=claude-usage` after
sign-in. Disabled sources return `disabled: true` and never run collectors.
An optional Admin API section appears only when `OPENAI_ADMIN_KEY` is configured
and Codex is enabled. Browser language is saved locally.

首次认证后可用 `?report=claude-usage` 指定视图。关闭的来源不会执行采集。
默认自动检测的结果在重启服务时更新；安装或登录新客户端后请重启。

Toolbar: Report (Overview by default), Language, Isambard Status, Codex Radar, Auto Refresh and Refresh.
The two public sources are checked by default. Switching one off hides its panel and stops new
collection work; Radar's background worker pauses. An already-running fetch may finish.
The switches are shared by this server's tabs, synchronized on refresh, and reset to the startup
selection when the server restarts. Explicit `--sources` selections determine initial checkboxes.

工具栏保留 Report／语言／自动刷新／刷新，并加入默认勾选的 Isambard Status 和 Codex Radar。
Local Days 与 Refresh Seconds 仅通过本地启动参数调整。关闭来源不会删除缓存。

## Refresh behavior / 刷新行为

The browser requests at most two sections concurrently and displays each result
as it arrives. An unavailable source leaves the other sections usable. Existing
results remain visible during refresh. Switching the report or source selection never
renders a late response for the old selection.

| Source | Reuse / 更新策略 |
| --- | --- |
| Codex local | 5-second source cache; unchanged JSONL files reuse parsed metadata |
| Codex online/reset credits | 60-second source cache, shared across views |
| Claude | 15-second source cache; unchanged JSONL files reuse parsed metadata |
| Optional Admin API | 60-second source cache |
| Isambard | 30-second source cache over a 5-minute disk cache |
| Radar | Independent 4-hour worker, only started when enabled |

网页同时最多加载两个区块，逐块显示结果。刷新间隔控制读取频率，各来源仍使用自己的缓存。
手动刷新仅对 Isambard 绕过缓存，30 秒内最多启动一次；不会强制刷新 Radar 或 Claude 限额。
`days` 控制本地每日表保留的最近有记录日期行数，模型和总 token 统计仍为全部历史。

## Paths and environment / 路径与环境变量

| Variable | Purpose / 用途 |
| --- | --- |
| `CODEX_HOME` | Codex state directory; default `~/.codex` |
| `CLAUDE_CONFIG_DIR` | Claude state directory; default `~/.claude` |
| `CLAUDE_BIN` | Explicit Claude launcher for auth checks and the refresher |
| `CLAUDE_USAGE_PROJECT_DIR` | Temporary refresher session's project |
| `CLAUDE_USAGE_SNAPSHOT` | Claude limit snapshot; default `~/.claude/usage-dashboard.json` |
| `CLAUDE_USAGE_STALE_SECONDS` | Snapshot stale threshold; default 900 seconds |
| `CODEX_USAGE_CACHE_DIR` | Public caches; overridden by `--cache-dir` |
| `CODEX_USAGE_EXPORT_DIR` | CLI export directory; overridden by `export --output-dir` |
| `SSL_CERT_FILE` | CA bundle override for public status/benchmark requests |
| `OPENAI_ADMIN_KEY` | Optional organization usage/cost API; not needed for subscriptions |

Default public cache locations:

- macOS: `~/Library/Caches/codex-usage`
- Linux: `$XDG_CACHE_HOME/codex-usage`, or `~/.cache/codex-usage`
- Windows: `%LOCALAPPDATA%/codex-usage`

Exports default to `~/Downloads/codex-usage`:

```sh
python3 codex_usage.py export --report local-usage --format json --output-dir ./exports
```

Earlier repository-local public caches are read as a fallback when the new
default cache file is absent. New writes use the user cache directory; existing
files are not deleted. Custom cache directories do not read legacy caches.
缓存写入失败不会丢弃已抓取的数据。旧仓库缓存仅作为默认路径的回退读取，原文件不会被删除。

## Local HTTP API / 本地接口

| Route | Result |
| --- | --- |
| `GET /`, `GET /index.html` | Authenticated dashboard |
| `GET /isambard-maintenance` | Authenticated maintenance page |
| `GET /healthz` | Health check; no account data or authentication required |
| `GET /api/usage` | Usage JSON |
| `GET /api/codex-radar` | In-memory snapshot only; never triggers a fetch |
| `GET /api/sources` | Current enabled sources |
| `POST /api/sources?isambard=false&radar=true` | Change public-source switches; authenticated, requires `X-Codex-Usage-Action: set-sources` |

Pages and data APIs require the browser session cookie, or
`Authorization: Bearer <token from startup URL>`. Tokens change on restart.
Host validation applies to all routes. A wildcard bind requires an explicit
accepted hostname, for example `--host 0.0.0.0 --allowed-host 192.0.2.10`;
this exposes the server beyond the local machine.

`/api/usage` parameters:

| Parameter | Values / default |
| --- | --- |
| `report` | `all` (default), `codex-usage`, `claude-usage`, `isambard-status`, `resets`, `local-usage`, `online-usage`, `api-usage` |
| `top` | Default 10, maximum 100 |
| `days` | Default 30, maximum 365 |
| `warn_days` | Default 7 |
| `bucket_width` | `1d` (default), `1h`, `1m` |
| `limit` | Optional Admin bucket count; maximum 1440 |
| `group_by` | Optional Admin grouping fields, repeated or comma-separated |
| `no_costs` | `true`, `1`, `yes` skips Admin costs |
| `isambard_force_refresh` | Requires authenticated POST and `X-Codex-Usage-Action: force-refresh` |

Combined `all` / `codex-usage` API responses remain complete snapshots for existing
clients. Progressive rendering is a browser behavior using the individual reports.

See [Claude setup](docs/claude-setup.md), [中文 Claude 设置](docs/claude-setup.zh-CN.md),
[Radar rules](docs/radar.md) and [中文 Radar 规则](docs/radar.zh-CN.md).
