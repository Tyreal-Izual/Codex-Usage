from __future__ import annotations

import unittest

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
                    reset_retry_seconds=300,
                )
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
