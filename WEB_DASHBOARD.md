# Legacy web interface

[Native Mac app](README.md) · [原生应用](README.zh-CN.md)

This compatibility/debugging server is separate from the SwiftUI app. Its browser
controls and startup arguments do not configure the native app.

## Start

```sh
python3 codex_claude_usage_web.py --sources auto
python3 codex_claude_usage_web.py --check
python3 codex_claude_usage_web.py --help
```

Open the private access URL printed in the terminal. The server defaults to
`127.0.0.1:8765`; `Ctrl-C` stops it. The startup token establishes a browser cookie
and is removed from the URL. An API client may use `Authorization: Bearer <token>`.
Tokens change on restart. All routes validate Host; wildcard binding requires an
explicit `--allowed-host` and exposes the server beyond the local machine.

## Startup options

| Option | Values / default |
| --- | --- |
| `--sources` | `auto`, `all`, or comma-separated `codex,claude,isambard,radar` |
| `--default-report` | `all`, `codex-usage`, `claude-usage`, `isambard-status` |
| `--days`, `--refresh` | Daily rows: 30 (max 365); browser polling: 15 seconds |
| `--port`, `--host`, `--allowed-host` | Bind address and accepted hostnames |
| `--cache-dir`, `--quiet` | Public cache override; disable access logging |
| `--max-workers`, `--max-collectors` | HTTP concurrency: 4; distinct collections: 2 |
| `--cache-seconds`, `--check` | Whole-report cache: 5 seconds; read-only setup diagnostics |

Browser requests are progressive with at most two sections in flight. Public-source
switches are shared by tabs and reset on server restart. An in-flight fetch may
finish after a switch is disabled. Use `?report=claude-usage` to select a view.
[Shared paths, environment and source caches](docs/development.md#configuration)
and [Radar behavior](docs/radar.md) apply here too; legacy web layouts may differ.

## HTTP API

| Route | Result |
| --- | --- |
| `GET /`, `/index.html` | Authenticated dashboard |
| `GET /isambard-maintenance` | Authenticated maintenance page |
| `GET /healthz` | Health only; no authentication or account data |
| `GET /api/usage` | Report JSON |
| `GET /api/codex-radar` | Memory snapshot; never starts an upstream fetch |
| `GET /api/sources` | Enabled sources |
| `POST /api/sources?isambard=false&radar=true` | Update public sources; requires `X-Codex-Usage-Action: set-sources` |

Pages and data APIs require authentication. `/api/usage` accepts:

| Parameter | Values / default |
| --- | --- |
| `report` | `all`, `codex-usage`, `claude-usage`, `isambard-status`, `resets`, `local-usage`, `online-usage`, `api-usage` |
| `top`, `days`, `warn_days` | 10 (max 100), 30 (max 365), 7 |
| `bucket_width`, `limit` | `1d`, `1h`, `1m`; optional Admin bucket count (max 1440) |
| `group_by`, `no_costs` | Repeated/comma-separated Admin fields; `true`, `1`, `yes` skips costs |
| `isambard_force_refresh` | Authenticated POST only, with `X-Codex-Usage-Action: force-refresh` |

Forced Isambard fetches are limited to one start per 30 seconds. Admin reports need
`OPENAI_ADMIN_KEY`; disabled sources return `disabled: true`. Combined reports remain
complete snapshots. See [privacy](docs/privacy.md) for data handling.
