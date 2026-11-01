# Codex degradation radar

[Back to quick start](../README.md)

Radar is enabled by default; use its toolbar checkbox to pause/resume collection.
`codex_radar.py` owns collection and caching; `static/radar.js` and `static/radar.css`
render the cards. The panel appears below Banked Resets when present and also
works when Radar is the only enabled source.

## Current source and display

The integration follows the [homepage degradation radar](https://codexradar.com/#stationmaster-round)
as verified on **2026-10-31**. This assessment uses Qin Shi Huang, Pompeii, Pelican
and Candy. It is separate from the previous 64-task RadarBench; scores from those
benchmarks are never mixed or used as fallback for this one.

- The collector reads the already-published **total / 150** from the homepage's
  total-score table. It does not reconstruct totals from component scores or
  execute scripts, download artwork, or read account data.
- The reviewed catalog has 46 configurations across GPT-6.1 Sol, GPT-6 Astra,
  GPT-6.1 Terra, GPT-6 Sol, GPT-6 Luna, GPT-5.6 Sol, GPT-5.6 Terra and GPT-5.6 Luna.
  Luna supports low through max; the other families include ultra.
- Cards show only the score and a thin bar with width **score / 150 × 100%**.
  Scores use two decimal places, matching the published totals. All models share
  the fixed 150-point scale. Zero is `0.00` with an empty bar; missing scores are
  `—` with a dashed placeholder. Cost, duration, historical curves and the old
  RadarBench coverage/record counts are not shown.
- The title age measures time since the last successful **local sync**. The source
  test period is shown separately: the homepage publishes its start/end to the
  minute in Beijing time, which the dashboard displays in the browser's timezone.
  A successful sync does not mean the source ran a new test round.

## Refresh and failure handling

The worker makes **one homepage request every four hours** while enabled and the
server is running. The authenticated `GET /api/codex-radar` endpoint reads memory
only. Browser refresh never triggers an upstream fetch; the browser need not stay
open. Sleep or offline time can delay synchronization.

Each request uses a 20-second socket timeout and a 4 MiB response limit. Timeouts,
connection failures and HTTP 502/503/504 receive at most **two additional attempts**,
after 1 and 3 seconds. Pause/stop interrupts the wait before another request.
Invalid data, certificate errors and other HTTP errors are not retried immediately.
After all attempts fail, the last successful degradation snapshot remains visible
with its original sync time. Scheduled retries back off for 15, 30, 60, 120, then
at most 240 minutes, and their deadline survives restart.

All 46 configurations, the four-component/150-point heading, the source test period,
and score ranges must pass validation before replacing the cache. A partial page,
changed catalog or older test period leaves the last valid snapshot intact. Source
HTML changes may require an adapter update. Earlier IQ and RadarBench caches are
discarded from display; upgrading triggers an immediate fetch of the new source.

## Cache and manual update

The default cache is `codex_radar_snapshot.json` in the per-user cache directory
(`CODEX_USAGE_CACHE_DIR` overrides it). Only normalized model IDs, efforts, totals
and test-period metadata are stored; the source page and artwork are not retained.

```sh
python3 codex_radar.py                 # update if due, then print JSON
python3 codex_radar.py --force         # refresh the disk cache now
python3 codex_radar.py --cache /tmp/radar.json
```

If the web server uses `--cache-dir`, point the standalone command's `--cache` at
that directory's `codex_radar_snapshot.json` file. Stop the dashboard before a
standalone cache update, then restart it; the command does not update a running
service's memory and two processes should not write the same cache concurrently.

```sh
python3 codex_radar.py --cache /tmp/codex-usage-cache/codex_radar_snapshot.json --force
python3 codex_claude_usage_web.py --cache-dir /tmp/codex-usage-cache
```

Restart the service after upgrading the code. No separate scheduler is required.
These are community assessments, not account usage or official model ratings.
