# Codex degradation radar

[Quick start](../README.md) · [中文](radar.zh-CN.md)

Radar reads the published total-score panel on the
[Codex Radar homepage](https://codexradar.com/#stationmaster-round).
It is enabled by default and can be paused in Settings.

## Data and display

- The adapter targets the four-task assessment (Qin Shi Huang, Pompeii, Pelican,
  Candy), with 46 configurations. Totals are read directly, not recomputed.
- Cards use two decimals and a fixed **score / 150** bar, with gaps at 50 and 100.
  A colored top edge becomes a full outline on hover. Zero is `0.00`; an unscored
  configuration is `—`. Old IQ/RadarBench snapshots are not valid fallback data.
- The native grid has six equal columns: ultra → max → xhigh → high → medium → low.
  Luna has no ultra cell. Unsupported cells stay empty; narrow windows scroll all
  rows horizontally together. Cost, duration and history charts are omitted.
- Local sync time and the source test period are separate. The latter is converted
  from Beijing time to the Mac's timezone; syncing does not imply a new test round.

## Refresh and cache

The worker requests the homepage every four hours while the app and source are
running. Ordinary App refresh only reads the snapshot. Each fetch has a 20-second
socket timeout and a 4 MiB limit. Transient errors (including HTTP 502/503/504) get
at most two extra attempts after 1 and 3 seconds; certificate/parse errors do not.

Failed cycles retain the last valid snapshot and retry after 15, 30, 60, 120, then
240 minutes. Invalid, incomplete or older panels cannot replace the cache. Pause/quit
interrupts retry waits; sleep/offline time may delay work. Source HTML changes may
require an adapter update.

The cache is `codex_radar_snapshot.json` under the [public cache directory](development.md#configuration).
For a manual source-checkout update, quit Usage first, then reopen it afterward:

```sh
python3 codex_radar.py --force
# Optional path override:
python3 codex_radar.py --cache /tmp/radar.json --force
```

These are community assessments, not account usage or official model ratings.
