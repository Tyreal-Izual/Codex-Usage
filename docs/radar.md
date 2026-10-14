# Codex Radar benchmarks

[Back to quick start](../README.md)

Radar is enabled by default; use the toolbar checkbox to pause/resume collection.
The collector remains in `codex_radar.py`, with editable chart assets in
`static/radar.js` and `static/radar.css`. The panel appears below Banked Resets
when that card is present. It also works when Radar is the only enabled source.

## Current benchmark: RadarBench

The integration follows the [public Radar site](https://codexradar.com/)'s
2026-10-13 RadarBench contract. The old composite IQ / software / visual views
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
- Cost means **API-equivalent USD**, not subscription deductions or cash charges.
  Cost and duration use all evidenced valid grades for the current task set and
  configuration; their sample window differs from the score's latest-three rule.
  Each metric shows known/total samples. Partial means use only known samples;
  unavailable or invalid statistics do not erase a valid score.
- The chart and its controls appear above the score cards. The default chart shows daily score history for one model, with distinct effort
  markers and line styles. Select another model or switch to cost/time versus
  score. Daily history is the final score per **UTC grading day**; days without
  grades are omitted, and the date is not an exact grading timestamp. The data
  table includes both current scores and the selected model's history.

## Synchronization and cache

While enabled and the server is running, the worker reads the public binding
and each of its 34 configurations sequentially every four hours. Requests have
bounded timeouts and response sizes. Browser refresh only reads the authenticated
`GET /api/codex-radar` memory cache and never starts an upstream request.
The browser need not stay open. Sleep or offline time can delay synchronization.

The title age is time since the last successful **local sync**. The latest UTC
grading day is shown separately. The public summary does not provide exact
individual grading timestamps.

A refresh replaces the cache only after all configurations pass validation for
the same catalog and task digest. Failure retains the last successful snapshot
and retries after 15, 30, 60, 120, then at most 240 minutes. Old cache versions
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
