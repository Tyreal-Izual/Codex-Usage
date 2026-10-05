#!/usr/bin/env python3
"""
Local web dashboard for Codex and Claude Code usage.

Imports the standalone collectors, exposes authenticated local JSON reports,
and assembles the editable templates/static assets without a build step.
"""

from __future__ import annotations

import argparse
import http.cookies
import json
import math
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from pathlib import Path
from usage_common import CollectionError, cache_directory
from usage_sources import SOURCES, SourceCache, check_environment, resolve_sources
from dashboard_assets import asset_text, load_page
import codex_usage
import claude_usage
import isambard_status
import codex_radar


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_REFRESH_SECONDS = 15
DEFAULT_DAYS = 30
MAX_TOP = 100
MAX_DAYS = 365
MAX_ADMIN_LIMIT = 1440
ACCESS_COOKIE_NAME = "codex_usage_session"
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_COLLECTORS = 2
DEFAULT_REPORT_CACHE_SECONDS = 5
FORCE_REFRESH_COOLDOWN_SECONDS = 30
FORCE_REFRESH_ACTION_HEADER = "X-Codex-Usage-Action"
FORCE_REFRESH_ACTION = "force-refresh"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})


class CollectionBusy(RuntimeError):
    """Raised when a new collection would exceed the configured work limit."""

    def __init__(self, message: str, *, retry_after: int = 1) -> None:
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class ReportCoordinator:
    """Coalesce identical work, cache it briefly, and bound distinct collectors."""

    def __init__(self, *, cache_seconds: int, max_collectors: int) -> None:
        if cache_seconds < 0:
            raise ValueError("cache_seconds must be zero or greater")
        if max_collectors < 1:
            raise ValueError("max_collectors must be at least one")
        self.cache_seconds = cache_seconds
        self._condition = threading.Condition()
        self._entries: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._inflight: set[tuple[Any, ...]] = set()
        self._collector_slots = threading.BoundedSemaphore(max_collectors)
        self._force_refresh_blocked_until = 0.0

    def get_or_collect(
        self,
        key: tuple[Any, ...],
        collector: Callable[[], Any],
        *,
        force_refresh: bool = False,
    ) -> Any:
        while True:
            with self._condition:
                now = time.monotonic()
                self._entries = {
                    entry_key: entry
                    for entry_key, entry in self._entries.items()
                    if entry[0] > now
                }
                cached = self._entries.get(key)
                if cached:
                    return cached[1]
                if key in self._inflight:
                    self._condition.wait()
                    continue
                if force_refresh and now < self._force_refresh_blocked_until:
                    raise CollectionBusy(
                        "force refresh is cooling down",
                        retry_after=math.ceil(
                            self._force_refresh_blocked_until - now
                        ),
                    )
                if not self._collector_slots.acquire(blocking=False):
                    raise CollectionBusy("collection capacity is exhausted")
                self._inflight.add(key)
                if force_refresh:
                    self._force_refresh_blocked_until = (
                        now + FORCE_REFRESH_COOLDOWN_SECONDS
                    )
                break

        try:
            value = collector()
        except BaseException:
            with self._condition:
                self._inflight.discard(key)
                self._collector_slots.release()
                self._condition.notify_all()
            raise

        with self._condition:
            cache_seconds = (
                FORCE_REFRESH_COOLDOWN_SECONDS
                if force_refresh
                else self.cache_seconds
            )
            if cache_seconds:
                self._entries[key] = (
                    time.monotonic() + cache_seconds,
                    value,
                )
            self._inflight.discard(key)
            self._collector_slots.release()
            self._condition.notify_all()
        return value


def normalise_host(value: str) -> str:
    return value.strip().lower().strip("[]").rstrip(".")


def allowed_hostnames(bind_host: str, extra_hosts: list[str]) -> set[str]:
    bind = normalise_host(bind_host)
    extras = {normalise_host(value) for value in extra_hosts if value.strip()}
    if bind in WILDCARD_HOSTS and not extras:
        raise ValueError(
            "Wildcard binding requires at least one --allowed-host value."
        )
    allowed = set(extras)
    if bind not in WILDCARD_HOSTS:
        allowed.add(bind)
    if bind in LOOPBACK_HOSTS:
        allowed.update(LOOPBACK_HOSTS)
    return allowed


