"""Per-source caching and read-only startup diagnostics."""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from usage_common import export_directory, find_claude_binary, resolve_claude_home, resolve_snapshot_path

SOURCES = frozenset({"codex", "claude", "isambard", "radar"})


def resolve_sources(value: str, codex_home: Path) -> frozenset[str]:
    if value == "all":
        return SOURCES
    if value == "auto":
        enabled = {"isambard", "radar"}
        if codex_home.exists():
            enabled.add("codex")
        if resolve_claude_home().exists() or find_claude_binary():
            enabled.add("claude")
        return frozenset(enabled)
    enabled = frozenset(part.strip() for part in value.split(",") if part.strip())
    if not enabled or not enabled <= SOURCES:
        raise ValueError("--sources must be auto, all, or a comma-separated list of codex,claude,isambard,radar")
    return enabled


class SourceCache:
    """Coalesce each source independently; never expose mutable cached objects."""
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._condition = threading.Condition()
        self._entries: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._inflight: set[tuple[Any, ...]] = set()

    def get(self, key: tuple[Any, ...], collect: Callable[[], Any], seconds: int,
            *, force: bool = False) -> Any:
        with self._condition:
            while key in self._inflight:
                self._condition.wait()
            now = self._clock()
            self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
            cached = self._entries.get(key)
            if cached is not None and not force:
                return copy.deepcopy(cached[1])
            self._inflight.add(key)
        try:
            result = collect()
            with self._condition:
                self._entries[key] = (self._clock() + seconds, copy.deepcopy(result))
            return result
        finally:
            with self._condition:
                self._inflight.discard(key)
                self._condition.notify_all()


def check_environment(codex_home: Path, enabled: frozenset[str], cache_dir: Path) -> dict[str, Any]:
    """Inspect paths only. Never read credentials, launch clients or write files."""
    claude_home = resolve_claude_home()
    snapshot = resolve_snapshot_path(claude_home)
    binary = find_claude_binary()
    nearest = cache_dir
    while not nearest.exists() and nearest != nearest.parent:
        nearest = nearest.parent
    return {
        "python": sys.version.split()[0],
        "enabled_sources": sorted(enabled),
        "codex_home": str(codex_home),
        "codex_home_exists": codex_home.is_dir(),
        "codex_auth_present": (codex_home / "auth.json").is_file(),
        "claude_home": str(claude_home),
        "claude_transcripts_present": (claude_home / "projects").is_dir(),
        "claude_binary": str(binary) if binary else None,
        "claude_snapshot": str(snapshot),
        "claude_snapshot_present": snapshot.is_file(),
        "cache_directory": str(cache_dir),
        "cache_parent_writable": nearest.is_dir() and os.access(nearest, os.W_OK),
        "export_directory": str(export_directory()),
        "admin_api_configured": bool(os.environ.get("OPENAI_ADMIN_KEY")),
        "note": "Read-only checks; credentials and remote availability were not validated.",
    }
