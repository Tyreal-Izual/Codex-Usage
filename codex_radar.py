#!/usr/bin/env python3
"""Codex Radar collector, four-hour cache worker, and standalone dashboard widget.

Only public benchmark metadata is requested. No account or transcript data is
sent. The composite calculation follows https://codexradar.com/ (2026-09-07).
Run this file directly to update the cache once; the web server owns the worker.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import ssl
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

SOURCE_URL = "https://codexradar.com/"
METRICS_URL = SOURCE_URL + "api/intelligence-efficiency-metrics"
VISUAL_URL = SOURCE_URL + "api/visual-spatial-reasoning"
REFRESH_SECONDS = 4 * 60 * 60
RETRY_SECONDS = 15 * 60
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_CACHE_PATH = Path(__file__).resolve().with_name("codex_radar_snapshot.json")
MODEL_NAMES = {
    "gpt-6-astra": "Astra",
    "gpt-5.6-sol": "Sol",
    "gpt-5.6-terra": "Terra",
    "gpt-5.6-luna": "Luna",
    "gpt-5.5": "5.5",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
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


def ssl_context() -> ssl.SSLContext:
    configured = os.environ.get("SSL_CERT_FILE")
    if configured:
        return ssl.create_default_context(cafile=configured)
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                   "/etc/pki/tls/certs/ca-bundle.crt"):
        if Path(bundle).is_file():
            return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={
        "User-Agent": "Codex-Usage-Dashboard/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=20, context=ssl_context()) as response:
        cache_status = response.headers.get("X-Codex-Cache", "")
        if not cache_status or cache_status.startswith("STALE") or cache_status == "ERROR":
            raise ValueError("Radar upstream is not serving a current snapshot")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Radar response exceeds the size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Radar response must be a JSON object")
    return value


def component_points(payload: dict[str, Any], *, software: bool) -> dict[tuple[str, str], dict[str, float]]:
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
        if model not in MODEL_NAMES or effort not in EFFORTS:
            continue
        fields = {key: finite_number(row.get(key)) for key in
                  ("iq", "average_price_usd", "average_minutes", weight_field)}
        # A configuration without all three measured metrics cannot be plotted.
        if any(row.get(key) is None for key in fields):
            continue
        if any(value is None for value in fields.values()):
            raise ValueError("Non-finite Radar metric")
        if not 0 <= fields["iq"] <= 150 or any(fields[key] < 0 for key in fields if key != "iq"):
            raise ValueError("Radar metric outside its valid range")
        if fields[weight_field] == 0:
            continue
        key = (model, effort)
        if key in out:
            raise ValueError("Duplicate Radar model/effort")
        out[key] = {**fields, "weight": fields[weight_field]}
    return out


def combine_snapshots(software: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the site's valid-task weighted composite, then normalize costs.

    The API's software combined_cost_index is not the composite chart's x value.
    Cost is proportional to price * (minutes / 10) ** log(2.5)/log(1.35).
    Log-space arithmetic avoids overflow; normalizing the largest to 100 removes
    the common factor. Only configurations present in both sources participate.
    """
    software_at = source_time(software.get("source_updated_at"))
    visual_at = source_time(visual.get("source_updated_at"))
    left = component_points(software, software=True)
    right = component_points(visual, software=False)
    points = []
    log_costs = []
    for model in MODEL_NAMES:
        for effort in EFFORTS:
            a, b = left.get((model, effort)), right.get((model, effort))
            if a is None or b is None:
                continue
            total = a["weight"] + b["weight"]
            point = {"model": model, "effort": effort}
            for field in ("iq", "average_price_usd", "average_minutes"):
                point[field] = a[field] * (a["weight"] / total) + b[field] * (b["weight"] / total)
            # A zero component cost is legitimate when the weighted composite
            # remains positive. Only the final logarithmic coordinates need > 0.
            if point["average_price_usd"] <= 0 or point["average_minutes"] <= 0:
                continue
            point.update(software_iq=a["iq"], visual_iq=b["iq"],
                         software_samples=a["weight"], visual_samples=b["weight"])
            log_costs.append(math.log(point["average_price_usd"]) + COST_WEIGHT * math.log(point["average_minutes"] / 10))
            points.append(point)
    if not points:
        raise ValueError("No Radar configurations have both software and visual metrics")
    largest = max(log_costs)
    for point, cost in zip(points, log_costs):
        point["combined_cost_index"] = math.exp(cost - largest) * 100
        if point["combined_cost_index"] <= 0:
            raise ValueError("Radar cost is too small to plot")
    return {
        "source_url": SOURCE_URL,
        "source_updated_at": min(software_at, visual_at).isoformat(),
        "software_updated_at": software_at.isoformat(),
        "visual_updated_at": visual_at.isoformat(),
        "points": points,
    }


