<p align="right"><strong>English</strong> | <a href="README.zh-CN.md">中文</a></p>

# Codex & Claude Code Usage Dashboard

A local dashboard for subscription limits, token history, models and sessions.
**Python 3.10+ · no third-party dependencies · one command to start.**
Codex and Claude Code work independently; public Isambard status and Codex Radar benchmarks are optional.

## Quick start

```sh
git clone https://github.com/Tyreal-Izual/Codex-Usage.git
cd Codex-Usage
python3 codex_claude_usage_web.py
```

Open the private access URL printed in the terminal. Stop with `Ctrl-C`.
On Windows, use `py -3` in place of `python3` (Python 3.10+).
No `pip`, Node.js, build step or API key is needed for the basic dashboard.

The default `--sources auto` detects local Codex/Claude installations at startup.
The **Isambard Status** and **Codex Radar** toolbar checkboxes are checked by default. Use them to toggle service status and benchmarks while the server is running.

| What you use | What you need |
| --- | --- |
| Codex only | Local `~/.codex` state; sign in to Codex for online limits |
| Claude Code only | Local `~/.claude/projects` transcripts; optional limit capture below |
| Both | Both data directories; each source works independently |
| Isambard Status / Codex Radar | Enabled by default; use the toolbar checkboxes |

```sh
python3 codex_claude_usage_web.py --sources codex --default-report codex-usage
python3 codex_claude_usage_web.py --sources claude --default-report claude-usage
python3 codex_claude_usage_web.py --sources all
python3 codex_claude_usage_web.py --check
```

`--check` prints paths, detected configuration and snapshot presence. It does not
read credential contents, launch clients, contact services, or write files.
Sources can also be selected with a comma-separated list: `codex,claude,isambard,radar`.
Source switches apply to the running server and are shared by its tabs. Restarting restores the startup selection. Local Days and Refresh Seconds are configured only at startup, for example `--days 60 --refresh 30`.

## Optional Claude limit capture

Local token history needs no setup. For 5-hour / 7-day subscription windows:

```sh
python3 claude_usage_statusline.py --install
```

Then complete a response in a compatible Claude Code client. The bridge saves a
sanitized snapshot; browser refresh only reads it. Existing custom status lines
are preserved unless you explicitly use `--force`.
See [Claude setup](docs/claude-setup.md) for details, uninstall instructions and
the optional macOS background refresher (`expect` / `launchd`).

## Common adjustments and troubleshooting

| Situation | Action |
| --- | --- |
| Port already in use | Add `--port 8766` |
| Different refresh interval | Add `--refresh 30` |
| Missing Codex online limits | Check the configured Codex home and sign in to Codex |
| Old Claude limit values | Check snapshot age and the [capture setup](docs/claude-setup.md) |
| Custom data directories | Set `CODEX_HOME` / `CLAUDE_CONFIG_DIR` |
| Configuration is unclear | Run `python3 codex_claude_usage_web.py --check` |

Update with `git pull --ff-only`, restart the server and open the new printed URL.
After moving the checkout, reinstall any Claude statusLine / background refresher
that references its old absolute path.

## Data and privacy

The server binds to `127.0.0.1` by default. The startup URL establishes an
authenticated browser session; keep it private. Reports read usage metadata,
not displayable conversation contents. Codex online endpoints are unofficial
and may change. This is not an official OpenAI or Anthropic tool.

Public caches live in the user's cache directory; exports default to
`~/Downloads/codex-usage`. Both are configurable. Source failures are isolated;
the browser renders completed sections while other sources load.
See [configuration and API](WEB_DASHBOARD.md) and [privacy details](docs/privacy.md).

## Documentation and development

- [Screenshots](docs/screenshots.md) · [Radar rules](docs/radar.md)
- [Configuration, cache locations and local API](WEB_DASHBOARD.md)
- [Development, tests and architecture](docs/development.md)
- [Original Codex CLI guide](README_OLD.md)

```sh
python3 -B -m unittest discover -v
```

Node.js is only needed for JavaScript regression tests. Tests use synthetic data
and local temporary HTTP servers; allow loopback binding and check for skips.

## Origin and license

The Codex collection/reporting core in `codex_usage.py` derives from
[MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage).
This is an independently maintained project. The combined dashboard, Claude
support, Isambard and Radar integration are additions by Frederick Zou.
Both copyright notices are retained in the [MIT license](LICENCE).
