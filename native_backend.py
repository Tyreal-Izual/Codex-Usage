#!/usr/bin/env python3
"""Private JSON-lines bridge for the macOS app. No HTTP listener or web assets."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO

import codex_radar
import codex_usage
from usage_common import cache_directory, tls_diagnostics
from usage_reports import collect_report, report_has_error
from usage_sources import SOURCES, SourceCache, check_environment, resolve_sources

REPORTS = frozenset({"local-usage", "online-usage", "resets", "claude-usage",
                     "isambard-status", "api-usage", "all", "codex-usage"})
MAX_LINE_BYTES = 64 * 1024


class NativeBackend:
    def __init__(self, *, sources: frozenset[str], cache_dir: Path,
                 radar: Any = None) -> None:
        self.sources = sources
        self.cache_dir = cache_dir
        self.cache = SourceCache()
        self.lock = threading.RLock()
        self.radar = radar or codex_radar.RadarService(cache_dir / "codex_radar_snapshot.json")
        self.force_after = 0.0
        self.radar.set_enabled("radar" in sources)
        if "radar" in sources:
            self.radar.start()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        with self.lock:
            if action == "configure":
                sources = request.get("sources")
                if (not isinstance(sources, list) or
                        any(not isinstance(s, str) or s not in SOURCES for s in sources)):
                    raise ValueError("sources must contain only codex, claude, isambard, radar")
                self.sources = frozenset(sources)
                self.radar.set_enabled("radar" in self.sources)
                if "radar" in self.sources:
                    self.radar.start()
            enabled = self.sources
        if action in {"hello", "configure"}:
            return {"protocol": 1, "sources": sorted(enabled),
                    "bundled_python": bool(getattr(sys, "frozen", False)),
                    "detected_sources": sorted(resolve_sources("auto", codex_usage.CODEX_HOME)),
                    "admin_enabled": bool(codex_usage.admin_api_key())}
        if action == "check":
            return check_environment(codex_usage.CODEX_HOME, enabled, self.cache_dir)
        if action == "radar":
            if "radar" not in enabled:
                return {"available": False, "disabled": True, "data": None}
            return self.radar.snapshot()
        if action != "report" or request.get("report") not in REPORTS:
            raise ValueError("Unknown action or report")
        days = self.integer(request, "days", 30, 1, 365)
        top = self.integer(request, "top", 10, 1, 100)
        force = request.get("force") is True and request["report"] == "isambard-status"
        with self.lock:
            if force and "isambard" in enabled:
                now = time.monotonic()
                if now < self.force_after:
                    force = False
                else:
                    self.force_after = now + 30
        data, errors = collect_report(
            request["report"], top, days, 7, "1d", None, [], False, force,
            enabled_sources=enabled, source_cache=self.cache, cache_dir=self.cache_dir)
        return {"ok": not errors and not report_has_error(data), "data": data, "errors": errors}

    @staticmethod
    def integer(request: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
        value = request.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        return min(high, max(low, value))

    def close(self) -> None:
        self.radar.close()


def serve(backend: NativeBackend, incoming: TextIO, outgoing: TextIO) -> None:
    """Correlate replies by ID; slow collectors never block settings or Radar reads."""
    output_lock = threading.Lock()
    slots = threading.BoundedSemaphore(8)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="usage-source")

    def reply(payload: dict[str, Any]) -> None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError):
            encoded = json.dumps({"id": payload.get("id"), "ok": False,
                                  "error": "Collector returned invalid JSON data"})
        with output_lock:
            try:
                outgoing.write(encoded + "\n")
                outgoing.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass  # The app closed its pipe while a collection was finishing.

    def run(request: dict[str, Any], *, release: bool = False) -> None:
        try:
            reply({"id": request["id"], "ok": True, "result": backend.handle(request)})
        except Exception as error:
            reply({"id": request["id"], "ok": False, "error": str(error)})
        finally:
            if release:
                slots.release()

    try:
        while line := incoming.readline(MAX_LINE_BYTES + 1):
            identifier = None
            try:
                if len(line) > MAX_LINE_BYTES:
                    if not line.endswith("\n"):
                        while chunk := incoming.readline(MAX_LINE_BYTES + 1):
                            if chunk.endswith("\n"):
                                break
                    raise ValueError("Request exceeds size limit")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Request must be an object")
                identifier = request.get("id")
                if type(identifier) is not int or identifier < 0:
                    raise ValueError("Request requires a nonnegative integer id")
                if request.get("action") == "report":
                    if slots.acquire(blocking=False):
                        pool.submit(run, request, release=True)
                    else:
                        reply({"id": identifier, "ok": False, "error": "Collectors are busy; retry shortly"})
                else:
                    run(request)
            except (ValueError, TypeError) as error:
                reply({"id": identifier, "ok": False, "error": str(error)})
    finally:
        backend.close()
        pool.shutdown(wait=True, cancel_futures=True)


def main() -> None:
    # Retain optional capture/automation and CLI exports in a self-contained app.
    if len(sys.argv) > 1 and sys.argv[1] in {"--statusline", "--refresh-claude", "--codex"}:
        command = sys.argv.pop(1)
        if command == "--statusline":
            import claude_usage_statusline
            claude_usage_statusline.main()
        elif command == "--refresh-claude":
            import claude_usage_refresher
            raise SystemExit(claude_usage_refresher.main())
        else:
            codex_usage.main()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="auto")
    parser.add_argument("--cache-dir", type=Path, default=cache_directory())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-tls", action="store_true", help="Inspect CA trust without network access")
    parser.add_argument("--check-https", action="store_true", help="Probe public HTTPS endpoints without credentials")
    args = parser.parse_args()
    if args.check_tls or args.check_https:
        result = tls_diagnostics(probe=args.check_https)
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
    sources = resolve_sources(args.sources, codex_usage.CODEX_HOME)
    if args.check:
        print(json.dumps(check_environment(codex_usage.CODEX_HOME, sources, args.cache_dir)))
        return
    # Reserve stdout for the wire protocol, including any future collector prints.
    wire = sys.stdout
    sys.stdout = sys.stderr
    serve(NativeBackend(sources=sources, cache_dir=args.cache_dir), sys.stdin, wire)


if __name__ == "__main__":
    main()
