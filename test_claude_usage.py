from __future__ import annotations

import json
import os
import tempfile
from contextlib import nullcontext
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
    @staticmethod
    def usage_row(identifier='message', output=5, cwd='/example', **usage):
        return {'type': 'assistant', 'timestamp': '2026-11-08T10:00:00Z',
                'requestId': identifier, 'cwd': cwd,
                'message': {'id': identifier, 'model': 'fixture',
                            'usage': {'input_tokens': 10, 'output_tokens': output, **usage}}}

    def test_streaming_updates_use_one_complete_snapshot_even_if_old_rows_follow(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            rows = [self.usage_row(output=5), self.usage_row(output=50), self.usage_row(output=7)]
            (project / 'one.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            result = claude_usage.aggregate_local_usage(home, 20, 30)
        self.assertEqual(result['unique_usage_records'], 1)
        self.assertEqual(result['duplicate_usage_records_skipped'], 2)
        self.assertEqual(result['token_totals']['total_tokens'], 60)
        for key in ('by_model', 'by_project', 'daily_usage'):
            self.assertEqual(result[key][0]['total_tokens'], 60)
            self.assertEqual(result[key][0]['requests'], 1)
        self.assertEqual(result['top_sessions'][0]['usage']['total_tokens'], 60)

    def test_cross_file_duplicates_choose_larger_snapshot_in_either_file_order(self):
        for outputs in ((5, 50), (50, 5)):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                project = home / 'projects'
                project.mkdir()
                for name, output in zip(('a.jsonl', 'b.jsonl'), outputs):
                    (project / name).write_text(json.dumps(self.usage_row(output=output))+'\n')
                result = claude_usage.aggregate_local_usage(home, 20, 30)
                self.assertEqual(result['token_totals']['total_tokens'], 60)
                self.assertEqual(result['unique_usage_records'], 1)
                self.assertEqual(result['duplicate_usage_records_skipped'], 1)

    def test_deduplication_does_not_mix_counters_from_different_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            rows = [self.usage_row(output=0, cache_read_input_tokens=90),
                    self.usage_row(output=40, input_tokens=80)]
            (project / 'one.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            totals = claude_usage.aggregate_local_usage(home, 20, 30)['token_totals']
        self.assertEqual(totals['total_tokens'], 120)
        self.assertEqual(totals['input_tokens'], 80)
        self.assertEqual(totals['cache_read_input_tokens'], 0)

    def test_long_project_paths_with_same_leaf_remain_distinct(self):
        paths = ['/work/' + segment * 80 + '/same-leaf' for segment in ('a', 'b')]
        self.assertEqual(claude_usage.short_path(paths[0]), claude_usage.short_path(paths[1]))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            rows = [self.usage_row(identifier=str(index), cwd=path) for index, path in enumerate(paths)]
            (project / 'one.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            projects = claude_usage.aggregate_local_usage(home, 20, 30)['by_project']
        self.assertEqual({row['project'] for row in projects}, set(paths))
        self.assertTrue(all(row['requests'] == 1 and row['total_tokens'] == 15 for row in projects))

    def test_transient_read_failure_is_retried_without_a_metadata_change(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            (project / 'one.jsonl').write_text(json.dumps(self.usage_row())+'\n')
            with patch.object(Path, 'open', side_effect=PermissionError('temporary read failure')):
                failed = claude_usage.aggregate_local_usage(home, 20, 30)
            recovered = claude_usage.aggregate_local_usage(home, 20, 30)
        self.assertEqual(failed['parse_or_read_errors'], 1)
        self.assertEqual(recovered['parse_or_read_errors'], 0)
        self.assertEqual(recovered['token_totals']['total_tokens'], 15)

    def test_partial_read_is_not_counted_or_cached(self):
        line = json.dumps(self.usage_row())+'\n'
        def interrupted():
            yield line
            raise OSError('read interrupted')
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            (project / 'one.jsonl').write_text(line)
            with patch.object(Path, 'open', return_value=nullcontext(interrupted())):
                failed = claude_usage.aggregate_local_usage(home, 20, 30)
            recovered = claude_usage.aggregate_local_usage(home, 20, 30)
        self.assertEqual(failed['token_totals']['total_tokens'], 0)
        self.assertEqual(failed['parse_or_read_errors'], 1)
        self.assertEqual(recovered['token_totals']['total_tokens'], 15)

    def test_replaced_file_is_rescanned_with_same_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            project = home / 'projects'
            project.mkdir()
            file = project / 'one.jsonl'
            file.write_text(json.dumps(self.usage_row(output=5))+'\n')
            before = file.stat()
            self.assertEqual(claude_usage.aggregate_local_usage(home, 20, 30)['token_totals']['total_tokens'], 15)
            replacement = home / 'replacement'
            replacement.write_text(json.dumps(self.usage_row(output=6))+'\n')
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(file)
            self.assertEqual(file.stat().st_size, before.st_size)
            self.assertEqual(file.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(claude_usage.aggregate_local_usage(home, 20, 30)['token_totals']['total_tokens'], 16)

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
