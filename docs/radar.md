# Codex Radar benchmark curves

[Back to quick start](../README.md)

Radar is enabled by default. Toggle the Codex Radar checkbox in the toolbar to pause/resume it. `--sources` controls the initial selection.

The collector is in `codex_radar.py`; editable chart assets are in `static/radar.js` and `static/radar.css`. The default cache is in the per-user cache directory (`CODEX_USAGE_CACHE_DIR` overrides it).

When enabled, the Overview and Codex Usage views include a full-width **Codex Radar** panel
immediately below Codex Reset Credits (banked resets). It shows community
benchmark scores against combined cost, duration, or cost. It defaults to **GPT-6 (Astra, 6.1 Sol, 6 Sol, and Luna)**,
with a GPT-5 group and separate composite, software-engineering, and visual-spatial
views. Each view includes score cards and curves. The independent
`codex_radar.py` module owns collection, calculation and caching; chart source lives in `static/`; the web entry point only mounts it and exposes its cached data.
The title's Updated badge shows time since the last successful local sync;
hover over it for the exact sync and source-data timestamps.

While Radar is enabled and the dashboard server is running, a background worker checks the two public
benchmark sources and the optional distinct-task coverage endpoint every four
hours, even with the browser closed. The first run fetches immediately; a restart reuses a fresh disk cache. Sleep or
offline time can delay updates. Failed refreshes retain the last successful
snapshot and retry after 15, 30, 60, 120, then at most 240 minutes. The panel
distinguishes source-data time from local sync time and marks stale results.

The calculation follows Codex Radar's 2026-10-04 display rules:

- GPT-6.1 Sol and GPT-6 Sol/Luna need 30 valid software samples for composite IQ. Visual results
  contribute only with 30 valid samples of their own; otherwise the score is
  explicitly marked **Software only**. Missing scores are never treated as zero.
- GPT-6.1 Sol supports low, medium, high, xhigh, and max (no ultra), sharing
  the GPT-6 cost scale. Missing source scores show **Insufficient data** until
  a later background refresh supplies eligible results.
- Astra and GPT-5 composite scores still require both components. Individual
  benchmark views remain available independently.
- Sample counts and distinct-task coverage are separate. Coverage below 60% is
  flagged; a failed coverage request is shown as unknown without blocking score
  updates. Quality information describes the last local snapshot.
- Source costs may be medians; composite costs are weighted by sample counts.
  They are no longer all labelled as average prices.
- Cost is proportional to `price * (minutes / 10) ** (log(2.5) / log(1.35))`.
  The largest cost **within the selected generation and benchmark** is 100;
  these indexes are not absolute cross-generation prices.
- A valid IQ remains visible on its card when cost or duration is missing;
  invalid coordinates are omitted from the corresponding curve.

The horizontal axis remains logarithmic, with a marked compressed gap where
needed. Legacy caches refresh on startup; failed upgrades retain a stale-marked
snapshot and back off before retrying. Scores are community benchmarks, not
account usage or official ratings.

The authenticated `GET /api/codex-radar` endpoint only reads memory; it never
starts an upstream fetch. Browser refresh controls do not override the four-hour
schedule. Hover, tap, or keyboard-focus a point for values, or expand the data
table. English/Chinese follows the dashboard language.

The ignored `codex_radar_snapshot.json` file stores sanitized benchmark data and
retry timing, with no credentials. A standalone cache update is also available:

```sh
python3 codex_radar.py                 # update only when due, then print JSON
python3 codex_radar.py --force         # explicitly refresh the disk cache now
python3 codex_radar.py --cache /tmp/radar.json
```

Standalone updates are loaded by the web service on its next restart; the running
service owns its in-memory snapshot. No LaunchAgent or Codex scheduled task is
required. Upstream website interfaces may change; incompatible responses leave
the last valid cache intact.
