#!/usr/bin/env python3
"""Smoke-test release or development helpers with isolated account data."""
import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path


def check(app: Path, *, https: bool = False, development: bool = False) -> None:
    helper = app.resolve() / "Contents/Resources/helper/usage-helper"
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        codex = home / "codex"
        claude = home / "claude"
        codex.mkdir()
        claude.mkdir()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CODEX_HOME": str(codex),
               "CLAUDE_CONFIG_DIR": str(claude), "CODEX_USAGE_CACHE_DIR": str(home / "cache"),
               "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
        def run(*args: str, payload: str = "", timeout: int = 15) -> str:
            result = subprocess.run([str(helper), *args], input=payload, capture_output=True,
                                    text=True, env=env, timeout=timeout, check=True)
            return result.stdout

        with sqlite3.connect(codex / "state_5.sqlite") as db:
            db.execute("CREATE TABLE threads(model TEXT, tokens_used INTEGER)")
            db.execute("INSERT INTO threads VALUES ('fixture', 42)")
        run("--check")
        trust = json.loads(run("--check-tls"))
        assert trust["ok"] and trust["ca_certificates"] > 0
        assert trust["certificate_verification"] and trust["hostname_verification"]
        if https:
            assert json.loads(run("--check-https", timeout=40))["ok"]
        replies = {r["id"]: r for r in map(json.loads, run("--sources", "codex", payload=(
            '{"id":1,"action":"hello"}\n'
            '{"id":2,"action":"report","report":"local-usage"}\n'
        )).splitlines())}
        assert replies[1]["result"]["protocol"] == 1
        assert replies[1]["result"]["bundled_python"] is (not development), "Helper does not match the requested build mode"
        if development:
            assert not (helper.parent / "_internal").exists(), "Development bundle retained frozen libraries"
        assert replies[2]["result"]["data"]["sqlite_threads"]["selected"]["tokens_used_sum"] == 42
        run("--statusline", "--install")
        command = json.loads((claude / "settings.json").read_text())["statusLine"]["command"]
        assert ("claude_usage_statusline.py" if development else "--statusline") in command
        payload = '{"rate_limits":{"five_hour":{"used_percentage":12,"resets_at":2000000000}}}'
        run("--statusline", payload=payload)
        assert json.loads((claude / "usage-dashboard.json").read_text())["rate_limits"]["five_hour"]["used_percentage"] == 12
        run("--statusline", "--uninstall")
        assert "statusLine" not in json.loads((claude / "settings.json").read_text())
        run("--refresh-claude", "--help")
        run("--codex", "export", "--report", "local-usage", "--format", "json", "--output-dir", str(home / "exports"))
        assert len(list((home / "exports").glob("*.json"))) == 1
    print("Bundle checks passed: CA trust, private pipes, SQLite, capture, refresher entry point and CLI export."
          + (" Public HTTPS probes passed." if https else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--https", action="store_true", help="Also probe public HTTPS without account data")
    parser.add_argument("--development", action="store_true", help="Check the source-backed helper and absence of frozen libraries")
    args = parser.parse_args()
    check(args.app, https=args.https, development=args.development)
