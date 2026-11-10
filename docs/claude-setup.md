# Claude Code capture on macOS

[Quick start](../README.md) · [中文](claude-setup.zh-CN.md)

Local token history is read from `~/.claude/projects/**/*.jsonl` with no setup.
See [data boundaries](development.md#data-boundaries) for aggregation rules.
The 5-hour/7-day limits require a sanitized snapshot at `~/.claude/usage-dashboard.json`.
App refresh reads that snapshot; it does not force an account refresh.
The 7-day window is the all-model total. Model-specific allowances (such as Fable)
never overwrite or substitute for that total, even when it is missing.

## Status line capture

From the checkout root after building the app:

```sh
HELPER="$PWD/dist/Usage.app/Contents/Resources/helper/usage-helper"
"$HELPER" --statusline --install
"$HELPER" --statusline --status
```

For an app moved to Applications, set `HELPER` to
`/Applications/Usage.app/Contents/Resources/helper/usage-helper` instead.

Then complete a response in a compatible Claude Code client. An existing custom
status line is preserved unless you explicitly pass `--force`. Remove capture with
`"$HELPER" --statusline --uninstall`. Reinstall after moving the app.
For a source checkout, use `python3 claude_usage_statusline.py` with the same flags.
The app also shows the exact installation command when no snapshot is available.

## Optional scheduled refresh

This uses the signed-in Claude CLI's `/usage` screen without sending a prompt or
resuming a conversation. It requires `expect` and an existing trusted project.
Choose that project explicitly; no trust prompts are accepted automatically.

```sh
"$HELPER" --refresh-claude --once --force --project-dir "$PWD"
"$HELPER" --refresh-claude --install --project-dir "$PWD"
"$HELPER" --refresh-claude --status
# Remove the schedule:
"$HELPER" --refresh-claude --uninstall
```

In a source checkout, replace `"$HELPER" --refresh-claude` with
`python3 claude_usage_refresher.py`. The job checks every minute, normally refreshes
around every ten minutes and checks shortly after a recorded reset. Failed attempts
back off for 5–40 minutes. It runs while the Mac is awake and logged in.
Reinstall after moving the app, project or Claude executable.

The snapshot contains only limit percentages, reset times and capture metadata.
Old snapshots remain visibly stale. A confirmed logged-out CLI check prompts
`claude auth login` when the snapshot is stale or unavailable; a missing CLI or
timeout is not treated as proof of logout.
Use matching [path overrides](development.md#configuration) for capture and the app.
