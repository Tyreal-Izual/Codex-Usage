from __future__ import annotations

import json
import tempfile
from pathlib import Path
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


class ClaudeTranscriptTest(unittest.TestCase):
    def test_streaming_and_cross_file_duplicates_are_counted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects' / 'example'
            project.mkdir(parents=True)
            row = {'type': 'assistant', 'timestamp': '2026-10-05T00:00:00Z',
                   'requestId': 'request-1', 'message': {'id': 'message-1', 'model': 'example',
                   'usage': {'input_tokens': 10, 'output_tokens': 5,
                             'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3}}}
            encoded = json.dumps(row)+'\n'
            (project/'one.jsonl').write_text(encoded*2+'broken\n')
            subagent = project/'subagents'
            subagent.mkdir()
            (subagent/'two.jsonl').write_text(encoded)
            result = claude_usage.aggregate_local_usage(home, 10, 30)
            self.assertEqual(result['unique_usage_records'], 1)
            self.assertEqual(result['duplicate_usage_records_skipped'], 2)
            self.assertEqual(result['token_totals']['total_tokens'], 20)
            self.assertEqual(result['parse_or_read_errors'], 1)

    def test_cache_reuses_unchanged_and_refreshes_appended_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            file = project/'one.jsonl'
            row = {'type':'assistant','timestamp':'2026-10-05T00:00:00Z',
                   'message':{'id':'1','usage':{'input_tokens':10}}}
            file.write_text(json.dumps(row)+'\n')
            with patch.object(claude_usage, 'scan_file', wraps=claude_usage.scan_file) as scan:
                claude_usage.aggregate_local_usage(home, 10, 30)
                claude_usage.aggregate_local_usage(home, 10, 30)
                self.assertEqual(scan.call_count, 1)
                row['message']['id'] = '2'
                with file.open('a') as handle: handle.write(json.dumps(row)+'\n')
                result = claude_usage.aggregate_local_usage(home, 10, 30)
                self.assertEqual(scan.call_count, 2)
                self.assertEqual(result['token_totals']['total_tokens'], 20)
            file.unlink()
            self.assertEqual(claude_usage.aggregate_local_usage(home, 10, 30)['unique_usage_records'], 0)

    def test_missing_projects_is_a_clean_empty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            result = claude_usage.aggregate_local_usage(Path(directory), 10, 30)
        self.assertFalse(result['available'])
        self.assertEqual(result['token_totals']['total_tokens'], 0)


if __name__ == "__main__":
    unittest.main()
