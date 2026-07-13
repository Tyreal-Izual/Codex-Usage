#!/usr/bin/env python3
"""Read local Claude Code usage without modifying Claude Code data.

The collector has two independent sources:

* ``~/.claude/projects/**/*.jsonl`` for per-request token counters.
* A small rate-limit snapshot written by ``claude_usage_statusline.py``.

Only metadata and usage counters are returned. Prompt text, assistant content,
tool inputs, file contents, credentials, and transcript bodies are ignored.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
TOTAL_FIELD = "total_tokens"
DEFAULT_STALE_SECONDS = 15 * 60


def resolve_claude_home() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude"


CLAUDE_HOME = resolve_claude_home()


def resolve_snapshot_path(claude_home: Path | None = None) -> Path:
    configured = os.environ.get("CLAUDE_USAGE_SNAPSHOT")
    if configured:
        return Path(configured).expanduser()
    return (claude_home or CLAUDE_HOME) / "usage-dashboard.json"


def local_now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z %z")


def iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_timestamp_text(value: Any) -> str | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z %z")


def local_date(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.astimezone().strftime("%Y-%m-%d")


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def nonnegative_int(value: Any) -> int:
    number = finite_number(value)
    if number is None:
        return 0
    return max(0, int(number))


def short_path(value: str | None, max_chars: int = 64) -> str:
    if not value:
        return "-"
    text = str(value).replace(str(Path.home()), "~", 1)
    if len(text) <= max_chars:
        return text
    parts = Path(text).parts
    if len(parts) >= 3:
        text = f"{parts[0]}/…/{parts[-1]}"
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def token_usage(usage: dict[str, Any]) -> dict[str, int]:
    out = {field: nonnegative_int(usage.get(field)) for field in TOKEN_FIELDS}
    out[TOTAL_FIELD] = sum(out.values())
    return out


def usage_key(
    obj: dict[str, Any],
    message: dict[str, Any],
    usage: dict[str, int],
    file_path: Path,
) -> str:
    message_id = str(message.get("id") or "").strip()
    request_id = str(obj.get("requestId") or "").strip()
    if message_id or request_id:
        return f"message={message_id}|request={request_id}"

    # Older or provider-specific records can omit both identifiers. This
    # fallback still collapses repeated streaming records in the same file.
    signature = [
        str(obj.get("sessionId") or file_path.stem),
        str(obj.get("timestamp") or ""),
        str(message.get("model") or "unknown"),
        *(str(usage[field]) for field in (*TOKEN_FIELDS, TOTAL_FIELD)),
    ]
    return "fallback=" + "|".join(signature)


def scan_file(file_path: Path, claude_home: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines_seen = 0
    parse_errors = 0
    usage_rows_seen = 0
    duplicate_rows = 0

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines_seen += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "assistant":
                    continue
                message = obj.get("message")
                if not isinstance(message, dict):
                    continue
                raw_usage = message.get("usage")
                if not isinstance(raw_usage, dict):
                    continue

                usage = token_usage(raw_usage)
                usage_rows_seen += 1
                if usage[TOTAL_FIELD] <= 0:
                    continue
                key = usage_key(obj, message, usage, file_path)
                if key in seen:
                    duplicate_rows += 1
                    continue
                seen.add(key)

                timestamp = obj.get("timestamp")
                cwd = obj.get("cwd") if isinstance(obj.get("cwd"), str) else None
                records.append(
                    {
                        "key": key,
                        "timestamp": timestamp,
                        "date": local_date(timestamp),
                        "model": str(message.get("model") or "unknown"),
                        "project": short_path(cwd),
                        "session_id": str(obj.get("sessionId") or file_path.stem),
                        "session_file": str(file_path.relative_to(claude_home)),
                        "usage": usage,
                    }
                )
    except OSError:
        parse_errors += 1

    return {
        "records": records,
        "lines_seen": lines_seen,
        "parse_errors": parse_errors,
        "usage_rows_seen": usage_rows_seen,
        "duplicate_rows": duplicate_rows,
    }


_FILE_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def cached_file_scan(file_path: Path, claude_home: Path) -> dict[str, Any]:
    try:
        stat = file_path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {
            "records": [],
            "lines_seen": 0,
            "parse_errors": 1,
            "usage_rows_seen": 0,
            "duplicate_rows": 0,
        }

    cache_key = str(file_path)
    cached = _FILE_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1]
    result = scan_file(file_path, claude_home)
    _FILE_CACHE[cache_key] = (signature, result)
    return result


def add_usage(target: Counter[str], usage: dict[str, int]) -> None:
    for field in (*TOKEN_FIELDS, TOTAL_FIELD):
        target[field] += int(usage.get(field) or 0)


def counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {field: int(counter.get(field, 0)) for field in (*TOKEN_FIELDS, TOTAL_FIELD)}


def aggregate_local_usage(claude_home: Path, top_n: int, days: int) -> dict[str, Any]:
    projects_dir = claude_home / "projects"
    files = sorted(projects_dir.rglob("*.jsonl")) if projects_dir.exists() else []

    totals: Counter[str] = Counter()
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    daily_sessions: dict[str, set[str]] = defaultdict(set)
    model_totals: dict[str, Counter[str]] = defaultdict(Counter)
    model_requests: Counter[str] = Counter()
    project_totals: dict[str, Counter[str]] = defaultdict(Counter)
    project_requests: Counter[str] = Counter()
    session_totals: dict[str, Counter[str]] = defaultdict(Counter)
    session_meta: dict[str, dict[str, Any]] = {}

    lines_seen = 0
    parse_errors = 0
    usage_rows_seen = 0
    duplicate_rows = 0
    unique_records = 0
    globally_seen: set[str] = set()

    with _CACHE_LOCK:
        live_paths = {str(path) for path in files}
        for stale_path in set(_FILE_CACHE) - live_paths:
            _FILE_CACHE.pop(stale_path, None)

        for file_path in files:
            scanned = cached_file_scan(file_path, claude_home)
            lines_seen += int(scanned["lines_seen"])
            parse_errors += int(scanned["parse_errors"])
            usage_rows_seen += int(scanned["usage_rows_seen"])
            duplicate_rows += int(scanned["duplicate_rows"])

            for record in scanned["records"]:
                key = record["key"]
                if key in globally_seen:
                    duplicate_rows += 1
                    continue
                globally_seen.add(key)
                unique_records += 1

                usage = record["usage"]
                day = record["date"]
                model = record["model"]
                project = record["project"]
                session_file = record["session_file"]

                add_usage(totals, usage)
                add_usage(daily[day], usage)
                daily[day]["requests"] += 1
                daily_sessions[day].add(session_file)
                add_usage(model_totals[model], usage)
                model_requests[model] += 1
                add_usage(project_totals[project], usage)
                project_requests[project] += 1
                add_usage(session_totals[session_file], usage)
                session_totals[session_file]["requests"] += 1

                meta = session_meta.setdefault(
                    session_file,
                    {
                        "date": day,
                        "timestamp": record.get("timestamp"),
                        "models": set(),
                        "project": project,
                        "session_id": record["session_id"],
                    },
                )
                meta["models"].add(model)
                if str(record.get("timestamp") or "") > str(meta.get("timestamp") or ""):
                    meta["timestamp"] = record.get("timestamp")
                    meta["date"] = day
                    meta["project"] = project

    daily_rows: list[dict[str, Any]] = []
    for day in sorted(daily):
        row: dict[str, Any] = {
            "date": day,
            "sessions": len(daily_sessions[day]),
            "requests": int(daily[day].get("requests", 0)),
        }
        row.update(counter_dict(daily[day]))
        daily_rows.append(row)
    if days > 0:
        daily_rows = daily_rows[-days:]

    by_model = []
    for model, counter in sorted(
        model_totals.items(), key=lambda item: item[1].get(TOTAL_FIELD, 0), reverse=True
    ):
        row = {"model": model, "requests": int(model_requests[model])}
        row.update(counter_dict(counter))
        by_model.append(row)

    by_project = []
    for project, counter in sorted(
        project_totals.items(), key=lambda item: item[1].get(TOTAL_FIELD, 0), reverse=True
    ):
        row = {"project": project, "requests": int(project_requests[project])}
        row.update(counter_dict(counter))
        by_project.append(row)

    top_sessions = []
    for session_file, counter in sorted(
        session_totals.items(), key=lambda item: item[1].get(TOTAL_FIELD, 0), reverse=True
    )[:top_n]:
        meta = session_meta[session_file]
        top_sessions.append(
            {
                "date": meta["date"],
                "models": sorted(meta["models"]),
                "project": meta["project"],
                "session_id": meta["session_id"],
                "session_file": session_file,
                "requests": int(counter.get("requests", 0)),
                "usage": counter_dict(counter),
            }
        )

    return {
        "available": projects_dir.exists(),
        "projects_dir": str(projects_dir),
        "session_files": len(files),
        "jsonl_lines_scanned": lines_seen,
        "parse_or_read_errors": parse_errors,
        "usage_rows_seen": usage_rows_seen,
        "unique_usage_records": unique_records,
        "duplicate_usage_records_skipped": duplicate_rows,
        "token_totals": counter_dict(totals),
        "daily_usage": daily_rows,
        "by_model": by_model[:top_n],
        "by_project": by_project[:top_n],
        "top_sessions": top_sessions,
    }


def stale_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CLAUDE_USAGE_STALE_SECONDS", DEFAULT_STALE_SECONDS)))
    except ValueError:
        return DEFAULT_STALE_SECONDS


def statusline_script_path() -> Path:
    return Path(__file__).resolve().with_name("claude_usage_statusline.py")


def statusline_install_command() -> str:
    return " ".join(
        [shlex.quote(sys.executable), shlex.quote(str(statusline_script_path())), "--install"]
    )


def statusline_is_installed(claude_home: Path) -> bool:
    settings_path = claude_home / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    status_line = settings.get("statusLine") if isinstance(settings, dict) else None
    if not isinstance(status_line, dict):
        return False
    command = str(status_line.get("command") or "")
    return str(statusline_script_path()) in command


def normalise_window(value: Any, now_epoch: float) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    used = finite_number(value.get("used_percentage"))
    resets_at = finite_number(value.get("resets_at"))
    if used is None and resets_at is None:
        return None
    out: dict[str, Any] = {}
    if used is not None:
        used = max(0.0, min(100.0, used))
        out["used_percentage"] = used
        out["remaining_percentage"] = 100.0 - used
    if resets_at is not None:
        out["resets_at"] = int(resets_at)
        out["reset_after_seconds"] = max(0, int(resets_at - now_epoch))
        out["resets_at_local"] = local_timestamp_text(resets_at)
    return out


def collect_rate_limits(claude_home: Path, snapshot_path: Path) -> dict[str, Any]:
    installed = statusline_is_installed(claude_home)
    base: dict[str, Any] = {
        "available": False,
        "capture_installed": installed,
        "snapshot_path": str(snapshot_path),
        "install_command": statusline_install_command(),
        "stale_after_seconds": stale_seconds(),
    }
    if not snapshot_path.exists():
        base["reason"] = "snapshot_not_found"
        return base
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base["reason"] = "snapshot_invalid"
        base["error"] = f"{type(exc).__name__}: {exc}"
        return base
    if not isinstance(snapshot, dict):
        base["reason"] = "snapshot_invalid"
        return base

    now_epoch = datetime.now(timezone.utc).timestamp()
    captured_epoch = finite_number(snapshot.get("captured_at_epoch"))
    if captured_epoch is None:
        parsed = parse_timestamp(snapshot.get("captured_at"))
        captured_epoch = parsed.timestamp() if parsed is not None else None
    age = max(0, int(now_epoch - captured_epoch)) if captured_epoch is not None else None
    rate_limits = snapshot.get("rate_limits")
    rate_limits = rate_limits if isinstance(rate_limits, dict) else {}
    five_hour = normalise_window(rate_limits.get("five_hour"), now_epoch)
    seven_day = normalise_window(rate_limits.get("seven_day"), now_epoch)

    base.update(
        {
            "available": bool(five_hour or seven_day),
            "captured_at": snapshot.get("captured_at"),
            "captured_at_local": local_timestamp_text(snapshot.get("captured_at")),
            "age_seconds": age,
            "stale": age is None or age > base["stale_after_seconds"],
            "claude_version": snapshot.get("claude_version"),
            "model": snapshot.get("model") if isinstance(snapshot.get("model"), dict) else {},
            "five_hour": five_hour,
            "seven_day": seven_day,
        }
    )
    plan_value = snapshot.get("plan_type") or snapshot.get("plan")
    if not plan_value:
        plan_value = rate_limits.get("plan_type") or rate_limits.get("plan")
    if isinstance(plan_value, str) and plan_value.strip():
        base["plan_type"] = plan_value.strip()
    limit_reached = snapshot.get("limit_reached")
    if not isinstance(limit_reached, bool):
        limit_reached = rate_limits.get("limit_reached")
    if isinstance(limit_reached, bool):
        base["limit_reached"] = limit_reached
    if not base["available"]:
        base["reason"] = "rate_limits_missing"
    return base


def collect_usage(
    claude_home: Path | None = None,
    top_n: int = 10,
    days: int = 30,
    snapshot_path: Path | None = None,
) -> dict[str, Any]:
    home = (claude_home or CLAUDE_HOME).expanduser()
    snapshot = (snapshot_path or resolve_snapshot_path(home)).expanduser()
    return {
        "ok": True,
        "retrieved_at_local": local_now_text(),
        "claude_home": str(home),
        "network_calls_made": 0,
        "privacy_note": "Usage metadata only; prompts, responses, tool inputs, and transcript content are ignored.",
        "rate_limits": collect_rate_limits(home, snapshot),
        "local_usage": aggregate_local_usage(home, top_n=max(1, top_n), days=max(1, days)),
    }


def print_human(data: dict[str, Any]) -> None:
    rate = data["rate_limits"]
    local = data["local_usage"]
    totals = local["token_totals"]
    print("Claude Code Usage")
    print("=================")
    print(f"Retrieved: {data['retrieved_at_local']}")
    print(f"Claude home: {data['claude_home']}")
    print(f"Session files: {local['session_files']:,}")
    print(f"Unique requests: {local['unique_usage_records']:,}")
    print(f"Duplicate usage rows skipped: {local['duplicate_usage_records_skipped']:,}")
    print(f"Total tokens: {totals[TOTAL_FIELD]:,}")
    for label, key in (("5-hour", "five_hour"), ("7-day", "seven_day")):
        window = rate.get(key)
        if isinstance(window, dict) and window.get("used_percentage") is not None:
            print(
                f"{label} limit: {window['used_percentage']:.1f}% used, "
                f"{window['remaining_percentage']:.1f}% remaining"
            )
        else:
            print(f"{label} limit: unavailable")
    if not rate.get("capture_installed"):
        print(f"Install rate-limit capture: {rate['install_command']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read local Claude Code token and rate-limit usage.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a short summary.")
    parser.add_argument("--top", type=int, default=10, help="Number of ranked rows to return.")
    parser.add_argument("--days", type=int, default=30, help="Number of daily rows to return.")
    parser.add_argument("--claude-home", type=Path, default=CLAUDE_HOME)
    parser.add_argument("--snapshot", type=Path, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data = collect_usage(
        claude_home=args.claude_home,
        top_n=max(1, args.top),
        days=max(1, args.days),
        snapshot_path=args.snapshot,
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_human(data)


if __name__ == "__main__":
    main()
