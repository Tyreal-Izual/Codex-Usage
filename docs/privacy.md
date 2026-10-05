# Privacy and limitations

[Quick start](../README.md)

- The server listens on `127.0.0.1` by default.
- Codex and Claude transcript/state files are read but not modified; the Claude
  bridges write only the sanitised usage snapshot and refresher support files.
- Claude streaming rows are deduplicated before token totals are calculated.
- The Claude statusLine bridge never reads or reuses Claude OAuth credentials.
- The optional refresher runs the normal Claude Code client and may perform its
  usual startup network requests or configured hooks, but sends no prompt and
  does not resume a conversation or save its terminal output.
- Codex reset-credit and online-profile requests are read-only.
- OpenAI Admin API access is optional and uses documented endpoints.
- Isambard data comes from public status pages; only parsed cache data is kept.
- Radar requests only public benchmark metadata, sends no local account or
  conversation data, and stores its snapshot in a Git-ignored cache file.
- Individual collectors fail independently so one unavailable source does not
  take down the whole dashboard.

Some Codex subscription endpoints used by the upstream-derived collector are
undocumented and may change. Treat all displayed values as operational
information rather than a contractual billing statement. Do not commit API
keys, `auth.json`, private exports, cached account data, or sensitive
screenshots.