def validate_snapshot(snapshot: Any) -> bool:
    try:
        source_time(snapshot["source_updated_at"])
        points = snapshot["points"]
        if not isinstance(points, list) or not points or len(points) > 30:
            return False
        seen = set()
        for point in points:
            key = (point["model"], point["effort"])
            if key[0] not in MODEL_NAMES or key[1] not in EFFORTS or key in seen:
                return False
            seen.add(key)
            for field in ("iq", "software_iq", "visual_iq", "average_price_usd",
                          "average_minutes", "combined_cost_index"):
                number = finite_number(point.get(field))
                if number is None:
                    return False
                if field.endswith("iq") and not 0 <= number <= 150:
                    return False
                if not field.endswith("iq") and number <= 0:
                    return False
                if field == "combined_cost_index" and number > 100.000001:
                    return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def atomic_write(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
        self._thread: threading.Thread | None = None
        self._refreshing = False
        self._state: dict[str, Any] = {}
        now = self._clock()
        try:
            state = json.loads(self.cache_path.read_text(encoding="utf-8"))
            # json.loads accepts NaN/Infinity by default, but the atomic writer
            # correctly rejects them. Reject corrupt metadata here as well, so
            # retaining a failed attempt cannot crash the background worker.
            json.dumps(state, allow_nan=False)
            if isinstance(state, dict) and state.get("schema_version") == 1:
                snapshot = state.get("snapshot")
                fetched = finite_number(state.get("fetched_at_epoch"))
                if snapshot is None or (validate_snapshot(snapshot) and fetched is not None and 0 < fetched <= now + 60):
                    self._state = state
                    if snapshot is None:
                        self._state.pop("fetched_at_epoch", None)
        except (OSError, ValueError):
            pass
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
                data = combine_snapshots(self._fetcher(METRICS_URL), self._fetcher(VISUAL_URL))
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
            state.update(schema_version=1, last_attempt_at_epoch=now)
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

    def _run(self) -> None:
        while not self._stop.is_set():
            self.refresh_if_due()
            with self._lock:
                remaining = self._state.get("next_attempt_at_epoch", 0) - self._clock()
            # Recheck wall-clock deadlines after waking from system sleep.
            self._stop.wait(min(60, max(0.1, remaining)))

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


STYLE = r"""
    .radar-toolbar, .radar-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
    .radar-toolbar { justify-content: space-between; margin-bottom: 10px; }
    .radar-toolbar label { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
    .radar-toolbar select { min-height: 44px; width: auto; max-width: 100%; }
    .radar-source { color: var(--accent); text-decoration: none; }
    .radar-source:hover { text-decoration: underline; }
    .radar-meta { color: var(--muted); font-size: 12px; margin: 8px 0 12px; }
    .radar-warning { color: var(--warn); margin: 8px 0; }
    .radar-legend { color: var(--ink); font-size: 13px; }
    .radar-legend span { display: inline-flex; align-items: center; gap: 7px; }
    .radar-legend i { width: 18px; height: 3px; border-radius: 2px; }
    .radar-chart svg { display: block; width: 100%; height: auto; overflow: visible; }
    .radar-grid { stroke: var(--line); stroke-dasharray: 3 4; }
    .radar-axis { stroke: var(--muted); fill: none; }
    .radar-tick, .radar-label { fill: var(--muted); font: 12px ui-monospace, monospace; }
    .radar-label { font-size: 11px; paint-order: stroke; stroke: var(--panel); stroke-width: 3px; }
    .radar-point { cursor: pointer; outline: none; }
    .radar-point:focus .radar-hit, .radar-point:hover .radar-hit { stroke: var(--ink); stroke-width: 1.5; }
    .radar-detail { min-height: 44px; padding: 10px 12px; background: var(--field); border-radius: 6px; font-size: 13px; }
    .radar-formula { margin: 10px 0; color: var(--muted); font-size: 12px; }
    .radar-table summary { cursor: pointer; padding: 12px 0; color: var(--accent); }
    .radar-table table { min-width: 520px; }
    .radar-toolbar select:focus-visible, .radar-source:focus-visible, .radar-table summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
    @media (max-width: 600px) { .radar-toolbar { align-items: flex-start; } .radar-meta { line-height: 1.7; } }
"""

SCRIPT = r"""
    const CodexRadar = (() => {
      const models = {
        "gpt-6-astra": ["Astra", "#f97316"], "gpt-5.6-sol": ["Sol", "#eab308"],
        "gpt-5.6-terra": ["Terra", "#60a5fa"], "gpt-5.6-luna": ["Luna", "#c7d2e0"],
        "gpt-5.5": ["5.5", "#00e5ff"]
      };
      const efforts = ["low", "medium", "high", "xhigh", "max", "ultra"];
      const words = {
        en: { title: "Codex Radar", subtitle: "Composite intelligence · Cost × IQ", metric: "Metric",
          combined: "Combined cost × IQ", time: "Time cost × IQ", price: "Price cost × IQ",
          efficient: "Upper-left is more efficient", source: "Source: Codex Radar ↗",
          sync: "Synced", through: "Source data", next: "Next check", cadence: "Sync every 4 hours",
          loading: "Fetching the first benchmark snapshot…", unavailable: "Benchmark data is temporarily unavailable.",
          stale: "Showing the last successful snapshot; the next sync will retry automatically.",
          failed: "Could not read the local Radar cache. Retrying automatically.",
          cache: "The latest data could not be saved to disk.", refreshing: "Syncing…",
          combinedAxis: "Relative combined cost index (log scale)", timeAxis: "Average duration · minutes (log scale)",
          priceAxis: "Average cost · USD (log scale)", table: "View all data", model: "Model", effort: "Effort",
          cost: "Cost index", minutes: "Minutes", usd: "USD", hint: "Hover, tap, or focus a point to inspect its values.",
          formula: "Community benchmark scores. IQ, price and time are weighted across software and visual tasks. Cost ∝ price × (minutes / 10)^3.053; the largest cost is normalized to 100. A // mark indicates a compressed gap on the log axis." },
        zh: { title: "Codex Radar", subtitle: "综合智能 · 成本 × IQ", metric: "切换指标",
          combined: "综合成本 × IQ", time: "时间成本 × IQ", price: "费用成本 × IQ",
          efficient: "越靠左上越高效", source: "来源：Codex Radar ↗",
          sync: "上次同步", through: "源数据截至", next: "下次检查", cadence: "每 4 小时同步",
          loading: "正在获取首次评测快照…", unavailable: "评测数据暂时不可用。",
          stale: "正在显示上次成功的快照；下次同步将自动重试。",
          failed: "暂时无法读取本地 Radar 缓存，将自动重试。",
          cache: "最新数据暂未保存到磁盘。", refreshing: "正在同步…",
          combinedAxis: "相对综合成本指数（对数刻度）", timeAxis: "平均耗时 · 分钟（对数刻度）",
          priceAxis: "平均费用 · USD（对数刻度）", table: "查看完整数据", model: "模型", effort: "推理档位",
          cost: "成本指数", minutes: "分钟", usd: "USD", hint: "悬停、点击或用键盘聚焦数据点查看数值。",
          formula: "社区评测分数。IQ、费用和耗时按软件工程与视觉任务的有效题量加权。综合成本 ∝ 费用 × (分钟 / 10)^3.053，最高成本归一为 100。横轴 // 表示压缩的对数区间。" }
      };
      let root = null, lang = "en", metric = "combined", payload = null;
      let pending = false, checkedAt = 0, timer = null, localError = false, tableOpen = false, signature = "";
      const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
      const t = (key) => words[lang][key];
      const fmt = (v) => Number(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {maximumSignificantDigits: 4});
      const tick = (v) => v >= 10 ? String(Math.round(v)) : v >= 1 ? v.toFixed(1)
        : v >= .01 ? v.toFixed(2) : v >= .0001 ? v.toFixed(4) : v.toExponential(1);
      const date = (v) => v ? new Date(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", timeZoneName:"short"}) : "—";
      const pointText = (p) => `${models[p.model][0]} · ${p.effort} · IQ ${fmt(p.iq)} · ${t("cost")} ${fmt(p.combined_cost_index)} · $${fmt(p.average_price_usd)} · ${fmt(p.average_minutes)} ${t("minutes")}`;
      const shape = (effort, color) => {
        const attrs = `fill="var(--panel)" stroke="${color}" stroke-width="2.5"`;
        if (effort === "low") return `<circle r="5" ${attrs}/>`;
        if (effort === "high") return `<rect x="-5" y="-5" width="10" height="10" rx="1" ${attrs}/>`;
        const counts = {medium:3, xhigh:4, max:6, ultra:10};
        const count = counts[effort], offset = -Math.PI / 2;
        const pts = Array.from({length:count}, (_,i) => {
          const r = effort === "ultra" && i % 2 ? 3 : 6;
          const angle = offset + i * Math.PI * 2 / count;
          return `${(Math.cos(angle)*r).toFixed(2)},${(Math.sin(angle)*r).toFixed(2)}`;
        }).join(" ");
        return `<polygon points="${pts}" ${attrs}/>`;
      };
      function chart(points) {
        const width = Math.max(300, Math.min(1080, root.clientWidth));
        const compact = width < 620, height = compact ? 340 : 440;
        const left = 44, right = 20, top = 26, bottom = 54, pw = width-left-right, ph = height-top-bottom;
        const field = {combined:"combined_cost_index", time:"average_minutes", price:"average_price_usd"}[metric];
        const values = [...new Set(points.map(p => p[field]))].sort((a,b) => a-b);
        const min = values[0], max = values.at(-1), second = values[1];
        const broken = second / min >= 4, gap = compact ? .19 : .14;
        const logShare = (v,a,b) => a === b ? .5 : Math.log(v/a)/Math.log(b/a);
        const x = (v) => left + pw * (broken ? (v < second ? 0 : gap + (1-gap)*logShare(v,second,max)) : logShare(v,min,max));
        const yMax = Math.min(150, Math.max(20, Math.ceil(Math.max(...points.map(p => p.iq))/20)*20));
        const y = (v) => top + ph * (1-v/yMax);
        const tickMin = broken ? second : min;
        const count = compact ? 3 : 5;
        const ticks = min === max ? [min] : (broken ? [min] : []).concat(Array.from({length:count+1}, (_,i) => tickMin * (max/tickMin)**(i/count)));
        let svg = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="${esc(t(metric))}"><title>${esc(t(metric))}</title>`;
        ticks.forEach(v => { svg += `<line class="radar-grid" x1="${x(v)}" y1="${top}" x2="${x(v)}" y2="${height-bottom}"/><text class="radar-tick" text-anchor="middle" x="${x(v)}" y="${height-bottom+22}">${esc(tick(v))}</text>`; });
        for (let i=0; i<=6; i++) {
          const v=yMax*i/6;
          svg += `<line class="radar-grid" x1="${left}" y1="${y(v)}" x2="${width-right}" y2="${y(v)}"/><text class="radar-tick" text-anchor="end" x="${left-9}" y="${y(v)+4}">${Math.round(v)}</text>`;
        }
        svg += `<path class="radar-axis" d="M${left} ${top}V${height-bottom}H${width-right}"/>`;
        if (broken) {
          const bx=left+pw*gap/2, by=height-bottom;
          svg += `<path class="radar-axis" stroke-width="2" d="M${bx-6} ${by+4}l5 -8 M${bx} ${by+4}l5 -8"/>`;
        }
        Object.entries(models).forEach(([model, [name,color]], familyIndex) => {
          const series=points.filter(p => p.model===model).sort((a,b) => efforts.indexOf(a.effort)-efforts.indexOf(b.effort));
          if (!series.length) return;
          svg += `<path d="${series.map((p,i) => `${i?'L':'M'}${x(p[field])},${y(p.iq)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2"/>`;
          series.forEach((p,i) => {
            const index=points.indexOf(p), px=x(p[field]), py=y(p.iq);
            svg += `<g class="radar-point" data-radar-point="${index}" tabindex="0" role="img" aria-label="${esc(pointText(p))}" transform="translate(${px},${py})"><circle class="radar-hit" r="13" fill="transparent"/>${shape(p.effort,color)}</g>`;
            if (!compact) svg += `<text class="radar-label" pointer-events="none" text-anchor="middle" x="${px}" y="${py+((familyIndex+i)%2?20:-12)}">${esc(p.effort)}</text>`;
          });
        });
        return svg + `<text class="radar-tick" text-anchor="middle" x="${left+pw/2}" y="${height-6}">${esc(t(metric+'Axis'))}</text><text class="radar-tick" x="10" y="16">IQ</text></svg>`;
      }
      function render() {
        if (!root?.isConnected) return;
        const key=JSON.stringify([payload,lang,metric,localError,Math.round(root.clientWidth)]);
        if (signature===key) return;
        signature=key;
        const focused=document.activeElement;
        const activePoint=root.contains(focused) ? focused.getAttribute('data-radar-point') : null;
        const activeSelector=root.contains(focused) && focused.matches('[data-radar-metric]');
        const activeSummary=root.contains(focused) && focused.matches('summary');
        const p=payload, data=p?.data, points=data?.points || [];
        const warning=localError ? t("failed") : p?.stale ? t("stale") : p?.cache_warning ? t("cache") : "";
        const meta=p ? `${t("cadence")} · ${t("sync")}: ${date(p.fetched_at)} · ${t("through")}: ${date(data?.source_updated_at)} · ${t("next")}: ${date(p.next_attempt_at)}` : t("cadence");
        root.innerHTML=`<div class="radar-toolbar"><label>${t("metric")}<select aria-label="${t("metric")}" data-radar-metric>${["combined","time","price"].map(k=>`<option value="${k}" ${k===metric?'selected':''}>${t(k)}</option>`).join('')}</select></label><a class="radar-source" href="https://codexradar.com/" target="_blank" rel="noopener noreferrer">${t("source")}</a></div><div class="radar-meta">${esc(meta)}${p?.refreshing?' · '+t("refreshing"):''}</div>${warning?`<p class="radar-warning" role="status">${warning}</p>`:''}`;
        if (!points.length) {
          root.innerHTML+=`<div class="empty" role="status">${p?.last_error || localError ? t("unavailable") : t("loading")}</div>`;
          return;
        }
        root.innerHTML+=`<div class="radar-legend">${Object.entries(models).filter(([m])=>points.some(p=>p.model===m)).map(([, [name,color]])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}<span>${t("efficient")}</span></div><div class="radar-chart">${chart(points)}</div><div class="radar-detail" aria-live="polite">${t("hint")}</div><p class="radar-formula">${t("formula")}</p><details class="radar-table" ${tableOpen?'open':''}><summary>${t("table")} · ${points.length}</summary><div class="table-wrap"><table><thead><tr>${[t("model"),t("effort"),"IQ",t("cost"),t("usd"),t("minutes")].map(v=>`<th>${v}</th>`).join('')}</tr></thead><tbody>${points.map(p=>`<tr>${[models[p.model][0],p.effort,fmt(p.iq),fmt(p.combined_cost_index),fmt(p.average_price_usd),fmt(p.average_minutes)].map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
        root.querySelector("details").addEventListener("toggle", e => {tableOpen=e.target.open;});
        if (activePoint!==null) root.querySelector(`[data-radar-point="${activePoint}"]`)?.focus({preventScroll:true});
        else if (activeSelector) root.querySelector('select').focus({preventScroll:true});
        else if (activeSummary) root.querySelector('summary').focus({preventScroll:true});
      }
      async function poll() {
        if (pending || !root?.isConnected) return;
        pending=true;
        const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),10000);
        try {
          const response=await fetch('/api/codex-radar',{cache:'no-store',signal:controller.signal});
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          payload=await response.json();
          localError=false;
        } catch (_) { localError=true; }
        finally { clearTimeout(timeout); pending=false; checkedAt=Date.now(); render(); schedule(); }
      }
      function schedule() {
        clearTimeout(timer);
        if (root?.isConnected) timer=setTimeout(poll,payload?.available?60000:5000);
      }
      const observer=new ResizeObserver(()=>render());
      return {
        title: (language) => words[language].title,
        subtitle: (language) => words[language].subtitle,
        mount(element, language) {
          lang=language;
          if (root!==element) {
            observer.disconnect(); root=element; signature="";
            if (!root) {clearTimeout(timer); return;}
            observer.observe(root);
            root.addEventListener("change", e=>{
              if (e.target.matches('[data-radar-metric]')) {
                metric=e.target.value; render(); root.querySelector('select').focus();
              }
            });
            const inspect=e=>{
              const marker=e.target.closest('[data-radar-point]');
              if (!marker) return;
              const p=payload?.data?.points[Number(marker.dataset.radarPoint)];
              if (p) root.querySelector('.radar-detail').textContent=pointText(p);
            };
            ['pointerover','focusin','click'].forEach(event=>root.addEventListener(event,inspect));
          }
          render();
          if (Date.now()-checkedAt>5000) poll(); else schedule();
        }
      };
    })();
"""


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
