from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import claude_usage_refresher as refresher


class ResetAwareRefreshTest(unittest.TestCase):
    def test_reset_becomes_due_only_after_grace_period(self) -> None:
        snapshot = {
            "rate_limits": {
                "five_hour": {"resets_at": 970},
                "seven_day": {"resets_at": 1_500},
            }
        }

        self.assertIsNone(
            refresher.reset_due_epoch(snapshot, now_epoch=999, grace_seconds=30)
        )
        self.assertEqual(
            refresher.reset_due_epoch(snapshot, now_epoch=1_000, grace_seconds=30),
            970,
        )

    def test_reset_parser_ignores_invalid_values(self) -> None:
        snapshot = {
            "rate_limits": {
                "five_hour": {"resets_at": True},
                "seven_day": {"resets_at": "970"},
            }
        }

        self.assertIsNone(
            refresher.reset_due_epoch(snapshot, now_epoch=2_000, grace_seconds=0)
        )

    def test_refresh_decision_table(self) -> None:
        cases = (
            ("forced", True, 10, None, {}, "force"),
            ("fresh", False, 599, None, {}, None),
            ("regular age", False, 600, None, {}, "regular"),
            ("missing snapshot", False, None, None, {}, "regular"),
            ("due reset overrides fresh age", False, 10, 970, {}, "reset_due"),
            (
                "same reset cooling down",
                False,
                10,
                970,
                {"reset_epoch": 970, "last_attempt_at_epoch": 900},
                None,
            ),
            (
                "same reset retries after cooldown",
                False,
                10,
                970,
                {"reset_epoch": 970, "last_attempt_at_epoch": 700},
                "reset_due",
            ),
            (
                "new reset bypasses old cooldown",
                False,
                10,
                970,
                {"reset_epoch": 500, "last_attempt_at_epoch": 990},
                "reset_due",
            ),
        )
        for name, force, age, due_reset, state, expected in cases:
            with self.subTest(name=name):
                actual = refresher.refresh_decision(
                    force=force,
                    snapshot_age=age,
                    due_reset=due_reset,
                    state=state,
                    now_epoch=1_000,
                    min_age_seconds=600,
                    retry_base_seconds=300,
                )
                self.assertEqual(actual, expected)

    def test_regular_refresh_obeys_failure_cooldown(self) -> None:
        state = {
            "last_attempt_at_epoch": 999,
            "last_exit_code": 1,
            "consecutive_failures": 1,
        }
        for age in (600, 720, 3_600):
            with self.subTest(snapshot_age=age):
                self.assertIsNone(
                    refresher.refresh_decision(
                        force=False,
                        snapshot_age=age,
                        due_reset=None,
                        state=state,
                        now_epoch=1_000,
                        min_age_seconds=600,
                        retry_base_seconds=300,
                    )
                )

    def test_failure_backoff_doubles_and_caps_at_forty_minutes(self) -> None:
        expected = {
            1: 300,
            2: 600,
            3: 1_200,
            4: 2_400,
            10: 2_400,
        }
        for failures, seconds in expected.items():
            with self.subTest(failures=failures):
                state = {"last_exit_code": 1, "consecutive_failures": failures}
                self.assertEqual(refresher.failure_backoff_seconds(state, 300), seconds)
        self.assertEqual(
            refresher.failure_backoff_seconds(
                {"last_exit_code": 0, "consecutive_failures": 5},
                300,
            ),
            0,
        )
        self.assertEqual(
            refresher.consecutive_failure_count({"consecutive_failures": float("nan")}),
            0,
        )

    def test_regular_refresh_retries_when_cooldown_expires(self) -> None:
        self.assertEqual(
            refresher.refresh_decision(
                force=False,
                snapshot_age=3_600,
                due_reset=None,
                state={
                    "last_attempt_at_epoch": 700,
                    "last_exit_code": 1,
                    "consecutive_failures": 1,
                },
                now_epoch=1_000,
                min_age_seconds=600,
                retry_base_seconds=300,
            ),
            "regular",
        )

    def test_running_attempt_is_treated_as_a_failure_after_a_crash(self) -> None:
        state = {
            "last_attempt_at_epoch": 999,
            "last_exit_code": "running",
            "consecutive_failures": 1,
        }
        self.assertIsNone(
            refresher.refresh_decision(
                force=False,
                snapshot_age=3_600,
                due_reset=None,
                state=state,
                now_epoch=1_000,
                min_age_seconds=600,
                retry_base_seconds=300,
            )
        )

    def test_recent_regular_failure_does_not_spawn_claude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "usage-dashboard.json"
            state_path = root / "usage-dashboard-refresh-state.json"
            snapshot.write_text(json.dumps({"rate_limits": {}}), encoding="utf-8")
            old = time.time() - 3_600
            os.utime(snapshot, (old, old))
            state_path.write_text(
                json.dumps(
                    {
                        "last_attempt_at_epoch": time.time() - 1,
                        "last_exit_code": 1,
                        "consecutive_failures": 1,
                    }
                ),
                encoding="utf-8",
            )

            # This checks retry scheduling, independently of POSIX file locking.
            locking = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=Mock())
            with (
                patch.object(refresher, "fcntl", locking),
                patch.object(refresher.subprocess, "Popen") as spawn,
            ):
                result = refresher.run_once(
                    project=root,
                    snapshot=snapshot,
                    state_path=state_path,
                    claude_binary=Path("/fake/claude"),
                    min_age_seconds=600,
                    reset_grace_seconds=30,
                    retry_base_seconds=300,
                    ready_timeout_seconds=30,
                    startup_delay_seconds=0,
                    timeout_seconds=1,
                    exit_grace_seconds=1,
                    force=False,
                    quiet=True,
                )

            self.assertEqual(result, 0)
            spawn.assert_not_called()
            self.assertEqual([call.args[1] for call in locking.flock.call_args_list], [6, 8])


