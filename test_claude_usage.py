from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import claude_usage


class ClaudeAuthStatusTest(unittest.TestCase):
    def test_reports_logged_out_without_exposing_identity_fields(self) -> None:
        payload = {
            "loggedIn": False,
            "authMethod": "none",
            "apiProvider": "firstParty",
            "email": "private@example.com",
            "orgId": "private-org-id",
        }
        completed = subprocess.CompletedProcess(
            args=["/fake/claude", "auth", "status"],
            returncode=1,
            stdout=json.dumps(payload),
            stderr="",
        )

        with (
            patch.object(claude_usage, "claude_binary_path", return_value="/fake/claude"),
            patch.object(claude_usage.subprocess, "run", return_value=completed),
        ):
            status = claude_usage.claude_auth_status()

        self.assertEqual(status["logged_in"], False)
        self.assertEqual(status["requires_login"], True)
        self.assertEqual(status["auth_method"], "none")
        self.assertEqual(status["api_provider"], "firstParty")
        self.assertNotIn("email", status)
        self.assertNotIn("org_id", status)

    def test_invalid_auth_output_does_not_raise_a_false_alarm(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["/fake/claude", "auth", "status"],
            returncode=1,
            stdout="not json",
            stderr="failed",
        )

        with (
            patch.object(claude_usage, "claude_binary_path", return_value="/fake/claude"),
            patch.object(claude_usage.subprocess, "run", return_value=completed),
        ):
            status = claude_usage.claude_auth_status()

        self.assertEqual(status["checked"], False)
        self.assertEqual(status["requires_login"], False)
        self.assertEqual(status["reason"], "auth_status_invalid")

    def test_login_indicator_truth_table(self) -> None:
        cases = (
            ("logged in, fresh", True, True, True, False, "logged_in"),
            ("logged in, stale", True, True, True, True, "logged_in"),
            ("logged out, stale", True, False, True, True, "requires_login"),
            ("logged out, fresh", True, False, True, False, None),
            ("binary missing, fresh", False, None, True, False, None),
            ("invalid output, fresh", False, None, True, False, None),
            ("check timeout, stale", False, None, True, True, None),
            ("logged in, no snapshot", True, True, False, None, "logged_in"),
        )
        for name, checked, logged_in, available, stale, expected in cases:
            with self.subTest(name=name):
                actual = claude_usage.claude_login_indicator(
                    {"checked": checked, "logged_in": logged_in},
                    rate_available=available,
                    rate_stale=stale,
                )
                self.assertEqual(actual, expected)


class ClaudeLoginWarningMarkupTest(unittest.TestCase):
    def test_dashboard_places_relogin_warning_after_snapshot_age(self) -> None:
        import codex_claude_usage_web as web

        self.assertIn('const loginHealthy = authStatus.indicator === "logged_in";', web.INDEX_HTML)
        self.assertIn(
            'const requiresLogin = authStatus.indicator === "requires_login";',
            web.INDEX_HTML,
        )
        self.assertIn('tone: requiresLogin ? "bad" : "good"', web.INDEX_HTML)
        self.assertIn('headerExtras.splice(1, 0, {', web.INDEX_HTML)
        self.assertIn('bars + loginWarning + setup', web.INDEX_HTML)
        self.assertIn('claude auth login', web.INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