def host_is_allowed(host_header: str | None, allowed: set[str], port: int) -> bool:
    if not host_header:
        return False
    raw_host = host_header.strip()
    if (
        raw_host != host_header
        or raw_host.endswith(":")
        or any(character.isspace() for character in raw_host)
        or any(character in raw_host for character in "/?#\\,")
    ):
        return False
    try:
        parsed = urllib.parse.urlsplit(f"//{raw_host}")
        hostname = normalise_host(parsed.hostname or "")
        request_port = parsed.port
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    effective_port = 80 if request_port is None else request_port
    return hostname in allowed and effective_port == port


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that rejects work before spawning excess threads."""

    def __init__(self, *args: Any, max_workers: int, **kwargs: Any) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least one")
        self._request_slots = threading.BoundedSemaphore(max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            body = b'{"ok": false, "error": "server busy"}\n'
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Retry-After: 1\r\nConnection: close\r\n\r\n"
                + body
            )
            try:
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def server_close(self) -> None:
        radar = getattr(self, "radar_service", None)
        if radar is not None:
            radar.close()
        super().server_close()


INDEX_HTML = load_page("index")


INDEX_HTML = INDEX_HTML.replace("__RADAR_STYLE__", codex_radar.STYLE).replace(
    "__RADAR_SCRIPT__", codex_radar.SCRIPT
).replace("__REFRESH_SCRIPT__", asset_text("static/refresh.js"))


MAINTENANCE_HTML = load_page("maintenance")


def positive_int_query(
    query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = query.get(name, [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def optional_positive_int_query(query: dict[str, list[str]], name: str) -> int | None:
    raw = query.get(name, [""])[0]
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def list_query(query: dict[str, list[str]], name: str) -> list[str]:
    values: list[str] = []
    for item in query.get(name, []):
        values.extend(part.strip() for part in item.split(",") if part.strip())
    return values


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
        return collector(), None
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


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def report_has_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False:
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


class UsageWebHandler(BaseHTTPRequestHandler):
    server_version = "CodingUsageWeb/1.0"

    def request_host_is_allowed(self) -> bool:
        host_headers = self.headers.get_all("Host", [])
        if len(host_headers) != 1:
            return False
        return host_is_allowed(
            host_headers[0],
            getattr(self.server, "allowed_hosts", set()),
            int(self.server.server_address[1]),
        )

    def request_has_access(self) -> bool:
        expected = str(getattr(self.server, "access_token", ""))
        authorization = self.headers.get("Authorization", "")
        scheme, separator, bearer = authorization.partition(" ")
        if (
            expected
            and separator
            and scheme.lower() == "bearer"
            and secrets.compare_digest(bearer.strip(), expected)
        ):
            return True

        cookie_header = self.headers.get("Cookie", "")
        try:
            cookies = http.cookies.SimpleCookie(cookie_header)
        except http.cookies.CookieError:
            return False
        morsel = cookies.get(ACCESS_COOKIE_NAME)
        return bool(
            expected
            and morsel is not None
            and secrets.compare_digest(morsel.value, expected)
        )

    def bootstrap_session(
        self,
        parsed: urllib.parse.ParseResult,
        *,
        include_body: bool,
    ) -> bool:
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if "access_token" not in query:
            return False
        supplied = query["access_token"]
        expected = str(getattr(self.server, "access_token", ""))
        if (
            len(supplied) != 1
            or not expected
            or not secrets.compare_digest(supplied[0], expected)
        ):
            self.send_json(
                {"ok": False, "error": "invalid dashboard access token"},
                status=403,
                include_body=include_body,
            )
            return True

        remaining = [
            item
            for item in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if item[0] != "access_token"
        ]
        location = parsed.path or "/"
        if not location.startswith("/") or location.startswith("//"):
            location = "/"
        if remaining:
            location += "?" + urllib.parse.urlencode(remaining, doseq=True)

        cookie = http.cookies.SimpleCookie()
        cookie[ACCESS_COOKIE_NAME] = expected
        cookie[ACCESS_COOKIE_NAME]["path"] = "/"
        cookie[ACCESS_COOKIE_NAME]["httponly"] = True
        cookie[ACCESS_COOKIE_NAME]["samesite"] = "Strict"
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def reject_untrusted_host(self, *, include_body: bool) -> bool:
        if self.request_host_is_allowed():
            return False
        self.send_json(
            {"ok": False, "error": "unrecognized Host header"},
            status=421,
            include_body=include_body,
        )
        return True

    def reject_missing_access(self, *, include_body: bool) -> bool:
        if self.request_has_access():
            return False
        self.send_json(
            {"ok": False, "error": "dashboard authentication required"},
            status=403,
            include_body=include_body,
            extra_headers={"WWW-Authenticate": "Bearer"},
        )
        return True

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if self.reject_untrusted_host(include_body=False):
            return
        if self.bootstrap_session(parsed, include_body=False):
            return
        if parsed.path in {
            "/",
            "/index.html",
            "/isambard-maintenance",
            "/api/usage",
            "/api/codex-radar",
            "/api/sources",
        } and self.reject_missing_access(include_body=False):
            return
        if parsed.path in {"/", "/index.html"}:
            self.send_html(include_body=False)
            return
        if parsed.path == "/isambard-maintenance":
            self.send_maintenance_html(include_body=False)
            return
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "time": time.time()}, include_body=False)
            return
        if parsed.path == "/api/sources":
            self.send_json(self.source_settings(), include_body=False)
            return
        if parsed.path == "/api/codex-radar":
            self.send_json(self.radar_snapshot(), include_body=False)
            return
        self.send_json({"ok": False, "error": "not found"}, status=404, include_body=False)

    def do_GET(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if self.reject_untrusted_host(include_body=True):
            return
        if self.bootstrap_session(parsed, include_body=True):
            return
        if parsed.path in {
            "/",
            "/index.html",
            "/isambard-maintenance",
            "/api/usage",
            "/api/codex-radar",
            "/api/sources",
        } and self.reject_missing_access(include_body=True):
            return
        if parsed.path in {"/", "/index.html"}:
            self.send_html()
            return
        if parsed.path == "/isambard-maintenance":
            self.send_maintenance_html()
            return
        if parsed.path == "/api/usage":
            self.send_usage(parsed.query)
            return
        if parsed.path == "/api/sources":
            self.send_json(self.source_settings())
            return
        if parsed.path == "/api/codex-radar":
            self.send_json(self.radar_snapshot())
            return
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "time": time.time()})
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - http.server API name.
        parsed = urllib.parse.urlparse(self.path)
        if self.reject_untrusted_host(include_body=True):
            return
        if parsed.path == "/api/sources":
            if self.reject_missing_access(include_body=True):
                return
            if self.headers.get(FORCE_REFRESH_ACTION_HEADER) != "set-sources":
                self.send_json({"ok": False, "error": "set-sources action header required"}, status=403)
                return
            self.update_sources(parsed.query)
            return
        if parsed.path != "/api/usage":
            self.send_json({"ok": False, "error": "not found"}, status=404)
            return
        if self.reject_missing_access(include_body=True):
            return
        if self.headers.get(FORCE_REFRESH_ACTION_HEADER) != FORCE_REFRESH_ACTION:
            self.send_json(
                {"ok": False, "error": "force-refresh action header required"},
                status=403,
            )
            return
        self.send_usage(parsed.query, allow_force_refresh=True)

    def source_settings(self) -> dict[str, Any]:
        with self.server.sources_lock:
            return {"sources": sorted(self.server.enabled_sources)}

    def radar_snapshot(self) -> dict[str, Any]:
        with self.server.sources_lock:
            if "radar" not in self.server.enabled_sources:
                return DisabledRadar().snapshot()
            service = self.server.radar_service
        return service.snapshot()

    def update_sources(self, raw_query: str) -> None:
        query = urllib.parse.parse_qs(raw_query, keep_blank_values=True)
        if (not query or not query.keys() <= {"isambard", "radar"}
                or any(values not in (["true"], ["false"]) for values in query.values())):
            self.send_json({"ok": False, "error": "Supply isambard/radar as true or false"}, status=400)
            return
        with self.server.sources_lock:
            enabled = set(self.server.enabled_sources)
            for source, values in query.items():
                if values == ["true"]:
                    enabled.add(source)
                else:
                    enabled.discard(source)
            if "radar" in query:
                if "radar" in enabled and isinstance(self.server.radar_service, DisabledRadar):
                    self.server.radar_service = codex_radar.RadarService(self.server.cache_dir / "codex_radar_snapshot.json")
                service = self.server.radar_service
                if not isinstance(service, DisabledRadar):
                    service.set_enabled("radar" in enabled)
                    if "radar" in enabled:
                        service.start()
            self.server.enabled_sources = frozenset(enabled)
            settings = {"sources": sorted(enabled)}
        self.send_json(settings)

    def send_html(self, include_body: bool = True) -> None:
        refresh = getattr(self.server, "refresh_seconds", DEFAULT_REFRESH_SECONDS)
        config = json.dumps({**self.source_settings(),
                             "days": getattr(self.server, "local_days", DEFAULT_DAYS),
                             "refreshSeconds": refresh,
                             "defaultReport": self.server.default_report,
                             "adminEnabled": bool(codex_usage.admin_api_key())})
        body = INDEX_HTML.replace("__DASHBOARD_CONFIG__", config).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser navigation or a source switch cancelled this response.

    def send_maintenance_html(self, include_body: bool = True) -> None:
        body = MAINTENANCE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser navigation or a source switch cancelled this response.

    def send_usage(self, raw_query: str, *, allow_force_refresh: bool = False) -> None:
        query = urllib.parse.parse_qs(raw_query)
        report = query.get("report", ["all"])[0]
        top = positive_int_query(query, "top", 10, 1, MAX_TOP)
        days = positive_int_query(query, "days", getattr(self.server, "local_days", DEFAULT_DAYS), 1, MAX_DAYS)
        warn_days = positive_int_query(query, "warn_days", 7, 0, 365)
        bucket_width = query.get("bucket_width", ["1d"])[0]
        if bucket_width not in {"1d", "1h", "1m"}:
            bucket_width = "1d"
        limit = optional_positive_int_query(query, "limit")
        if limit is not None:
            limit = min(limit, MAX_ADMIN_LIMIT)
        group_by = list_query(query, "group_by")
        no_costs = query.get("no_costs", ["false"])[0].lower() in {"1", "true", "yes"}
        force_refresh_requested = query.get(
            "isambard_force_refresh",
            ["false"],
        )[0].lower() in {
            "1",
            "true",
            "yes",
        }
        if force_refresh_requested and not allow_force_refresh:
            self.send_json(
                {"ok": False, "error": "force refresh requires authenticated POST"},
                status=405,
                extra_headers={"Allow": "POST"},
            )
            return
        if allow_force_refresh and not force_refresh_requested:
            self.send_json(
                {"ok": False, "error": "POST is reserved for force refresh"},
                status=400,
            )
            return
        isambard_force_refresh = force_refresh_requested and allow_force_refresh

        with self.server.sources_lock:
            enabled_sources = self.server.enabled_sources
        coordinator = getattr(self.server, "report_coordinator")
        cache_key = (
            tuple(sorted(enabled_sources)),
            report,
            top,
            days,
            warn_days,
            bucket_width,
            limit,
            tuple(group_by),
            no_costs,
            isambard_force_refresh,
        )
        try:
            data, errors = coordinator.get_or_collect(
                cache_key,
                lambda: collect_report(
                    report=report,
                    top=top,
                    days=days,
                    warn_days=warn_days,
                    bucket_width=bucket_width,
                    limit=limit,
                    group_by=group_by,
                    no_costs=no_costs,
                    isambard_force_refresh=isambard_force_refresh,
                    enabled_sources=enabled_sources,
                    source_cache=self.server.source_cache,
                    cache_dir=self.server.cache_dir,
                ),
                force_refresh=isambard_force_refresh,
            )
        except CollectionBusy as exc:
            self.send_json(
                {"ok": False, "error": str(exc)},
                status=429,
                extra_headers={"Retry-After": str(exc.retry_after)},
            )
            return
        payload = {
            "ok": not errors and not report_has_error(data),
            "report": report,
            "served_at_local": codex_usage.local_now_text(),
            "settings": {
                "top": top,
                "days": days,
                "warn_days": warn_days,
                "bucket_width": bucket_width,
                "limit": limit,
                "group_by": group_by,
                "no_costs": no_costs,
                "isambard_force_refresh": isambard_force_refresh,
            },
            "errors": errors,
            "data": data,
        }
        self.send_json(payload)

    def send_json(
        self,
        payload: Any,
        status: int = 200,
        include_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if include_body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser navigation or a source switch cancelled this response.

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        token = str(getattr(self.server, "access_token", ""))
        safe_args = tuple(
            str(value).replace(token, "[REDACTED]") if token else value
            for value in args
        )
        super().log_message(fmt, *safe_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a local browser dashboard for Codex and Claude Code usage."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind. Default: {DEFAULT_HOST}. Use with care if changing it.",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help=(
            "Host header to accept. Repeat for aliases. Wildcard binds require "
            "at least one explicit value."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind. Default: {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Default browser refresh interval in seconds. Default: {DEFAULT_REFRESH_SECONDS}.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-request access logs.",
    )
    parser.add_argument(
        "--max-workers",
        type=codex_usage.positive_int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Maximum simultaneous HTTP requests. Default: {DEFAULT_MAX_WORKERS}.",
    )
    parser.add_argument(
        "--max-collectors",
        type=codex_usage.positive_int,
        default=DEFAULT_MAX_COLLECTORS,
        help=f"Maximum distinct report collections. Default: {DEFAULT_MAX_COLLECTORS}.",
    )
    parser.add_argument(
        "--cache-seconds",
        type=codex_usage.non_negative_int,
        default=DEFAULT_REPORT_CACHE_SECONDS,
        help=(
            "Seconds to reuse a completed report and coalesce identical work. "
            f"Default: {DEFAULT_REPORT_CACHE_SECONDS}."
        ),
    )
    parser.add_argument("--days", type=codex_usage.positive_int, default=DEFAULT_DAYS, help="Local daily rows to display (1-365); configured only at startup.")
    parser.add_argument("--sources", default="auto", help="auto detects local Codex/Claude and enables Isambard/Radar; or supply all or a comma-separated initial selection")
    parser.add_argument("--default-report", default="all", choices=["all", "codex-usage", "claude-usage", "isambard-status"])
    parser.add_argument("--cache-dir", type=Path, default=cache_directory(), help="Directory for public-source caches (or CODEX_USAGE_CACHE_DIR).")
    parser.add_argument("--check", action="store_true", help="Print read-only setup diagnostics as JSON and exit; no network or client commands.")
    return parser


class DisabledRadar:
    def snapshot(self) -> dict[str, Any]:
        return {"available": False, "disabled": True, "refreshing": False, "data": None}

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass


def create_server(
    host: str,
    port: int,
    *,
    access_token: str,
    allowed_hosts: list[str],
    max_workers: int,
    max_collectors: int,
    cache_seconds: int,
    radar_service: codex_radar.RadarService | None = None,
    enabled_sources: frozenset[str] = SOURCES,
    default_report: str = "all",
    cache_dir: Path | None = None,
) -> BoundedThreadingHTTPServer:
    if not access_token:
        raise ValueError("access_token must not be empty")
    allowed = allowed_hostnames(host, allowed_hosts)
    coordinator = ReportCoordinator(
        cache_seconds=cache_seconds,
        max_collectors=max_collectors,
    )
    server = BoundedThreadingHTTPServer(
        (host, port),
        UsageWebHandler,
        max_workers=max_workers,
    )
    server.access_token = access_token
    server.allowed_hosts = allowed
    server.report_coordinator = coordinator
    server.source_cache = SourceCache()
    server.sources_lock = threading.Lock()
    server.enabled_sources = enabled_sources
    server.default_report = default_report
    server.cache_dir = cache_dir or cache_directory()
    server.radar_service = (radar_service or codex_radar.RadarService(server.cache_dir / "codex_radar_snapshot.json")) if "radar" in enabled_sources else DisabledRadar()
    return server


def display_hostname(bind_host: str, allowed_hosts: set[str]) -> str:
    normalized = normalise_host(bind_host)
    if normalized in WILDCARD_HOSTS:
        normalized = sorted(allowed_hosts)[0]
    return f"[{normalized}]" if ":" in normalized else normalized


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.days > MAX_DAYS:
        parser.error("--days must be between 1 and 365")
    try:
        enabled_sources = resolve_sources(args.sources, codex_usage.CODEX_HOME)
    except ValueError as exc:
        parser.error(str(exc))
    cache_dir = args.cache_dir.expanduser()
    if args.check:
        print(json.dumps(check_environment(codex_usage.CODEX_HOME, enabled_sources, cache_dir), indent=2))
        return
    access_token = secrets.token_urlsafe(32)
    try:
        server = create_server(
            args.host,
            args.port,
            access_token=access_token,
            allowed_hosts=args.allowed_host,
            max_workers=args.max_workers,
            max_collectors=args.max_collectors,
            cache_seconds=args.cache_seconds,
            enabled_sources=enabled_sources,
            default_report=args.default_report,
            cache_dir=cache_dir,
        )
    except (ValueError, OSError) as exc:
        parser.error(f"Could not start dashboard: {exc}. If the port is in use, try --port 8766.")
    server.local_days = args.days
    server.refresh_seconds = max(3, int(args.refresh))
    server.quiet = bool(args.quiet)
    hostname = display_hostname(args.host, server.allowed_hosts)
    port = int(server.server_address[1])
    query = urllib.parse.urlencode({"access_token": access_token})
    url = f"http://{hostname}:{port}/?{query}"
    print("Codex & Claude Code Usage dashboard access URL:")
    print(url)
    print("Keep this URL private. The token is removed after the first page load.")
    print("Press Ctrl-C to stop.")
    try:
        server.radar_service.start()
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Codex & Claude Code Usage dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
