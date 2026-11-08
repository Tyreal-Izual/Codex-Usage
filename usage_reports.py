"""Shared report composition for the native app and legacy HTTP interface."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

import claude_usage
import codex_usage
import isambard_status
from usage_common import CollectionError, cache_directory
from usage_sources import SOURCES, SourceCache


def sqlite_error(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    databases = data.get("sqlite_threads")
    selected = databases.get("selected") if isinstance(databases, dict) else None
    error = selected.get("error") if isinstance(selected, dict) else None
    return f"SQLite: {error}" if error else None


def error_message(exc: BaseException) -> str:
    if isinstance(exc, CollectionError):
        return str(exc)
    if isinstance(exc, SystemExit):
        return f"collector exited with code {exc.code}"
    return f"{type(exc).__name__}: {exc}"


def safe_collect(
    section: str, collector: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, str] | None]:
    try:
        result = collector()
        message = sqlite_error(result)
        return result, {"section": section, "message": message} if message else None
    except SystemExit as exc:
        message = error_message(exc)
    except Exception as exc:  # Keep the dashboard alive if one collector changes.
        message = error_message(exc)

    return (
        {
            "ok": False,
            "retrieved_at_local": codex_usage.local_now_text(),
            "error": {"message": message},
        },
        {"section": section, "message": message},
    )


def collect_report(
    report: str, top: int, days: int, warn_days: int, bucket_width: str,
    limit: int | None, group_by: list[str], no_costs: bool,
    isambard_force_refresh: bool, *, enabled_sources: frozenset[str] = SOURCES,
    source_cache: SourceCache | None = None, cache_dir: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Compose reports from the same source collectors used by progressive UI requests."""
    api_args = argparse.Namespace(days=days, top=top, bucket_width=bucket_width,
                                  limit=limit, group_by=group_by, no_costs=no_costs)
    def local() -> dict[str, Any]:
        result = codex_usage.collect_local_usage(codex_usage.CODEX_HOME, top_n=top)
        codex_usage.limit_local_usage_days(result, days)
        return result

    # name -> source, TTL, cache parameters, collector
    collectors = {
        "reset_credits": ("codex", 60, (), codex_usage.collect_resets),
        "local_usage": ("codex", 5, (top, days), local),
        "online_usage": ("codex", 60, (), codex_usage.collect_online_usage),
        "claude_usage": ("claude", 15, (top, days), lambda: claude_usage.collect_usage(top_n=top, days=days)),
        "isambard_status": ("isambard", 30, (), lambda: isambard_status.collect_status(
            cache_path=(cache_dir or cache_directory()) / "isambard_status_snapshot.json",
            force_refresh=isambard_force_refresh)),
        "api_usage": ("codex", 60, (days, top, bucket_width, limit, tuple(group_by), no_costs),
                      lambda: codex_usage.collect_api_usage(api_args)),
    }
    reports = {
        "all": ("reset_credits", "local_usage", "online_usage", "claude_usage", "isambard_status"),
        "codex-usage": ("reset_credits", "local_usage", "online_usage", "api_usage"),
        "resets": ("reset_credits",), "local-usage": ("local_usage",),
        "online-usage": ("online_usage",), "claude-usage": ("claude_usage",),
        "isambard-status": ("isambard_status",), "api-usage": ("api_usage",),
    }
    if report not in reports:
        message = f"unknown report: {report}"
        return {"ok": False, "error": {"message": message}}, [{"section": "request", "message": message}]
    data: dict[str, Any] = {"retrieved_at_local": codex_usage.local_now_text()}
    errors = []
    for name in reports[report]:
        source, ttl, params, collector = collectors[name]
        if source not in enabled_sources or (name == "api_usage" and not codex_usage.admin_api_key()):
            result, error = {"ok": True, "disabled": True, "source": source}, None
        elif source_cache is None:
            result, error = safe_collect(name, collector)
        else:
            result, error = source_cache.get(
                (name, *params), lambda: safe_collect(name, collector), ttl,
                force=name == "isambard_status" and isambard_force_refresh)
        data[name] = result
        if error:
            errors.append(error)
    if report not in {"all", "codex-usage"}:
        data = data[reports[report][0]]
    return data, errors

def report_has_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False or sqlite_error(data):
        return True
    endpoints = data.get("endpoints")
    if isinstance(endpoints, dict):
        for item in endpoints.values():
            if isinstance(item, dict) and item.get("ok") is False:
                return True
    for key in (
        "reset_credits",
        "local_usage",
        "online_usage",
        "claude_usage",
        "api_usage",
        "isambard_status",
    ):
        if report_has_error(data.get(key)):
            return True
    return False