class RefresherLockTest(unittest.TestCase):
    def call_once(self, root: Path) -> int:
        return refresher.run_once(
            project=root,
            snapshot=root / "usage-dashboard.json",
            state_path=root / "refresh-state.json",
            claude_binary=root / "fake-claude",
            min_age_seconds=600,
            reset_grace_seconds=30,
            retry_base_seconds=300,
            ready_timeout_seconds=30,
            startup_delay_seconds=0,
            timeout_seconds=1,
            exit_grace_seconds=1,
            force=False,
            quiet=True,
        )

    def test_unsupported_platform_returns_cleanly_without_files_or_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(refresher, "fcntl", None),
                patch.object(refresher.subprocess, "Popen") as spawn,
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(self.call_once(root), 2)
                self.assertIn("requires macOS or POSIX", stderr.getvalue())
                with self.assertRaisesRegex(OSError, "requires macOS or POSIX"):
                    refresher.acquire_lock(root / "nested" / "snapshot.json")
            spawn.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_lock_contention_and_failure_both_close_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            for error in (BlockingIOError("busy"), OSError("lock failed")):
                with self.subTest(error=type(error).__name__):
                    handle = Mock()
                    locking = SimpleNamespace(
                        LOCK_EX=2, LOCK_NB=4, flock=Mock(side_effect=error)
                    )
                    with (
                        patch.object(refresher, "fcntl", locking),
                        patch.object(Path, "open", return_value=handle),
                    ):
                        if isinstance(error, BlockingIOError):
                            self.assertIsNone(refresher.acquire_lock(snapshot))
                        else:
                            with self.assertRaisesRegex(OSError, "lock failed"):
                                refresher.acquire_lock(snapshot)
                    handle.close.assert_called_once()

    def test_unlock_failure_still_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            handle = Mock()
            locking = SimpleNamespace(LOCK_UN=8, flock=Mock(side_effect=OSError("unlock failed")))
            with (
                patch.object(refresher, "fcntl", locking),
                patch.object(refresher, "acquire_lock", return_value=handle),
                patch.object(refresher, "refresh_decision", return_value=None),
            ):
                with self.assertRaisesRegex(OSError, "unlock failed"):
                    self.call_once(Path(directory))
            handle.close.assert_called_once()


