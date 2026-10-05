#!/usr/bin/env python3
"""Codex Radar collector, four-hour cache worker, and standalone dashboard widget.

Only public benchmark metadata is requested. No account or transcript data is
sent. The composite calculation follows https://codexradar.com/ (2026-10-04).
Run this file directly to update the cache once; the web server owns the worker.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from dashboard_assets import asset_text
from usage_common import atomic_write_json, cache_directory, ssl_context

SOURCE_URL = "https://codexradar.com/"
METRICS_URL = SOURCE_URL + "api/intelligence-efficiency-metrics"
VISUAL_URL = SOURCE_URL + "api/visual-spatial-reasoning"
COVERAGE_URL = SOURCE_URL + "api/intelligence-efficiency-coverage"
CACHE_VERSION = 3
REFRESH_SECONDS = 4 * 60 * 60
RETRY_SECONDS = 15 * 60
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_CACHE_PATH = cache_directory() / "codex_radar_snapshot.json"
LEGACY_CACHE_PATH = Path(__file__).resolve().with_name("codex_radar_snapshot.json")
MODEL_NAMES = {
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.5": "GPT-5.5",
}
NEW_GPT6 = frozenset({"gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"})
MIN_SAMPLES = 30
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
MODEL_GROUPS = {
    "gpt6": ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"),
    "gpt5": ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"),
}
MODEL_EFFORTS = {model: EFFORTS[:-1] if model in {"gpt-6.1-sol", "gpt-6-luna"} else EFFORTS
                 for model in MODEL_NAMES}
COST_WEIGHT = math.log(2.5) / math.log(1.35)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def iso_time(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def source_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Radar source timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Radar source timestamp must include its timezone")
    return parsed.astimezone(timezone.utc)


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={
        "User-Agent": "Codex-Usage-Dashboard/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=20, context=ssl_context()) as response:
        cache_status = response.headers.get("X-Codex-Cache", "")
        if not cache_status or cache_status.startswith("STALE") or cache_status == "ERROR":
            raise ValueError("Radar upstream is not serving a current snapshot")
        if url == COVERAGE_URL:
            age = float(response.headers.get("X-Codex-Cache-Age", "nan"))
            fetched = float(response.headers.get("X-Codex-Fetched-At", "nan"))
            if not math.isfinite(age) or not 0 <= age < 300 or not math.isfinite(fetched) or fetched <= 0:
                raise ValueError("Radar task coverage cache age is unknown or expired")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Radar response exceeds the size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Radar response must be a JSON object")
    return value


def component_points(payload: dict[str, Any], *, software: bool) -> dict[tuple[str, str], dict[str, Any]]:
    if software:
        if (payload.get("schema"), payload.get("mode")) not in {
            (3, "equal_latest_3"), (2, "weighted_latest_3"),
        }:
            raise ValueError("Unsupported Radar software schema")
        weight_field = "total" if payload["schema"] == 3 else "weighted_total"
    else:
        if payload.get("schema") != 1 or payload.get("type") != "visual_spatial_reasoning_summary":
            raise ValueError("Unsupported Radar visual schema")
        weight_field = "valid_tasks"
    rows = payload.get("points")
    if not isinstance(rows, list):
        raise ValueError("Radar points must be a list")
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid Radar point")
        model, effort = row.get("model"), row.get("effort")
        if not isinstance(model, str) or not isinstance(effort, str):
            raise ValueError("Invalid Radar model or effort")
        if model not in MODEL_NAMES or effort not in MODEL_EFFORTS[model]:
            continue
        fields = {key: finite_number(row.get(key)) for key in
                  ("iq", "average_price_usd", "average_minutes", weight_field)}
        if any(row.get(key) is not None and fields[key] is None for key in fields):
            raise ValueError("Non-finite Radar metric")
        if fields["iq"] is None or fields[weight_field] is None:
            continue
        if not 0 <= fields["iq"] <= 150 or any(
            fields[key] is not None and fields[key] < 0 for key in fields if key != "iq"
        ):
            raise ValueError("Radar metric outside its valid range")
        if fields[weight_field] == 0:
            continue
        key = (model, effort)
        if key in out:
            raise ValueError("Duplicate Radar model/effort")
        out[key] = {**fields, "weight": fields[weight_field],
                    "benchmark_tasks": finite_number(row.get("benchmark_tasks")),
                    "price_aggregation": row.get("price_aggregation") if row.get("price_aggregation") in ("median", "mean") else "unknown"}

    return out


def normalize_costs(points: list[dict[str, Any]]) -> None:
    """Normalize independently within GPT-6 and GPT-5, as the upstream tabs do."""
    for models in MODEL_GROUPS.values():
        group = [p for p in points if p["model"] in models]
        logs = {}
        for index, point in enumerate(group):
            price, minutes = point["average_price_usd"], point["average_minutes"]
            point["combined_cost_index"] = None
            if price is not None and minutes is not None and price > 0 and minutes > 0:
                logs[index] = math.log(price) + COST_WEIGHT * (math.log(minutes) - math.log(10))
        if logs:
            largest = max(logs.values())
            for index, cost in logs.items():
                group[index]["combined_cost_index"] = math.exp(cost - largest) * 100


def coverage_points(payload: dict[str, Any]) -> dict[tuple[str, str], tuple[int, int]]:
    if (payload.get("schema") != 1 or payload.get("benchmark_id") != "deep-swe"
            or payload.get("coverage_mode") != "distinct-task-selected-n-v1"):
        raise ValueError("Unsupported Radar task coverage schema")
    total = payload.get("total_tasks")
    if type(total) is not int or total <= 0 or not isinstance(payload.get("points"), list):
        raise ValueError("Invalid Radar task coverage")
    source_time(payload.get("latest_graded_at"))
    result = {}
    for row in payload["points"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid Radar task coverage row")
        model, effort, covered = row.get("model"), row.get("effort"), row.get("covered_tasks")
        if not isinstance(model, str) or not isinstance(effort, str):
            raise ValueError("Invalid coverage identity")
        if model not in MODEL_NAMES or effort not in MODEL_EFFORTS[model]:
            continue
        key = (model, effort)
        if type(covered) is not int or not 0 <= covered <= total or key in result:
            raise ValueError("Invalid or duplicate task coverage")
        result[key] = (covered, total)
    return result


def combine_snapshots(software: dict[str, Any], visual: dict[str, Any],
                      coverage: dict[tuple[str, str], tuple[int, int]] | None = None) -> dict[str, Any]:
    """Mirror the current source's composite eligibility and generation tabs.

    GPT-6.1 Sol and GPT-6 Sol/Luna need 30 software samples; visual contributes only with 30 of
    its own. Astra and GPT-5 retain the two-component rule. Missing components
    are omitted, never treated as zero. Price input may be a median despite the
    upstream field's legacy average_price_usd name.
    """
    software_at = source_time(software.get("source_updated_at"))
    visual_at = source_time(visual.get("source_updated_at"))
    left = component_points(software, software=True)
    right = component_points(visual, software=False)
    coverage = coverage or {}
    views = {name: {"points": []} for name in ("comprehensive", "software", "visual")}
    samples = []
    for model in MODEL_NAMES:
        for effort in EFFORTS:
            key = (model, effort)
            a, b = left.get(key), right.get(key)
            if a is None and b is None:
                continue
            software_n, visual_n = (a["weight"] if a else 0), (b["weight"] if b else 0)
            covered, total = coverage.get(key, (None, None))
            samples.append({"model": model, "effort": effort, "software_samples": software_n,
                            "visual_samples": visual_n, "software_covered_tasks": covered,
                            "software_benchmark_tasks": total,
                            "visual_benchmark_tasks": b.get("benchmark_tasks") if b else None})
            meta = samples[-1]
            for mode, component in (("software", a), ("visual", b)):
                if component is None or (model in NEW_GPT6 and component["weight"] < MIN_SAMPLES):
                    continue
                views[mode]["points"].append({**meta, "iq": component["iq"],
                    "average_price_usd": component["average_price_usd"], "average_minutes": component["average_minutes"],
                    "price_aggregation": component["price_aggregation"], "score_basis": mode})
            if a is None or (model in NEW_GPT6 and software_n < MIN_SAMPLES):
                continue
            use_visual = b is not None and (model not in NEW_GPT6 or visual_n >= MIN_SAMPLES)
            if not use_visual and model not in NEW_GPT6:
                continue
            chosen = [a, b] if use_visual else [a]
            def weighted(field):
                measured = [c for c in chosen if c[field] is not None]
                if model not in NEW_GPT6 and len(measured) != len(chosen):
                    return None
                weight = sum(c["weight"] for c in measured)
                if not math.isfinite(weight):
                    raise ValueError("Radar sample weights exceed the numeric range")
                return sum(c[field] * (c["weight"] / weight) for c in measured) if weight else None
            views["comprehensive"]["points"].append({**meta,
                **{field: weighted(field) for field in ("iq", "average_price_usd", "average_minutes")},
                "software_iq": a["iq"], "visual_iq": b["iq"] if use_visual else None,
                "visual_included": use_visual, "score_basis": "comprehensive" if use_visual else "software",
                "price_aggregation": "weighted"})
    if not samples:
        raise ValueError("No Radar configurations have usable benchmark scores")
    for mode, view in views.items():
        normalize_costs(view["points"])
        view["source_updated_at"] = (software_at if mode == "software" else visual_at if mode == "visual"
                                     else min(software_at, visual_at)).isoformat()
    return {"source_url": SOURCE_URL, "source_updated_at": min(software_at, visual_at).isoformat(),
            "software_updated_at": software_at.isoformat(), "visual_updated_at": visual_at.isoformat(),
            "points": views["comprehensive"]["points"], "views": views, "samples": samples}


def validate_snapshot(snapshot: Any, *, legacy: bool = False) -> bool:
    try:
        source_time(snapshot["source_updated_at"])
        views = {"comprehensive": {"points": snapshot["points"]}} if legacy else snapshot["views"]
        if not isinstance(views, dict) or (not legacy and set(views) != {"comprehensive", "software", "visual"}):
            return False
        count = 0
        for view in views.values():
            points = view["points"]
            if not isinstance(points, list) or len(points) > len(MODEL_NAMES) * len(EFFORTS):
                return False
            count += len(points)
            seen = set()
            for point in points:
                key = (point["model"], point["effort"])
                if key[0] not in MODEL_NAMES or key[1] not in MODEL_EFFORTS[key[0]] or key in seen:
                    return False
                seen.add(key)
                iq = finite_number(point.get("iq"))
                if iq is None or not 0 <= iq <= 150:
                    return False
                for field in ("average_price_usd", "average_minutes", "combined_cost_index"):
                    # Null is a supported missing measurement; an absent field
                    # is a malformed cache and cannot be normalized safely.
                    if field not in point:
                        return False
                    value = point.get(field)
                    if value is not None:
                        number = finite_number(value)
                        if number is None or number < 0 or (field == "combined_cost_index" and number > 100.000001):
                            return False
        if legacy:
            return count > 0
        if snapshot["points"] != views["comprehensive"]["points"]:
            return False
        samples = snapshot["samples"]
        if not isinstance(samples, list) or not 0 < len(samples) <= len(MODEL_NAMES) * len(EFFORTS):
            return False
        identities = set()
        for row in samples:
            key = (row["model"], row["effort"])
            if key[0] not in MODEL_NAMES or key[1] not in MODEL_EFFORTS[key[0]] or key in identities:
                return False
            identities.add(key)
            for field in ("software_samples", "visual_samples"):
                value = finite_number(row.get(field))
                if value is None or value < 0:
                    return False
        for view in views.values():
            source_time(view["source_updated_at"])
            if any((point["model"], point["effort"]) not in identities for point in view["points"]):
                return False
        json.dumps(snapshot, allow_nan=False)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def atomic_write(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


class RadarService:
    """A nonblocking cache reader with one bounded, server-owned refresh worker."""

    def __init__(self, cache_path: Path = DEFAULT_CACHE_PATH, *,
                 fetcher: Callable[[str], dict[str, Any]] = fetch_json,
                 clock: Callable[[], float] = time.time) -> None:
        self.cache_path = Path(cache_path)
        self._fetcher = fetcher
        self._clock = clock
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop = threading.Event()
        self._enabled = threading.Event()
        self._enabled.set()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._refreshing = False
        self._state: dict[str, Any] = {}
        now = self._clock()
        try:
            read_path = self.cache_path
            if read_path == DEFAULT_CACHE_PATH and not read_path.exists():
                read_path = LEGACY_CACHE_PATH
            state = json.loads(read_path.read_text(encoding="utf-8"))
            # json.loads accepts NaN/Infinity by default, but the atomic writer
            # correctly rejects them. Reject corrupt metadata here as well, so
            # retaining a failed attempt cannot crash the background worker.
            json.dumps(state, allow_nan=False)
            if isinstance(state, dict) and state.get("schema_version") in (1, 2, CACHE_VERSION):
                snapshot = state.get("snapshot")
                fetched = finite_number(state.get("fetched_at_epoch"))
                if snapshot is None or (validate_snapshot(snapshot, legacy=state["schema_version"] == 1 or state.get("legacy_snapshot") is True) and fetched is not None and 0 < fetched <= now + 60):
                    self._state = state
                    if snapshot is not None and (state["schema_version"] == 1 or state.get("legacy_snapshot") is True):
                        normalize_costs(snapshot["points"])
                    if snapshot is None:
                        self._state.pop("fetched_at_epoch", None)
        except (OSError, ValueError):
            pass
        if self._state.get("schema_version") in (1, 2):
            self._state["next_attempt_at_epoch"] = now
            self._state["last_error"] = "Updating the Radar snapshot to the current model catalog and benchmark rules."
        # An invalid timestamp must never postpone initial recovery indefinitely.
        next_at = finite_number(self._state.get("next_attempt_at_epoch"))
        if next_at is None or not 0 < next_at <= now + REFRESH_SECONDS:
            self._state["next_attempt_at_epoch"] = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = copy.deepcopy(self._state)
            refreshing = self._refreshing
        now = self._clock()
        fetched = finite_number(state.get("fetched_at_epoch"))
        data = state.get("snapshot")
        age = max(0, now - fetched) if fetched is not None else None
        return {
            "available": data is not None,
            "refreshing": refreshing,
            "stale": data is not None and (age is None or age >= REFRESH_SECONDS or bool(state.get("last_error"))),
            "age_seconds": int(age) if age is not None else None,
            "fetched_at": iso_time(fetched) if fetched is not None else None,
            "next_attempt_at": iso_time(state.get("next_attempt_at_epoch", now)),
            "refresh_seconds": REFRESH_SECONDS,
            "last_error": state.get("last_error"),
            "cache_warning": state.get("cache_warning"),
            "data": data,
        }

    def refresh_if_due(self, *, force: bool = False) -> bool:
        if not self._enabled.is_set():
            return False
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            now = self._clock()
            with self._lock:
                if not force and now < self._state.get("next_attempt_at_epoch", 0):
                    return False
                previous = copy.deepcopy(self._state)
                self._refreshing = True
            try:
                software = self._fetcher(METRICS_URL)
                visual = self._fetcher(VISUAL_URL)
                coverage, coverage_warning = {}, None
                try:
                    coverage = coverage_points(self._fetcher(COVERAGE_URL))
                except Exception:
                    coverage_warning = "Independent software task coverage is unavailable."
                data = combine_snapshots(software, visual, coverage)
                data["coverage_warning"] = coverage_warning
                if not validate_snapshot(data):
                    raise ValueError("Invalid composite Radar snapshot")
                finished = self._clock()
                state = {"snapshot": data, "fetched_at_epoch": finished,
                         "failures": 0, "next_attempt_at_epoch": finished + REFRESH_SECONDS}
            except Exception as exc:
                old_failures = finite_number(previous.get("failures")) or 0
                failures = max(0, min(int(old_failures), 4)) + 1
                delay = min(REFRESH_SECONDS, RETRY_SECONDS * 2 ** (failures - 1))
                state = {**previous, "failures": failures,
                         "last_error": f"{type(exc).__name__}: {exc}"[:300],
                         "next_attempt_at_epoch": self._clock() + delay}
            if state.get("snapshot") is not None and "views" not in state["snapshot"]:
                state["legacy_snapshot"] = True
            state.update(schema_version=CACHE_VERSION, last_attempt_at_epoch=now)
            state.pop("cache_warning", None)
            try:
                atomic_write(self.cache_path, state)
            except OSError:
                state["cache_warning"] = "Could not save the Radar cache to disk."
            with self._lock:
                self._state = state
            return not bool(state.get("last_error"))
        finally:
            with self._lock:
                self._refreshing = False
            self._refresh_lock.release()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="codex-radar-refresh", daemon=True)
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            self.refresh_if_due()
            with self._lock:
                remaining = self._state.get("next_attempt_at_epoch", 0) - self._clock()
            # Recheck wall-clock deadlines after waking from system sleep.
            self._wake.wait(min(60, max(0.1, remaining)) if self._enabled.is_set() else 60)

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


STYLE = asset_text("static/radar.css")

SCRIPT = asset_text("static/radar.js")


# Keep renderer grouping, supported efforts and eligibility aligned with collection.
SCRIPT = (SCRIPT.replace("__RADAR_GENERATIONS__", json.dumps(MODEL_GROUPS))
          .replace("__RADAR_MODEL_EFFORTS__", json.dumps(MODEL_EFFORTS))
          .replace("__RADAR_THRESHOLD_MODELS__", json.dumps(sorted(NEW_GPT6))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--force", action="store_true", help="Refresh even if the four-hour cache is still fresh.")
    args = parser.parse_args()
    service = RadarService(args.cache)
    service.refresh_if_due(force=args.force)
    result = service.snapshot()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(1 if result["last_error"] else 0)


if __name__ == "__main__":
    main()
