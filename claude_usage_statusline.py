#!/usr/bin/env python3
"""Capture Claude Code's documented statusLine rate-limit payload.

Run ``python3 claude_usage_statusline.py --install`` once to register this file
as the Claude Code status line. During normal status-line invocations the script
stores only a small, sanitised usage snapshot and prints a compact status line.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def resolve_claude_home() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def snapshot_path() -> Path:
    configured = os.environ.get("CLAUDE_USAGE_SNAPSHOT")
    return Path(configured).expanduser() if configured else resolve_claude_home() / "usage-dashboard.json"


def command_text() -> str:
    return " ".join((shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve()))))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def clean_window(value: Any) -> dict[str, float | int] | None:
    if not isinstance(value, dict):
        return None
    used = finite_number(value.get("used_percentage"))
    resets_at = finite_number(value.get("resets_at"))
    if used is None and resets_at is None:
        return None
    out: dict[str, float | int] = {}
    if used is not None:
        out["used_percentage"] = max(0.0, min(100.0, used))
    if resets_at is not None:
        out["resets_at"] = int(resets_at)
    return out


def capture(payload: dict[str, Any]) -> None:
    raw_limits = payload.get("rate_limits")
    raw_limits = raw_limits if isinstance(raw_limits, dict) else {}
    limits = {
        key: window
        for key in ("five_hour", "seven_day")
        if (window := clean_window(raw_limits.get(key))) is not None
    }
    # Before the first API response Claude Code omits rate_limits. Keep the
    # previous useful snapshot rather than replacing it with an empty object.
    if not limits:
        return

    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    now = time.time()
    snapshot = {
        "schema_version": 1,
        "source": "claude_code_statusline",
        "captured_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "captured_at_epoch": now,
        "claude_version": str(payload.get("version") or ""),
        "model": {
            "id": str(model.get("id") or ""),
            "display_name": str(model.get("display_name") or ""),
        },
        "rate_limits": limits,
    }
    plan_value = (
        payload.get("plan_type")
        or payload.get("plan")
        or raw_limits.get("plan_type")
        or raw_limits.get("plan")
    )
    if isinstance(plan_value, str) and plan_value.strip():
        snapshot["plan_type"] = plan_value.strip()
    limit_reached = payload.get("limit_reached")
    if not isinstance(limit_reached, bool):
        limit_reached = raw_limits.get("limit_reached")
    if isinstance(limit_reached, bool):
        snapshot["limit_reached"] = limit_reached
    atomic_write_json(snapshot_path(), snapshot)


def status_text(payload: dict[str, Any]) -> str:
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_name = str(model.get("display_name") or model.get("id") or "Claude")
    parts = [f"[{model_name}]"]

    context = payload.get("context_window")
    context = context if isinstance(context, dict) else {}
    context_used = finite_number(context.get("used_percentage"))
    if context_used is not None:
        parts.append(f"ctx {context_used:.0f}%")

    limits = payload.get("rate_limits")
    limits = limits if isinstance(limits, dict) else {}
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        window = limits.get(key)
        window = window if isinstance(window, dict) else {}
        used = finite_number(window.get("used_percentage"))
        if used is not None:
            parts.append(f"{label} {used:.0f}% used")
    return " | ".join(parts)


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse {path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}.")
    return value


def is_ours(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return str(Path(__file__).resolve()) in str(value.get("command") or "")


def install(force: bool) -> None:
    settings_path = resolve_claude_home() / "settings.json"
    settings = load_settings(settings_path)
    existing = settings.get("statusLine")
    if existing and not is_ours(existing) and not force:
        raise SystemExit(
            "Claude Code already has a different statusLine. Re-run with --force only if you want to replace it."
        )
    previous = dict(existing) if isinstance(existing, dict) and is_ours(existing) else {}
    previous.update({"type": "command", "command": command_text()})
    settings["statusLine"] = previous
    atomic_write_json(settings_path, settings)
    print(f"Installed Claude Code usage capture in {settings_path}")
    print("The first rate-limit snapshot will appear after Claude Code completes an API response.")


def uninstall() -> None:
    settings_path = resolve_claude_home() / "settings.json"
    settings = load_settings(settings_path)
    existing = settings.get("statusLine")
    if not is_ours(existing):
        print("This usage capture is not the configured Claude Code statusLine; nothing changed.")
        return
    settings.pop("statusLine", None)
    atomic_write_json(settings_path, settings)
    print(f"Removed Claude Code usage capture from {settings_path}")


def show_status() -> None:
    settings_path = resolve_claude_home() / "settings.json"
    settings = load_settings(settings_path)
    print(f"Settings: {settings_path}")
    print(f"Installed: {'yes' if is_ours(settings.get('statusLine')) else 'no'}")
    print(f"Snapshot: {snapshot_path()}")
    print(f"Snapshot exists: {'yes' if snapshot_path().exists() else 'no'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Claude Code 5-hour and 7-day usage limits.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Register this script as the user statusLine.")
    action.add_argument("--uninstall", action="store_true", help="Remove this script if it is the active statusLine.")
    action.add_argument("--status", action="store_true", help="Show capture configuration status.")
    parser.add_argument("--force", action="store_true", help="Allow --install to replace another statusLine.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.install:
        install(force=args.force)
        return
    if args.uninstall:
        uninstall()
        return
    if args.status:
        show_status()
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(payload, dict):
        return
    try:
        capture(payload)
    except OSError:
        # A status line must never interfere with the Claude Code session.
        pass
    print(status_text(payload))


if __name__ == "__main__":
    main()