class RefresherOutputTest(unittest.TestCase):
    SCREEN = b"Current session 41% used Resets 1pm Current week (all models) 52% used Resets Aug 30 at 5pm"

    def capture(self, root, spawn, stop):
        snapshot = root / "usage-dashboard.json"
        snapshot.write_text(json.dumps({"claude_version": "fixture"}))
        locking = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=Mock())
        with (patch.object(refresher, "fcntl", locking),
              patch.object(refresher, "resolve_expect_binary", return_value=Path(sys.executable)),
              patch.object(refresher.subprocess, "Popen", side_effect=spawn),
              patch.object(refresher, "stop_process", side_effect=stop) as stopped,
              patch("sys.stderr", new_callable=io.StringIO)):
            result = refresher.run_once(project=root, snapshot=snapshot, state_path=root / "state.json",
                claude_binary=root / "fixture", min_age_seconds=600, reset_grace_seconds=30,
                retry_base_seconds=300, ready_timeout_seconds=0, startup_delay_seconds=0,
                timeout_seconds=0, exit_grace_seconds=0, force=True, quiet=True)
        self.assertEqual(result, 0)
        saved = json.loads(snapshot.read_text())
        self.assertEqual(saved["rate_limits"]["seven_day"]["used_percentage"], 52)
        return stopped

    def test_large_stdout_and_stderr_do_not_block_capture(self):
        real_spawn = subprocess.Popen
        def spawn(*args, **kwargs):
            script = ("import sys; sys.stdout.write('x'*262144); sys.stdout.flush(); "
                      "sys.stderr.write('y'*262144); sys.stderr.flush(); "
                      f"sys.stdout.buffer.write({self.SCREEN!r}); sys.stdout.flush()")
            process = real_spawn([sys.executable, "-c", script], **kwargs)
            self.addCleanup(process.stdout.close)
            self.addCleanup(process.stderr.close)
            return process
        def stop(process):
            process.kill()
            process.wait(timeout=3)
        with tempfile.TemporaryDirectory() as directory:
            stopped = self.capture(Path(directory), spawn, stop)
        stopped.assert_not_called()

    def test_timeout_preserves_output_already_captured(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 5), (self.SCREEN, b'')]
        with tempfile.TemporaryDirectory() as directory:
            stopped = self.capture(Path(directory), lambda *args, **kwargs: process, lambda p: None)
        stopped.assert_called_once_with(process)

    def test_pipe_left_open_after_timeout_has_bounded_cleanup(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 5),
            subprocess.TimeoutExpired('fixture', 5, output=self.SCREEN, stderr=b'fixture')]
        with tempfile.TemporaryDirectory() as directory:
            stopped = self.capture(Path(directory), lambda *args, **kwargs: process, lambda p: None)
        stopped.assert_called_once_with(process)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()


