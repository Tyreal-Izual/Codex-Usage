#!/usr/bin/env python3
"""Fetch and cache public Isambard service-status data for the web dashboard."""

from __future__ import annotations

import html
import json
import os
import ssl
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


STATUS_URL = "https://docs.isambard.ac.uk/service-status/"
MAINTENANCE_URL = "https://docs.isambard.ac.uk/service-status/planned_maintenance/"
DEFAULT_CACHE_PATH = Path(__file__).with_name("isambard_status_snapshot.json")
DEFAULT_CACHE_SECONDS = 300
USER_AGENT = "Codex-Usage-Isambard-Status/1.0 (local personal dashboard)"


def clean_text(value: str) -> str:
    """Collapse HTML whitespace without accidentally joining words."""
    return " ".join(html.unescape(value).split())


class PageParser(HTMLParser):
    """Extract MkDocs status cards and the maintenance table from an article."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.statuses: list[dict[str, str]] = []
        self._details: dict[str, Any] | None = None
        self._summary_depth = 0
        self._table_depth = 0
        self._in_cell = False
        self._cell_tag = ""
        self._cell_text: list[str] = []
        self._row: list[str] = []
        self.headers: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "article" and "md-content__inner" in (attributes.get("class") or ""):
            self.article_depth = 1
            return
        if not self.article_depth:
            return
        self.article_depth += 1

        if tag == "details":
            self._details = {"class": attributes.get("class", ""), "title": [], "body": []}
        elif tag == "summary" and self._details is not None:
            self._summary_depth = 1
        elif tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in {"th", "td"} and self._table_depth:
            self._in_cell = True
            self._cell_tag = tag
            self._cell_text = []
        elif tag in {"p", "br", "li"} and self._details is not None and not self._summary_depth:
            self._details["body"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self.article_depth:
            return

        if tag in {"th", "td"} and self._in_cell and tag == self._cell_tag:
            self._row.append(clean_text("".join(self._cell_text)))
            self._in_cell = False
            self._cell_tag = ""
        elif tag == "tr" and self._table_depth and self._row:
            if self._cell_tag == "th":
                self.headers = self._row
            elif not self.headers:
                # MkDocs uses <th> headers, but this keeps the parser tolerant.
                self.headers = self._row
            else:
                self.rows.append(self._row)
            self._row = []
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
        elif tag == "summary" and self._summary_depth:
            self._summary_depth = 0
        elif tag == "details" and self._details is not None:
            title = clean_text("".join(self._details["title"]))
            body = clean_text("".join(self._details["body"]))
            if title:
                self.statuses.append(
                    {"title": title, "body": body, "class": self._details["class"]}
                )
            self._details = None

        self.article_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.article_depth:
            return
        if self._in_cell:
            self._cell_text.append(data)
        if self._details is not None:
            target = "title" if self._summary_depth else "body"
            self._details[target].append(data)


def ssl_context() -> ssl.SSLContext:
    """Use a system CA bundle when Python has no configured certificate path."""
    configured_bundle = os.environ.get("SSL_CERT_FILE")
    if configured_bundle:
        return ssl.create_default_context(cafile=configured_bundle)

    for bundle in (
        "/etc/ssl/cert.pem",  # macOS and some Unix installations
        "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/Fedora
    ):
        if Path(bundle).is_file():
            return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def fetch(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def parse_pages(status_html: str, maintenance_html: str) -> dict[str, Any]:
    status_parser = PageParser()
    status_parser.feed(status_html)
    maintenance_parser = PageParser()
    maintenance_parser.feed(maintenance_html)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "statuses": status_parser.statuses,
        "maintenance_headers": maintenance_parser.headers,
        "maintenance_rows": maintenance_parser.rows,
    }


def status_kind(status: dict[str, str]) -> str:
    """Map the source's MkDocs admonition class to a stable display state."""
    source_class = status.get("class", "").lower()
    title = status.get("title", "").lower()
    if "success" in source_class or "no known issue" in title:
        return "ok"
    if "warning" in source_class or "degraded" in title or "at risk" in title:
        return "warning"
    if "failure" in source_class or "outage" in title:
        return "outage"
    return "unknown"


def load_cache(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any] | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp.write(content)
        temporary_path = Path(temp.name)
    temporary_path.replace(path)


def cache_age_seconds(data: dict[str, Any]) -> int | None:
    fetched_at = data.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds()))


def cached_result(
    data: dict[str, Any], *, reason: str | None = None, stale: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "status": data,
        "source": "cache",
        "cache_age_seconds": cache_age_seconds(data),
    }
    if reason:
        result["warning"] = reason
        result["stale"] = stale
    return result


def collect_status(
    *,
    timeout: int = 30,
    cache_path: Path = DEFAULT_CACHE_PATH,
    cache_seconds: int = DEFAULT_CACHE_SECONDS,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return a live result, a recent cache, or a last-known-good stale cache."""
    cached = load_cache(cache_path)
    cache_age = cache_age_seconds(cached) if cached else None
    if cached and not force_refresh and cache_age is not None and cache_age < cache_seconds:
        return cached_result(cached)

    try:
        data = parse_pages(
            fetch(STATUS_URL, timeout),
            fetch(MAINTENANCE_URL, timeout),
        )
        atomic_write(cache_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except (URLError, TimeoutError, OSError, ValueError) as error:
        if cached:
            return cached_result(
                cached,
                reason=f"Live Isambard status fetch failed; showing the last successful result: {error}",
                stale=True,
            )
        return {
            "ok": False,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "error": {"message": f"Isambard status fetch failed: {error}"},
        }

    return {
        "ok": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "status": data,
        "source": "live",
        "cache_age_seconds": 0,
    }
