#!/usr/bin/env python3
"""Refresh the Claude Code subscription-usage snapshot on macOS.

Claude Code only invokes custom statusLine commands while its terminal client
is running. This helper opens a temporary empty session in a pseudo-terminal,
runs Claude Code's local ``/usage`` command, parses only its limit percentages
and reset times, and writes the same sanitised snapshot format without
submitting a prompt to the model.

The optional launchd integration probes the local snapshot once per minute,
runs a normal refresh about every ten minutes, and can refresh shortly after a
recorded reset deadline. It is intentionally separate from the Codex
collectors and web server.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import claude_usage_statusline


LAUNCH_AGENT_LABEL = "com.tyreal.codex-usage.claude-refresh"
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_MIN_AGE_SECONDS = 10 * 60
DEFAULT_RESET_GRACE_SECONDS = 30
DEFAULT_RETRY_BASE_SECONDS = 5 * 60
MAX_RETRY_MULTIPLIER = 8
DEFAULT_STARTUP_DELAY_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_EXIT_GRACE_SECONDS = 8

EXPECT_PROGRAM = r"""
log_user 1
set timeout 1

spawn -noecho $env(CLAUDE_REFRESH_BIN) --no-chrome
after $env(CLAUDE_REFRESH_STARTUP_MS)
send -- "/usage\r"
after $env(CLAUDE_REFRESH_HOLD_MS)