class UsageScreenParserTest(unittest.TestCase):
    BOTH_WINDOWS = (
        b"Current session 41% used Resets 1pm "
        b"Current week (all models) 52% used Resets Aug 30 at 5pm"
    )

    def test_parses_both_windows(self) -> None:
        windows = refresher.parse_usage_screen(self.BOTH_WINDOWS)

        self.assertEqual(windows["five_hour"]["used_percentage"], 41.0)
        self.assertEqual(windows["seven_day"]["used_percentage"], 52.0)

    def test_uses_latest_explicitly_labelled_values(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current session 12% 12% used Resets 6am "
            b"Current week (all models) 4% 4% used Resets Sep 11 at 5pm "
            b"Scanning local sessions Refreshing Esc to cancel "
            b"13% 13% used Resets 5:59am "
            b"Current week (all models) 5% 5% used Resets Sep 11 at 4:59pm"
        )

        self.assertEqual(windows["five_hour"]["used_percentage"], 12.0)
        self.assertEqual(windows["seven_day"]["used_percentage"], 5.0)

    def test_unlabelled_weekly_refresh_is_not_assigned_to_five_hour(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current session 0% 0% used Resets 3:10am "
            b"Current week (all models) 11% 11% used Resets Sep 11 at 5pm "
            b"Scanning local sessions Refreshing Esc to cancel "
            b"12% 12% used Resets Sep 11 at 4:59pm"
        )

        self.assertEqual(windows["five_hour"]["used_percentage"], 0.0)
        self.assertNotEqual(
            windows["five_hour"].get("resets_at"),
            windows["seven_day"].get("resets_at"),
        )

    def test_accepts_weekly_only(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current week (all models) 52% used Resets Aug 30 at 5pm"
        )

        self.assertEqual(set(windows), {"seven_day"})
        self.assertEqual(windows["seven_day"]["used_percentage"], 52.0)

    def test_accepts_session_only(self) -> None:
        windows = refresher.parse_usage_screen(b"Current session 41% used Resets 1pm")

        self.assertEqual(set(windows), {"five_hour"})
        self.assertEqual(windows["five_hour"]["used_percentage"], 41.0)

    def test_model_allowances_do_not_overwrite_weekly_total(self) -> None:
        for model in ("Fable", "Sonnet", "Opus", "Future model"):
            with self.subTest(model=model):
                windows = refresher.parse_usage_screen(
                    b"Current session\n4% 4% used\nResets 4:40pm (Europe/London)\n"
                    b"Current week (all models)\n8% 8% used\n"
                    b"Resets Nov 13 at 4pm (Europe/London)\n"
                    + f"Esc to cancelCurrent week ({model})\n".encode()
                    + b"0% 0% used\nResets Nov 14 at 5pm (Europe/London)"
                )

                self.assertEqual(set(windows), {"five_hour", "seven_day"})
                self.assertEqual(windows["five_hour"]["used_percentage"], 4.0)
                self.assertEqual(windows["seven_day"]["used_percentage"], 8.0)
                self.assertEqual(
                    windows["seven_day"]["resets_at"],
                    refresher.parse_reset_time("Nov 13 at 4pm (Europe/London)"),
                )

    def test_model_allowance_alone_is_not_a_weekly_total(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid subscription window"):
            refresher.parse_usage_screen(
                b"Current week (Fable) 0% used Resets Nov 13 at 4pm"
            )

    def test_partial_total_cannot_borrow_model_percentage_or_reset(self) -> None:
        for total in (b"", b"8% used"):
            with self.subTest(total=total):
                windows = refresher.parse_usage_screen(
                    b"Current session 4% used Resets 4:40pm "
                    b"Current week (all models) " + total
                    + b" Current week (Fable) 0% used Resets Nov 13 at 4pm"
                )

                self.assertEqual(set(windows), {"five_hour"})

    def test_latest_total_survives_model_allowance_rerenders(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current week (Fable) 1% used Resets Nov 13 at 4pm "
            b"Current week (all models) 8% used Resets Nov 13 at 4pm "
            b"Current week (all models) 9% used Resets Nov 13 at 4pm "
            b"Current week (Fable) 2% used Resets Nov 13 at 4pm"
        )

        self.assertEqual(windows["seven_day"]["used_percentage"], 9.0)

    def test_unqualified_week_is_still_supported(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current week 8% used Resets Nov 13 at 4pm "
            b"Current week (Fable) 0% used Resets Nov 13 at 4pm"
        )

        self.assertEqual(windows["seven_day"]["used_percentage"], 8.0)

    def test_numeric_progress_bar_cannot_pollute_percentage(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current session 123441% used Resets 1pm "
            b"Current week (all models) 52% used Resets Aug 30 at 5pm"
        )

        self.assertEqual(set(windows), {"seven_day"})
        self.assertEqual(windows["seven_day"]["used_percentage"], 52.0)

    def test_numeric_weekly_progress_bar_does_not_discard_session(self) -> None:
        windows = refresher.parse_usage_screen(
            b"Current session 41% used Resets 1pm "
            b"Current week (all models) 123452% used Resets Aug 30 at 5pm"
        )

        self.assertEqual(set(windows), {"five_hour"})
        self.assertEqual(windows["five_hour"]["used_percentage"], 41.0)

    def test_rejects_out_of_range_percentage(self) -> None:
        self.assertIsNone(refresher.percentage("101"))
        self.assertIsNone(refresher.percentage("-1"))
        self.assertEqual(refresher.percentage("100"), 100.0)

    def test_fails_only_when_no_valid_window_exists(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid subscription window"):
            refresher.parse_usage_screen(b"Current session 101% used Resets 1pm")

    def test_partial_snapshot_does_not_retain_missing_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "usage-dashboard.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "claude_version": "test",
                        "rate_limits": {
                            "five_hour": {"used_percentage": 10},
                            "seven_day": {"used_percentage": 20},
                        },
                    }
                ),
                encoding="utf-8",
            )

            refresher.write_usage_snapshot(
                snapshot,
                {"seven_day": {"used_percentage": 52.0}},
                Path("/fake/claude"),
            )
            saved = json.loads(snapshot.read_text(encoding="utf-8"))

        self.assertEqual(set(saved["rate_limits"]), {"seven_day"})


class ExpectProgramTest(unittest.TestCase):
    def test_waits_for_prompt_and_disables_remote_control(self) -> None:
        self.assertIn('--settings {{"disableRemoteControl":true}}', refresher.EXPECT_PROGRAM)
        self.assertIn("--ax-screen-reader", refresher.EXPECT_PROGRAM)
        self.assertIn("-exact {$}", refresher.EXPECT_PROGRAM)
        self.assertIn('send -- "/usage"', refresher.EXPECT_PROGRAM)


if __name__ == "__main__":
    unittest.main()
