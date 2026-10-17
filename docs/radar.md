# Codex Radar benchmarks

[Back to quick start](../README.md)

Radar is enabled by default; use the toolbar checkbox to pause/resume collection.
The collector remains in `codex_radar.py`, with editable chart assets in
`static/radar.js` and `static/radar.css`. The panel appears below Banked Resets
when that card is present. It also works when Radar is the only enabled source.

## Current benchmark: RadarBench

The integration follows the [public Radar site](https://codexradar.com/)'s
2026-10-17 public summary v6 contract (with retained v5 cache compatibility). The old composite IQ / software / visual views
are legacy benchmarks and must not be compared with the new scores.

- The verified catalog contains 64 tasks from DeepSWE, Pompeii, TB4 and Science.
  Scores are on a 0–150 scale and are read directly from the public summary API.
  Scoring uses each task's latest three valid grades, with equal weight among
  covered tasks. Missing tasks are not zero; a real zero score is retained.
- The current display includes Astra, 6.1 Sol, 6 Sol, 5.6 Sol, 6 Luna and
  5.6 Luna: 34 configurations. Sol and Astra include **ultra**; Luna stops at
  **max**. The old 30-sample eligibility threshold does not apply to RadarBench.
- Cards show **Provisional**, **Complete** or **Not graded**, task coverage out
  of 64, and the number of records used for scoring (up to three per covered task).
- The panel shows only the authoritative **total Radar score**, grouped into
  model rows with effort cards ordered ultra → low. Each card shows a one-decimal
  score and a thin bar with width **score / 150 × 100%**. The scale is fixed across
  all models, not normalized to the best score in each row. Luna starts at max.
- A real zero shows `0.0` with an empty bar; missing results show `—` with a dashed
  placeholder. Coverage, grading-record count and status remain as context.
- The history chart, model selector, cost/time views and source-specific score
  tabs are removed. The expandable table contains current scores only. Narrow
  screens wrap cards into three or two columns.

## Synchronization and cache

While enabled and the server is running, the worker reads the public binding
and each of its 34 configurations sequentially every four hours. Requests have
bounded timeouts and response sizes. Browser refresh only reads the authenticated
`GET /api/codex-radar` memory cache and never starts an upstream request.
The browser need not stay open. Sleep or offline time can delay synchronization.

The title age is time since the last successful **local sync**. The latest UTC
grading day is shown separately, based on the source daily history. It is not
the exact grading timestamp. History remains in the cache but is not displayed.

A refresh replaces the cache only after all configurations pass validation for
the same catalog and task digest. Failure retains the last successful snapshot
and retries after 15, 30, 60, 120, then at most 240 minutes. The previous v5
RadarBench summaries remain valid fallback scores during the v6 upgrade. Old cache versions
trigger an immediate upgrade. Legacy IQ is never displayed, including on failure:
without a valid RadarBench snapshot the panel shows an unavailable message.
Only successful RadarBench snapshots are retained as fallback.

The default cache is `codex_radar_snapshot.json` in the per-user cache directory
(`CODEX_USAGE_CACHE_DIR` overrides it). It contains public benchmark metadata,
no account credentials. The source checkbox pauses subsequent requests; an
already-running request may finish before the worker observes the change.

```sh
python3 codex_radar.py                 # update if due, then print JSON
python3 codex_radar.py --force         # refresh the disk cache now
python3 codex_radar.py --cache /tmp/radar.json
```

Standalone updates are loaded by the web service on its next restart. Restart a
running dashboard after upgrading the code. No separate scheduler is required.
An incompatible source catalog or response leaves the last valid cache intact.
Scores are community benchmarks, not account usage or official model ratings.