catch {send -- "\004"}
set timeout $env(CLAUDE_REFRESH_EXIT_GRACE)
set exited 0
expect {
    eof { set exited 1 }
    timeout {}
}
if {!$exited} {
    catch {send -- "\003"}
    after 500
    catch {close}
    catch {wait}
}
exit 0
"""

ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
PERCENT_USED_PATTERN = r"(?<!\d)(\d{1,3}(?:\.\d+)?)%used"
SESSION_USAGE_RE = re.compile(
    r"Currentsession(?:(?!Currentweek).)*?" + PERCENT_USED_PATTERN
    + r"(?:(?!Currentweek).)*?Resets(.*?)(?=Currentweek|What.?scontributing|$)",
    re.IGNORECASE | re.DOTALL,
)
WEEKLY_USAGE_RE = re.compile(
    r"Currentweek(?:\(allmodels\))?.*?" + PERCENT_USED_PATTERN + r".*?Resets"
    r"(.*?)(?=(?:\+\d+(?:\.\d+)?%weekly|What.?scontributing|$))",
    re.IGNORECASE | re.DOTALL,
)
MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    )
    if name
}


def project_directory() -> Path:
    configured = os.environ.get("CLAUDE_USAGE_PROJECT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def log_directory() -> Path:
    return claude_usage_statusline.resolve_claude_home()


def snapshot_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        value = path.stat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mtime_ns, value.st_size)


def snapshot_age_seconds(path: Path) -> float | None:
    try:
        modified_at = path.stat().st_mtime
    except FileNotFoundError:
        return None
    return max(0.0, time.time() - modified_at)


def refresh_state_path(snapshot: Path) -> Path:
    return snapshot.with_name(f"{snapshot.stem}-refresh-state.json")


def finite_epoch(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def consecutive_failure_count(state: dict[str, object]) -> int:
    value = state.get("consecutive_failures")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = float(value)
    return max(0, int(number)) if math.isfinite(number) else 0


def failure_backoff_seconds(state: dict[str, object], retry_base_seconds: int) -> int:
    exit_code = state.get("last_exit_code")
    succeeded = (
        not isinstance(exit_code, bool)
        and isinstance(exit_code, (int, float))
        and exit_code == 0
    )
    if exit_code is None or succeeded:
        return 0
    failures = max(1, consecutive_failure_count(state))
    multiplier = min(2 ** min(failures - 1, 3), MAX_RETRY_MULTIPLIER)
    return retry_base_seconds * multiplier


def reset_due_epoch(
    snapshot: dict[str, object],
    *,
    now_epoch: float,
    grace_seconds: int,
) -> int | None:
    limits = snapshot.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    due: list[int] = []
    for key in ("five_hour", "seven_day"):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        resets_at = finite_epoch(window.get("resets_at"))
        if resets_at is not None and resets_at + grace_seconds <= now_epoch:
            due.append(int(resets_at))
    return min(due) if due else None


def refresh_decision(
    *,
    force: bool,
    snapshot_age: float | None,
    due_reset: int | None,
    state: dict[str, object],
    now_epoch: float,
    min_age_seconds: int,
    retry_base_seconds: int,
) -> str | None:
    if force:
        return "force"
    attempted_at = finite_epoch(state.get("last_attempt_at_epoch"))
    backoff_seconds = failure_backoff_seconds(state, retry_base_seconds)
    failure_cooling_down = (
        attempted_at is not None
        and backoff_seconds > 0
        and now_epoch - attempted_at < backoff_seconds
    )
    if due_reset is not None:
        attempted_reset = finite_epoch(state.get("reset_epoch"))
        same_reset = attempted_reset is not None and int(attempted_reset) == due_reset
        same_reset_cooling_down = (
            same_reset
            and attempted_at is not None
            and now_epoch - attempted_at < retry_base_seconds
        )
        return None if failure_cooling_down or same_reset_cooling_down else "reset_due"
    if snapshot_age is None or snapshot_age >= min_age_seconds:
        return None if failure_cooling_down else "regular"
    return None


def previous_refresh_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def write_refresh_state(path: Path, state: dict[str, object]) -> None:
    claude_usage_statusline.atomic_write_json(path, state)


def strip_terminal_codes(value: bytes) -> str:
    text = value.decode("utf-8", errors="ignore")
    text = ANSI_OSC_RE.sub("", text)
    text = ANSI_CSI_RE.sub("", text)
    return text.replace("\r", "\n")


def percentage(value: str) -> float | None:
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 100 else None


def hour_24(hour: int, meridiem: str) -> int:
    hour %= 12
    return hour + (12 if meridiem.lower() == "pm" else 0)


def timezone_from_reset(value: str) -> timezone | ZoneInfo:
    match = re.search(r"\(([^()]+)\)", value)
    if match:
        try:
            return ZoneInfo(match.group(1))
        except ZoneInfoNotFoundError:
            pass
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else timezone.utc


def parse_reset_time(value: str, now: datetime | None = None) -> int | None:
    zone = timezone_from_reset(value)
    current = (now or datetime.now(tz=zone)).astimezone(zone)
    compact = re.sub(r"[^A-Za-z0-9:]", "", re.sub(r"\([^()]+\)", "", value))

    dated = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"(\d{1,2})(?:at)?(\d{1,2})(?::(\d{2}))?(am|pm)",
        compact,
        re.IGNORECASE,
    )
    if dated:
        month_name, day, hour, minute, meridiem = dated.groups()
        candidate = datetime(
            current.year,
            MONTHS[month_name.lower()],
            int(day),
            hour_24(int(hour), meridiem),
            int(minute or 0),
            tzinfo=zone,
        )
        if candidate < current - timedelta(days=1):
            candidate = candidate.replace(year=current.year + 1)
        return int(candidate.timestamp())

    time_only = re.search(r"(\d{1,2})(?::(\d{2}))?(am|pm)", compact, re.IGNORECASE)
    if not time_only:
        return None
    hour, minute, meridiem = time_only.groups()
    candidate = current.replace(
        hour=hour_24(int(hour), meridiem),
        minute=int(minute or 0),
        second=0,
        microsecond=0,
    )
    if "tomorrow" in compact.lower() or candidate <= current:
        candidate += timedelta(days=1)
    return int(candidate.timestamp())


def parse_usage_screen(value: bytes) -> dict[str, dict[str, float | int]]:
    compact = re.sub(r"\s+", "", strip_terminal_codes(value))
    session = SESSION_USAGE_RE.search(compact)
    weekly = WEEKLY_USAGE_RE.search(compact)

    windows: dict[str, dict[str, float | int]] = {}
    for key, match in (("five_hour", session), ("seven_day", weekly)):
        if match is None:
            continue
        used_percentage = percentage(match.group(1))
        if used_percentage is None:
            continue
        window: dict[str, float | int] = {"used_percentage": used_percentage}
        resets_at = parse_reset_time(match.group(2))
        if resets_at is not None:
            window["resets_at"] = resets_at
        windows[key] = window
    if not windows:
        raise ValueError("Claude /usage output did not contain a valid subscription window.")
    return windows


def previous_snapshot(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def write_usage_snapshot(
    path: Path,
    windows: dict[str, dict[str, float | int]],
    claude_binary: Path,
) -> None:
    previous = previous_snapshot(path)
    previous_limits = previous.get("rate_limits")
    previous_limits = previous_limits if isinstance(previous_limits, dict) else {}
    now = time.time()

    for key, window in windows.items():
        if "resets_at" in window:
            continue
        old_window = previous_limits.get(key)
        old_reset = old_window.get("resets_at") if isinstance(old_window, dict) else None
        if (
            not isinstance(old_reset, bool)
            and isinstance(old_reset, (int, float))
            and old_reset > now
        ):
            window["resets_at"] = int(old_reset)

    snapshot: dict[str, object] = {
        "schema_version": 1,
        "source": "claude_code_usage_command",
        "captured_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "captured_at_epoch": now,
        "claude_version": str(previous.get("claude_version") or ""),
        "model": previous.get("model") if isinstance(previous.get("model"), dict) else {},
        "rate_limits": windows,
    }
    if "plan_type" in previous:
        snapshot["plan_type"] = previous["plan_type"]
    if not snapshot["claude_version"]:
        try:
            result = subprocess.run(
                [str(claude_binary), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            snapshot["claude_version"] = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    claude_usage_statusline.atomic_write_json(path, snapshot)


def capture_is_installed() -> bool:
    settings_path = claude_usage_statusline.resolve_claude_home() / "settings.json"
    try:
        settings = claude_usage_statusline.load_settings(settings_path)
    except SystemExit:
        return False
    return claude_usage_statusline.is_ours(settings.get("statusLine"))


def resolve_claude_binary(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    configured = os.environ.get("CLAUDE_BIN")
    if configured:
        candidates.append(Path(configured).expanduser())
    discovered = shutil.which("claude")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        (
            Path.home() / ".local" / "bin" / "claude",
            Path("/opt/homebrew/bin/claude"),
            Path("/usr/local/bin/claude"),
        )
    )

    checked: set[Path] = set()
    for candidate in candidates:
        executable = candidate.absolute()
        if executable in checked:
            continue
        checked.add(executable)
        if executable.is_file() and os.access(executable, os.X_OK):
            # Keep Claude's public launcher path instead of resolving its
            # versioned symlink. The native installer may rely on argv[0].
            return executable
    raise FileNotFoundError(
        "Could not find the Claude Code executable. Pass --claude-bin or set CLAUDE_BIN."
    )


def acquire_lock(snapshot: Path) -> BinaryIO | None:
    lock_path = snapshot.with_name(f".{snapshot.name}.refresh.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def resolve_expect_binary() -> Path:
    candidates = (Path("/usr/bin/expect"), Path(shutil.which("expect") or ""))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise FileNotFoundError(
        "Could not find expect. The automatic refresher requires the macOS /usr/bin/expect tool."
    )


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def run_once(
    *,
    project: Path,
    snapshot: Path,
    state_path: Path,
    claude_binary: Path,
    min_age_seconds: int,
    reset_grace_seconds: int,
    retry_base_seconds: int,
    startup_delay_seconds: int,
    timeout_seconds: int,
    exit_grace_seconds: int,
    force: bool,
    quiet: bool,
) -> int:
    if not project.is_dir():
        print(f"Project directory does not exist: {project}", file=sys.stderr)
        return 2
    lock_handle = acquire_lock(snapshot)
    if lock_handle is None:
        if not quiet:
            print("A Claude usage refresh is already running; skipped.")
        return 0

    try:
        now_epoch = time.time()
        age = snapshot_age_seconds(snapshot)
        snapshot_value = previous_snapshot(snapshot)
        due_reset = reset_due_epoch(
            snapshot_value,
            now_epoch=now_epoch,
            grace_seconds=reset_grace_seconds,
        )
        refresh_state = previous_refresh_state(state_path)
        decision = refresh_decision(
            force=force,
            snapshot_age=age,
            due_reset=due_reset,
            state=refresh_state,
            now_epoch=now_epoch,
            min_age_seconds=min_age_seconds,
            retry_base_seconds=retry_base_seconds,
        )
        if decision is None:
            if not quiet:
                if due_reset is not None:
                    print("Reset-aware refresh is cooling down; no refresh is needed.")
                elif age is not None:
                    print(f"Snapshot is {age:.0f}s old; no refresh is needed.")
            return 0

        refresh_state.update(
            {
                "schema_version": 1,
                "last_attempt_at_epoch": now_epoch,
                "last_attempt_reason": decision,
                "last_exit_code": "running",
                "consecutive_failures": consecutive_failure_count(refresh_state) + 1,
            }
        )
        if due_reset is not None:
            refresh_state["reset_epoch"] = due_reset
        try:
            write_refresh_state(state_path, refresh_state)
        except OSError as exc:
            print(f"Could not write refresh state {state_path}: {exc}", file=sys.stderr)

        previous_signature = snapshot_signature(snapshot)
        started_at = time.monotonic()
        try:
            expect_binary = resolve_expect_binary()
        except FileNotFoundError as exc:
            refresh_state["last_exit_code"] = 2
            try:
                write_refresh_state(state_path, refresh_state)
            except OSError:
                pass
            print(str(exc), file=sys.stderr)
            return 2

        environment = os.environ.copy()
        environment.update(
            {
                "TERM": environment.get("TERM") or "xterm-256color",
                "CLAUDE_REFRESH_BIN": str(claude_binary),
                "CLAUDE_REFRESH_STARTUP_MS": str(startup_delay_seconds * 1000),
                "CLAUDE_REFRESH_HOLD_MS": str(timeout_seconds * 1000),
                "CLAUDE_REFRESH_EXIT_GRACE": str(exit_grace_seconds),
            }
        )
        process = subprocess.Popen(
            [str(expect_binary), "-c", EXPECT_PROGRAM],
            cwd=project,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        maximum_runtime = startup_delay_seconds + timeout_seconds + exit_grace_seconds + 5
        try:
            process.wait(timeout=maximum_runtime)
        except subprocess.TimeoutExpired:
            stop_process(process)

        elapsed = time.monotonic() - started_at
        terminal_output = b""
        if process.stdout is not None:
            terminal_output = process.stdout.read()
        parse_error = ""
        try:
            windows = parse_usage_screen(terminal_output)
            write_usage_snapshot(snapshot, windows, claude_binary)
        except (OSError, ValueError) as exc:
            parse_error = str(exc)
        updated = snapshot_signature(snapshot) != previous_signature
        if updated:
            refresh_state.update(
                {
                    "last_exit_code": 0,
                    "last_success_at_epoch": time.time(),
                    "consecutive_failures": 0,
                }
            )
            try:
                write_refresh_state(state_path, refresh_state)
            except OSError as exc:
                print(f"Could not write refresh state {state_path}: {exc}", file=sys.stderr)
            if not quiet:
                print(f"Claude usage snapshot refreshed ({decision}) in {elapsed:.1f}s.")
            return 0

        diagnostic = ""
        if process.stderr is not None:
            diagnostic = process.stderr.read(2_000).decode("utf-8", errors="replace").strip()
        if diagnostic:
            print(f"expect failed: {diagnostic}", file=sys.stderr)
        if parse_error:
            print(f"Could not parse Claude /usage: {parse_error}", file=sys.stderr)
        print(
            f"Claude Code exited or timed out after {elapsed:.1f}s without updating {snapshot}.",
            file=sys.stderr,
        )
        refresh_state["last_exit_code"] = 1
        try:
            write_refresh_state(state_path, refresh_state)
        except OSError as exc:
            print(f"Could not write refresh state {state_path}: {exc}", file=sys.stderr)
        return 1
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def launchctl_path() -> str:
    path = shutil.which("launchctl")
    if not path:
        raise FileNotFoundError("launchctl is not available; automatic refresh requires macOS.")
    return path


def launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [launchctl_path(), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def launch_domain() -> str:
    return f"gui/{os.getuid()}"


def write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def install_launch_agent(
    *,
    project: Path,
    snapshot: Path,
    state_path: Path,
    claude_binary: Path,
    interval_seconds: int,
    min_age_seconds: int,
    reset_grace_seconds: int,
    retry_base_seconds: int,
    startup_delay_seconds: int,
    timeout_seconds: int,
    exit_grace_seconds: int,
) -> int:
    if sys.platform != "darwin":
        print("Automatic installation is currently supported only on macOS.", file=sys.stderr)
        return 2
    agent_path = launch_agent_path()
    logs = log_directory()
    logs.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    python = Path(sys.executable).resolve()
    arguments = [
        str(python),
        str(script),
        "--once",
        "--quiet",
        "--project-dir",
        str(project),
        "--snapshot",
        str(snapshot),
        "--state",
        str(state_path),
        "--claude-bin",
        str(claude_binary),
        "--min-age",
        str(min_age_seconds),
        "--reset-grace",
        str(reset_grace_seconds),
        "--retry-base",
        str(retry_base_seconds),
        "--startup-delay",
        str(startup_delay_seconds),
        "--timeout",
        str(timeout_seconds),
        "--exit-grace",
        str(exit_grace_seconds),
    ]
    environment = {
        "HOME": str(Path.home()),
        "PATH": ":".join(
            (
                str(claude_binary.parent),
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            )
        ),
        "TERM": "xterm-256color",
    }
    for name in ("CLAUDE_CONFIG_DIR", "CLAUDE_USAGE_SNAPSHOT"):
        value = os.environ.get(name)
        if value:
            environment[name] = value

    payload: dict[str, object] = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(project),
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "ThrottleInterval": 60,
        "Umask": 0o077,
        "StandardOutPath": str(logs / "usage-refresh.log"),
        "StandardErrorPath": str(logs / "usage-refresh.error.log"),
    }

    write_plist(agent_path, payload)
    domain = launch_domain()
    launchctl("bootout", domain, str(agent_path))
    result = launchctl("bootstrap", domain, str(agent_path))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown launchctl error"
        print(f"Could not load {agent_path}: {detail}", file=sys.stderr)
        return 1
    launchctl("enable", f"{domain}/{LAUNCH_AGENT_LABEL}")

    print(f"Installed and loaded: {agent_path}")
    print(f"Probe schedule: every {interval_seconds} seconds")
    print(f"Regular refresh age: {min_age_seconds} seconds")
    print(f"Reset grace: {reset_grace_seconds} seconds")
    print(f"Failure retry base: {retry_base_seconds} seconds")
    print(f"Project: {project}")
    print(f"Snapshot: {snapshot}")
    print(f"Refresh state: {state_path}")
    return 0


def uninstall_launch_agent() -> int:
    if sys.platform != "darwin":
        print("Automatic installation is currently supported only on macOS.", file=sys.stderr)
        return 2

    agent_path = launch_agent_path()
    launchctl("bootout", launch_domain(), str(agent_path))
    try:
        agent_path.unlink()
    except FileNotFoundError:
        print("Claude usage refresh LaunchAgent is not installed.")
        return 0
    print(f"Removed: {agent_path}")
    return 0


def show_status(snapshot: Path, state_path: Path) -> int:
    agent_path = launch_agent_path()
    loaded = False
    if sys.platform == "darwin":
        result = launchctl("print", f"{launch_domain()}/{LAUNCH_AGENT_LABEL}")
        loaded = result.returncode == 0

    interval: object = "-"
    if agent_path.exists():
        try:
            with agent_path.open("rb") as handle:
                value = plistlib.load(handle)
            interval = value.get("StartInterval", "-") if isinstance(value, dict) else "-"
        except (OSError, plistlib.InvalidFileException):
            interval = "invalid plist"

    age = snapshot_age_seconds(snapshot)
    age_text = "missing" if age is None else f"{age:.0f}s"
    refresh_state = previous_refresh_state(state_path)
    print(f"StatusLine capture installed: {'yes' if capture_is_installed() else 'no'}")
    print(f"LaunchAgent file: {agent_path}")
    print(f"LaunchAgent installed: {'yes' if agent_path.exists() else 'no'}")
    print(f"LaunchAgent loaded: {'yes' if loaded else 'no'}")
    print(f"Probe interval seconds: {interval}")
    print(f"Snapshot: {snapshot}")
    print(f"Snapshot age: {age_text}")
    print(f"Refresh state: {state_path}")
    print(f"Last attempt reason: {refresh_state.get('last_attempt_reason', '-')}")
    print(f"Last exit code: {refresh_state.get('last_exit_code', '-')}")
    print(f"Consecutive failures: {refresh_state.get('consecutive_failures', 0)}")
    return 0


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def non_negative_integer(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh Claude Code subscription limits and manage its macOS schedule."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--once", action="store_true", help="Run one refresh attempt.")
    action.add_argument("--install", action="store_true", help="Install and load the LaunchAgent.")
    action.add_argument("--uninstall", action="store_true", help="Unload and remove the LaunchAgent.")
    action.add_argument("--status", action="store_true", help="Show capture and LaunchAgent status.")
    parser.add_argument("--project-dir", type=Path, default=project_directory())
    parser.add_argument("--snapshot", type=Path, default=claude_usage_statusline.snapshot_path())
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="Refresh-state JSON path. Defaults beside the usage snapshot.",
    )
    parser.add_argument("--claude-bin", type=Path, default=None)
    parser.add_argument(
        "--interval",
        type=positive_integer,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Lightweight LaunchAgent probe interval. Default: {DEFAULT_INTERVAL_SECONDS}.",
    )
    parser.add_argument(
        "--min-age",
        type=non_negative_integer,
        default=DEFAULT_MIN_AGE_SECONDS,
        help=f"Regular refresh age in seconds. Default: {DEFAULT_MIN_AGE_SECONDS}.",
    )
    parser.add_argument(
        "--reset-grace",
        type=non_negative_integer,
        default=DEFAULT_RESET_GRACE_SECONDS,
        help=(
            "Seconds after a recorded reset before refreshing. "
            f"Default: {DEFAULT_RESET_GRACE_SECONDS}."
        ),
    )
    parser.add_argument(
        "--retry-base",
        "--reset-retry",
        dest="retry_base",
        type=positive_integer,
        default=DEFAULT_RETRY_BASE_SECONDS,
        help=(
            "Base cooldown after any failed refresh; doubles up to 8x. "
            f"Default: {DEFAULT_RETRY_BASE_SECONDS}."
        ),
    )
    parser.add_argument(
        "--startup-delay",
        type=non_negative_integer,
        default=DEFAULT_STARTUP_DELAY_SECONDS,
        help=(
            "Seconds to let Claude Code initialise before /usage. "
            f"Default: {DEFAULT_STARTUP_DELAY_SECONDS}."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=positive_integer,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Seconds to keep /usage open before exiting. "
            f"Default: {DEFAULT_TIMEOUT_SECONDS}."
        ),
    )
    parser.add_argument(
        "--exit-grace",
        type=positive_integer,
        default=DEFAULT_EXIT_GRACE_SECONDS,
        help=f"Seconds allowed for a clean Ctrl-D exit. Default: {DEFAULT_EXIT_GRACE_SECONDS}.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --once, refresh even when the current snapshot is still fresh.",
    )
    parser.add_argument("--quiet", action="store_true", help="Hide success and skip messages.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    snapshot = args.snapshot.expanduser().resolve()
    state_path = (
        args.state.expanduser().resolve()
        if args.state is not None
        else refresh_state_path(snapshot)
    )
    project = args.project_dir.expanduser().resolve()

    if args.status:
        return show_status(snapshot, state_path)
    if args.uninstall:
        return uninstall_launch_agent()

    try:
        claude_binary = resolve_claude_binary(args.claude_bin)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.install:
        return install_launch_agent(
            project=project,
            snapshot=snapshot,
            state_path=state_path,
            claude_binary=claude_binary,
            interval_seconds=args.interval,
            min_age_seconds=args.min_age,
            reset_grace_seconds=args.reset_grace,
            retry_base_seconds=args.retry_base,
            startup_delay_seconds=args.startup_delay,
            timeout_seconds=args.timeout,
            exit_grace_seconds=args.exit_grace,
        )
    return run_once(
        project=project,
        snapshot=snapshot,
        state_path=state_path,
        claude_binary=claude_binary,
        min_age_seconds=args.min_age,
        reset_grace_seconds=args.reset_grace,
        retry_base_seconds=args.retry_base,
        startup_delay_seconds=args.startup_delay,
        timeout_seconds=args.timeout,
        exit_grace_seconds=args.exit_grace,
        force=args.force,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    raise SystemExit(main())
