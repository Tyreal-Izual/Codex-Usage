"""Small shared filesystem, configuration and transport helpers (stdlib only)."""
from __future__ import annotations

import json
import os
import shutil
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any


class CollectionError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def resolve_claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def resolve_snapshot_path(home: Path | None = None) -> Path:
    return Path(os.environ.get("CLAUDE_USAGE_SNAPSHOT") or
                (home or resolve_claude_home()) / "usage-dashboard.json").expanduser()


def cache_directory() -> Path:
    configured = os.environ.get("CODEX_USAGE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "codex-usage"


def export_directory() -> Path:
    return Path(os.environ.get("CODEX_USAGE_EXPORT_DIR") or
                Path.home() / "Downloads" / "codex-usage").expanduser()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ssl_context() -> ssl.SSLContext:
    configured = os.environ.get("SSL_CERT_FILE")
    if configured:
        return ssl.create_default_context(cafile=configured)
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                   "/etc/pki/tls/certs/ca-bundle.crt"):
        if Path(bundle).is_file():
            return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def find_claude_binary(explicit: Path | None = None) -> Path | None:
    candidates = [explicit, os.environ.get("CLAUDE_BIN"), shutil.which("claude"),
                  Path.home() / ".local/bin/claude", "/opt/homebrew/bin/claude",
                  "/usr/local/bin/claude"]
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser().absolute()
            if path.is_file() and os.access(path, os.X_OK):
                return path  # Preserve the launcher's symlink / argv[0].
    return None
