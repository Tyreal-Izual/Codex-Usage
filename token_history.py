"""Local token-event accounting, adapted from PulseDeck (MIT).

Keep only usage metadata. Direct response usage and legacy cumulative counters
are reconciled before grouping by the event's local calendar day.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import math

CODEX_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens")
UNKNOWN = "(unknown)"


def timestamp(value):
    try:
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(value):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, OSError, OverflowError):
        pass
    return None


def counts(value):
    if not isinstance(value, dict):
        return None
    result = {k: int(v) for k, v in value.items() if k in CODEX_FIELDS
              and isinstance(v, (int, float)) and not isinstance(v, bool)
              and 0 <= v <= 2**53 - 1 and math.isfinite(v) and int(v) == v}
    if "total_tokens" not in result and "input_tokens" in result and "output_tokens" in result:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result if "total_tokens" in result else None


def signature(usage):
    return tuple(sorted((usage or {}).items()))


def merge_usage_records(first, second):
    """Keep the fullest counters without erasing known attribution metadata."""
    best, other = (first, second) if first["usage"]["total_tokens"] > second["usage"]["total_tokens"] else (second, first)
    times = [row["timestamp"] for row in (first, second) if row["timestamp"] is not None]
    return {**best, "timestamp": min(times) if times else None,
            "model": best["model"] if best["model"] != UNKNOWN else other["model"],
            "project": best["project"] or other["project"]}


class CodexParser:
    def __init__(self, path):
        self.path = path
        self.session = path.stem
        self.turn = None
        self.model = UNKNOWN
        self.project = None
        self.provider = None
        self.points = []
        self.endpoints = {}
        self.responses = {}
        self.duplicates = 0
        self.latest_cumulative = None

    def consume(self, obj):
        if not isinstance(obj, dict):
            return
        kind = obj.get("type")
        if kind is not None and not isinstance(kind, str):
            return
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
        subtype = payload.get("type")
        if subtype is not None and not isinstance(subtype, str):
            return
        if kind == "compacted":
            self.endpoints.clear()
            return
        if kind == "session_meta":
            self.session = str(payload.get("id") or payload.get("thread_id") or self.session)
        if kind in {"session_meta", "turn_context"} or subtype in {"task_started", "thread_settings_applied"} or kind is None:
            turn = payload.get("turn_id")
            if turn and turn != self.turn:
                self.turn, self.model = str(turn), UNKNOWN
            if isinstance(payload.get("model"), str):
                self.model = payload["model"] or UNKNOWN
            if isinstance(payload.get("cwd"), str):
                self.project = payload["cwd"]
            if isinstance(payload.get("model_provider"), str):
                self.provider = payload["model_provider"]

        direct = kind == "token_usage_record"
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        if not direct and subtype != "token_count" and not (kind is None and info):
            return
        cumulative = counts(payload.get("thread_token_usage") if direct else info.get("total_token_usage"))
        actual = counts(payload.get("usage")) if direct else None
        last = counts(info.get("last_token_usage")) if not direct else None
        if cumulative is None and actual is None:
            return
        if cumulative and not direct:
            if self.latest_cumulative is not None and cumulative["total_tokens"] < self.latest_cumulative:
                self.endpoints.clear()
            self.latest_cumulative = cumulative["total_tokens"]
        turn = str(payload.get("turn_id") or self.turn or "")
        model = payload.get("model") or (self.model if not self.turn or turn == self.turn else UNKNOWN)
        response = str(payload.get("response_id") or "") if direct else ""
        endpoint = (direct, turn, signature(cumulative)) if cumulative is not None else None
        index = self.responses.get(response) if response else None
        if index is None and endpoint is not None:
            index = self.endpoints.get(endpoint)
            if direct and index is not None and self.points[index].get("response") not in ("", response):
                index = None
        point = {"cumulative": cumulative, "actual": actual, "last": last,
                 "timestamp": timestamp(obj.get("timestamp") or payload.get("timestamp")),
                 "turn": turn, "model": str(model or UNKNOWN), "project": self.project,
                 "session": str(payload.get("thread_id") or self.session), "response": response,
                 "file": str(self.path)}
        if index is not None:
            old = self.points[index]
            times = [value for value in (old["timestamp"], point["timestamp"]) if value is not None]
            self.duplicates += 1
            # Direct per-response evidence supersedes its duplicate cumulative display event.
            if actual and (not old["actual"] or actual["total_tokens"] >= old["actual"]["total_tokens"]):
                if old["timestamp"] and point["timestamp"]:
                    point["timestamp"] = min(old["timestamp"], point["timestamp"])
                if point["model"] == UNKNOWN:
                    point["model"] = old["model"]
                self.points[index] = point
            elif old["actual"] is None and old["last"] is None and last:
                old["last"] = last
            self.points[index]["timestamp"] = min(times) if times else None
            if response:
                self.responses[response] = index
            if endpoint is not None:
                self.endpoints[endpoint] = index
            return
        index = len(self.points)
        self.points.append(point)
        if endpoint is not None:
            self.endpoints[endpoint] = index
        if response:
            self.responses[response] = index

    def records(self):
        # thread_token_usage can restart with the process while token_count keeps
        # historical totals. Never subtract counters belonging to these streams.
        direct_by_usage, direct_by_counter = defaultdict(list), defaultdict(list)
        for i, point in enumerate(self.points):
            if point["actual"] is not None:
                normalized = tuple(point["actual"].get(k, 0) for k in CODEX_FIELDS)
                direct_by_usage[(point["turn"], normalized)].append(i)
                if point["cumulative"]:
                    direct_by_counter[(point["turn"], signature(point["cumulative"]))].append(i)
        pairs, paired = {}, set()
        for i, point in enumerate(self.points):
            if point["actual"] is not None:
                continue
            candidates = direct_by_usage.get((point["turn"], tuple((point["last"] or {}).get(k, 0) for k in CODEX_FIELDS)), [])
            if not candidates:
                candidates = direct_by_counter.get((point["turn"], signature(point["cumulative"])), [])
            available = [j for j in candidates if j not in paired]
            if available:
                match = min(available, key=lambda j: abs(j - i))
                pairs[i] = match
                paired.add(match)
        self.paired_duplicates = len(pairs)
        covered_ahead = {j for i, j in pairs.items() if j > i}
        previous, epoch, resets = None, 0, 0
        direct_since_snapshot = Counter()
        output = []
        for i, point in enumerate(self.points):
            cumulative, actual, last = point["cumulative"], point["actual"], point["last"]
            if actual is not None:
                usage = {k: actual.get(k, 0) for k in CODEX_FIELDS}
                if i not in covered_ahead:
                    direct_since_snapshot.update(usage)
                key = ("response:" + point["response"] if point["response"] else
                       "direct:" + (point["turn"] or point["session"]) + ":" + repr(signature(cumulative or actual)))
                output.append({**point, "key": key, "usage": usage, "basis": "request"})
                continue
            if cumulative is None:
                continue
            had_previous = previous is not None
            reset = bool(previous and cumulative["total_tokens"] < previous["total_tokens"])
            if reset:
                epoch += 1
                resets += 1
            baseline = {} if previous is None or reset else previous
            match = pairs.get(i)
            if match is not None and match > i:
                direct_since_snapshot.update(self.points[match]["actual"])
            delta = {k: max(0, cumulative.get(k, baseline.get(k, 0)) - baseline.get(k, 0)
                            - direct_since_snapshot.get(k, 0)) for k in CODEX_FIELDS}
            previous = cumulative
            direct_since_snapshot.clear()
            if not delta["total_tokens"]:
                continue
            identity = "counter:" + (point["turn"] or point["session"]) + ":" + str(epoch) + ":" + repr(signature(cumulative))
            if match is None and last is not None:
                usage = {k: min(last.get(k, 0), delta[k]) for k in CODEX_FIELDS}
            elif match is None and had_previous and not reset:
                usage = delta
            else:
                usage = {}
            if usage.get("total_tokens", 0):
                output.append({**point, "key": identity, "usage": usage, "basis": "cumulative_delta"})
            gap = {k: max(0, delta[k] - usage.get(k, 0)) for k in CODEX_FIELDS}
            if gap["total_tokens"]:
                output.append({**point, "key": identity + ":unattributed", "usage": gap,
                               "timestamp": None, "model": UNKNOWN, "project": None, "basis": "unattributed_baseline"})
        return output, resets


def daily_history(records):
    """Aggregate already deduplicated records; unknown dates never become today."""
    days = {}
    unknown = 0
    for record in records:
        when = timestamp(record.get("timestamp"))
        usage = record["usage"]
        if when is None:
            unknown += usage.get("total_tokens", 0)
            continue
        day = when.astimezone().date().isoformat()
        row = days.setdefault(day, {"usage": Counter(), "sessions": set(), "requests": 0})
        row["usage"].update(usage)
        row["sessions"].add(record.get("session") or record.get("session_file"))
        row["requests"] += 1
    return {
        "days": [{"date": day, **dict(row["usage"]),
                  "sessions": len(row["sessions"]), "requests": row["requests"]}
                 for day, row in sorted(days.items())],
        "unknown_date_tokens": unknown,
    }

