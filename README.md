**English** | [简体中文](README.zh-CN.md)

# Usage for Mac

A native SwiftUI dashboard for Codex and Claude Code limits, tokens, models and
sessions, with Isambard status and Codex Radar. **macOS 14.4+ only.**

## Build and open

Requires full Xcode 15.3+ and Python 3.10+ to build; standalone Command Line Tools are insufficient.
Quit Usage with `⌘Q`, then run from the checkout root:

```sh
./scripts/build_macos.sh
open dist/Usage.app
```

The first build installs PyInstaller in `.build/python`. The resulting app bundles
Python and runs without a terminal, browser or separate Python/Node installation.
It targets the build Mac's CPU architecture. Local builds use ad-hoc signing;
public distribution still needs Developer ID signing and notarization.

## Use

Overview order: **Limits → Isambard → Models → Codex Reset Credits → Radar**.
Codex and Claude limits occupy separate rows; model cards sit side by side when
space permits. Compact cards show reset countdowns, expandable service details and
credit-expiry hints. Headers wrap as needed, and changed numbers briefly highlight.

- **Settings (`⌘,`)**: sources, English/Chinese, refresh interval and history rows.
- **Back to limits**: align Codex limits with the top; startup does this once after
  loading. Later refreshes preserve your scroll position.
- **Refresh (`⌘R`)**: collect according to source caches; Radar syncs every four hours.
  **Reconnect** is available in the toolbar and menu bar during collection or after a disconnect.
- **Export**: save the current reports, update times and errors as JSON.
- **Menu bar**: remaining quota with its window; falls back to weekly when needed.
  Closing the window keeps the app running; `⌘Q` quits.

Codex and Claude work independently. Local history needs no capture installation.
Online Codex limits require an existing sign-in; Claude subscription limits need
the optional [capture setup](docs/claude-setup.md).
Use Settings → Check setup / Reconnect collectors for diagnostics.

## Reference

- [Development, configuration and checks](docs/development.md) · [Data scope](docs/development.md#data-boundaries)
- [Radar rules](docs/radar.md) · [Privacy](docs/privacy.md)
- [Legacy CLI](README_OLD.md) · [Legacy web API](WEB_DASHBOARD.md)

The Codex collector derives from [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage).
Frederick Zou independently maintains the native app and additional integrations.
The [MIT license](LICENCE) retains both copyright notices. This is not an official
OpenAI or Anthropic app.
