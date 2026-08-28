from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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

            with patch.object(refresher.subprocess, "Popen") as spawn:
                result = refresher.run_once(
                    project=root,
                    snapshot=snapshot,
                    state_path=state_path,
                    claude_binary=Path("/fake/claude"),
                    min_age_seconds=600,
                    reset_grace_seconds=30,
                    retry_base_seconds=300,
                    startup_delay_seconds=0,
                    timeout_seconds=1,
                    exit_grace_seconds=1,
                    force=False,
                    quiet=True,
                )

            self.assertEqual(result, 0)
            spawn.assert_not_called()


class UsageScreenParserTest(unittest.TestCase):
    BOTH_WINDOWS = (
        b"Current session 41% used Resets 1pm "
        b"Current week (all models) 52% used Resets Aug 30 at 5pm"
    )

    def test_parses_both_windows(self) -> None:
        windows = refresher.parse_usage_screen(self.BOTH_WINDOWS)

        self.assertEqual(windows["five_hour"]["used_percentage"], 41.0)
        self.assertEqual(windows["seven_day"]["used_percentage"], 52.0)

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


if __name__ == "__main__":
    unittest.main()
